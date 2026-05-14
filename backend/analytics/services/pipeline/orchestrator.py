"""
Analytics Pipeline Orchestrator.

Handles the end-to-end flow of an analytics query:
1. Database connection & discovery
2. Agent initialization
3. Execution & streaming
4. Result hydration & telemetry
"""

import json
import time
from typing import Generator, Any

from django.core.cache import cache

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.services.agent.logic.extraction import (
    extract_final_result,
    repair_missing_sql_result,
)
from analytics.services.agent.core.llm import build_messages, init_llm
from analytics.services.agent.core.runware import (
    invoke_runware_analytics,
    stream_runware_verified_report,
)
from analytics.services.agent.logic.reporting import (
    _evidence_from_result,
    apply_verified_report,
)
from analytics.services.agent.logic.schema_context import build_schema_context
from analytics.services.agent.core.state import StreamResult
from analytics.services.agent.core.streaming import stream_agent
from analytics.services.agent.logic.table_retrieval import rank_tables_for_query
from analytics.services.agent.tools import create_tools, sql_max_rows_from_budget
from analytics.services.database.connection import (
    build_engine_args,
    create_database,
    detect_active_schema,
    detect_dialect,
    discover_tables,
    normalize_db_uri,
)
from analytics.services.llm import get_model_config
from analytics.services.logger import RequestContext, get_logger
from analytics.services.pipeline.hydration import hydrate_analytics_result
from analytics.services.pipeline.serialization import sanitize_for_tokens, sanitize_row, deep_sanitize
from analytics.services.prompts import SYSTEM_PROMPT
from analytics.services.status import send_status
from analytics.services.sql_utils import normalize_sql_key
from analytics.services.tokens import count_tokens, estimate_query_budget

logger = get_logger("pipeline")

class AnalyticsPipeline:
    def __init__(self, payload: AnalyticsRequest, ctx: RequestContext):
        self.payload = payload
        self.ctx = ctx
        self.db = None
        self.db_uri = None
        self.active_schema = None
        self.usable_tables = []
        self.history_entry = None
        self.connect_time = 0.0
        self.discover_time = 0.0
        
    def run(self) -> Generator[dict, None, None]:
        """Main execution loop."""
        try:
            yield from self._prepare()
            yield from self._execute()
        except Exception as e:
            yield from self._handle_error(e)

    def _prepare(self) -> Generator[dict, None, None]:
        """Phase 1: Connection & Discovery."""
        logger.info("Starting analytics pipeline", extra={"data": self.ctx.to_dict()})
        
        # Reset cancellation
        cache.delete(f"cancel_{self.payload.session_id}")

        # 1. Database Connection
        send_status(self.ctx.task_id, "Connecting to database...")
        start = time.time()
        self.db_uri = normalize_db_uri(self.payload.db_url.strip())
        engine_args = build_engine_args(self.db_uri)

        try:
            self.db_uri, self.active_schema = detect_active_schema(self.db_uri, engine_args, self.ctx)
            self.db = create_database(self.db_uri, engine_args, self.active_schema)
            with self.db._engine.connect() as conn:
                pass
        except Exception as e:
            raise RuntimeError(f"Database connection failed: {str(e)}")

        self.connect_time = round((time.time() - start) * 1000, 2)

        # 2. Table Discovery
        send_status(self.ctx.task_id, "Discovering database tables...")
        start = time.time()
        self.usable_tables = discover_tables(self.db, self.active_schema, self.ctx)
        self.discover_time = round((time.time() - start) * 1000, 2)

        msg = f"Connected to database. Discovered {len(self.usable_tables)} business tables." if self.usable_tables else "Connected to database, but found no business tables yet."
        yield {"event": "status", "data": {"message": msg}}

        # 3. Create History Entry
        self.history_entry = QueryHistory.objects.create(
            session_id=self.payload.session_id,
            query=self.payload.query,
            report="Analyzing...",
            task_id=self.ctx.task_id,
        )
        yield {"event": "query_id", "data": {"id": self.history_entry.id}}

    def _execute(self) -> Generator[dict, None, None]:
        """Phase 2: Agent Execution."""
        exec_model = self.payload.executor_model or self.payload.model
        model_config = get_model_config(exec_model)

        # Schema & Prompt setup
        ranked_tables = rank_tables_for_query(self.usable_tables, self.payload.query, self.ctx.db_uri_hash)
        schema_context = build_schema_context(self.usable_tables, self.active_schema, self.db, self.ctx, table_rank_order=ranked_tables)
        
        formatted_prompt = SYSTEM_PROMPT.replace("{db_dialect}", detect_dialect(self.db_uri)).replace("{db_schema}", schema_context)
        
        agent_query = self.payload.query
        if getattr(self.payload, "direct_sql", None):
            agent_query += f"\n\nExecute this exact SQL query:\n```sql\n{self.payload.direct_sql}\n```"

        messages = build_messages(self.payload.session_id, agent_query)
        budget = estimate_query_budget(model_config, formatted_prompt, messages)
        tools, tool_state = create_tools(self.db, self.usable_tables, self.ctx, budget)

        if model_config.provider == "runware":
            result, runware_usage = self._run_runware_sql_loop(
                exec_model=exec_model,
                formatted_prompt=formatted_prompt,
                agent_query=agent_query,
                budget=budget,
                tool_state=tool_state,
            )
            if self._is_cancelled():
                self._finalize_cancellation()
                return
            send_status(self.ctx.task_id, "Writing final report with Runware...")
            verified_report = ""
            thinking_steps_acc = ""
            report_usage: dict = {}
            try:
                report_stream = stream_runware_verified_report(
                    model=exec_model,
                    api_key=self.payload.api_key,
                    user_query=self.payload.query,
                    evidence=_evidence_from_result(result),
                    llm_config=self.payload.llm_config,
                    usage_sink=report_usage,
                    cancel_checker=self._is_cancelled,
                    ctx=self.ctx,
                    query_history_id=self.history_entry.id if self.history_entry else None,
                )
                while True:
                    if self._is_cancelled():
                        report_stream.close()
                        self._finalize_cancellation()
                        return
                    try:
                        chunk = next(report_stream)
                        if "reasoning" in chunk:
                            thinking_steps_acc += chunk["reasoning"]
                            yield {
                                "event": "thinking",
                                "data": {"content": chunk["reasoning"]},
                            }
                        if "report" in chunk:
                            verified_report = chunk["report"]
                            yield {
                                "event": "report",
                                "data": {"content": verified_report, "partial": True},
                            }
                        if "usage" in chunk:
                            # Forward live usage update if needed, though finalize handles it too
                            pass
                    except StopIteration as done:
                        verified_report = done.value or verified_report
                        break
                if report_usage.get("_cancelled"):
                    self._finalize_cancellation()
                    return
            except Exception as exc:
                logger.warning(
                    "Runware streaming verified report failed",
                    exc_info=True,
                    extra={
                        "data": {
                            **self.ctx.to_dict(),
                            "error": str(exc)[:300],
                        }
                    },
                )
            if verified_report:
                result = apply_verified_report(result, verified_report)
            if thinking_steps_acc:
                result["thinking_steps"] = thinking_steps_acc
            result["_actual_usage"] = self._merge_actual_usage(
                runware_usage,
                report_usage,
            )
            yield from self._finalize(
                result,
                tool_state,
                budget,
                model_config,
                {
                    "full_content": result.get("report", ""),
                    "full_tool_args_str": json.dumps(result.get("result_blocks") or []),
                },
            )
            return
        
        llm = init_llm(exec_model, self.payload.api_key, self.payload.llm_config, self.ctx)
        
        from deepagents import create_deep_agent
        agent = create_deep_agent(model=llm, tools=tools, system_prompt=formatted_prompt, response_format=AnalyticsResponse)

        result_holder = StreamResult()
        for chunk in stream_agent(agent, messages, self.payload.session_id, result_holder, self.ctx):
            yield chunk

        if result_holder.cancelled:
            self._finalize_cancellation()
            return

        if result_holder.has_error:
            raise RuntimeError("Agent execution failed")

        # Extraction & Hydration
        result = extract_final_result(result_holder.data, tool_state, self.ctx)
        if self._needs_sql_repair(result, tool_state):
            send_status(self.ctx.task_id, "Recovering SQL from schema...")
            repaired = repair_missing_sql_result(
                llm,
                formatted_prompt,
                self.payload.query,
                self.ctx,
                repair_reason="Agent exited without a SQL query or final data block.",
            )
            if repaired and not self._needs_sql_repair(repaired, tool_state):
                result = repaired
        send_status(self.ctx.task_id, "Loading result data...")
        result = hydrate_analytics_result(result, self.db, self.ctx, sql_max_rows_from_budget(budget), tool_state, user_query=self.payload.query)

        yield from self._finalize(result, tool_state, budget, model_config, result_holder.data)

    def _run_runware_sql_loop(
        self,
        *,
        exec_model: str,
        formatted_prompt: str,
        agent_query: str,
        budget: dict,
        tool_state: dict,
    ) -> tuple[dict, dict]:
        max_rounds = 6
        result: dict | None = None
        runware_usage: dict = {}
        executed_sql_keys: set[str] = set()

        for round_idx in range(max_rounds):
            if self._is_cancelled():
                self._finalize_cancellation()
                return result or {"report": "", "result_blocks": [], "raw_data": [], "chart_config": None, "sql_query": ""}, runware_usage

            is_first = round_idx == 0
            if is_first:
                send_status(self.ctx.task_id, "Generating SQL with Runware...")
                followup_context = None
                repair_context = None
            else:
                send_status(
                    self.ctx.task_id,
                    f"Reviewing executed results with Runware ({round_idx + 1}/{max_rounds})...",
                )
                followup_context = self._runware_followup_context(result or {}, executed_sql_keys)
                repair_context = (
                    self._runware_repair_context(result or {}, round_idx - 1)
                    if self._needs_runware_sql_retry(result or {})
                    else None
                )

            planned = invoke_runware_analytics(
                model=exec_model,
                api_key=self.payload.api_key,
                formatted_prompt=formatted_prompt,
                user_query=agent_query,
                llm_config=self.payload.llm_config,
                ctx=self.ctx,
                query_history_id=self.history_entry.id if self.history_entry else None,
                repair_context=repair_context,
                followup_context=followup_context,
                phase=f"analytics_sql_round_{round_idx + 1}",
            )
            runware_usage = self._merge_actual_usage(
                runware_usage,
                planned.pop("_runware_usage", {}) if isinstance(planned, dict) else {},
            )

            send_status(self.ctx.task_id, f"Loading SQL result data ({round_idx + 1}/{max_rounds})...")
            hydrated = hydrate_analytics_result(
                planned,
                self.db,
                self.ctx,
                sql_max_rows_from_budget(budget),
                tool_state,
                user_query=self.payload.query,
            )

            if result is None:
                result = hydrated
                executed_sql_keys.update(self._result_sql_keys(result))
                continue

            merged, new_sql_count = self._merge_runware_results(result, hydrated, executed_sql_keys)
            result = merged
            if new_sql_count == 0:
                break
            executed_sql_keys.update(self._result_sql_keys(hydrated))

        return result or {"report": "", "result_blocks": [], "raw_data": [], "chart_config": None, "sql_query": ""}, runware_usage

    def _needs_sql_repair(self, result: dict, tool_state: dict) -> bool:
        """True when the agent produced neither executable SQL nor recovered SQL data."""
        if result.get("sql_query"):
            return False
        for block in result.get("result_blocks") or []:
            if isinstance(block, dict) and block.get("sql_query"):
                return False
        if tool_state.get("final_sql_query") or tool_state.get("last_sql_query"):
            return False
        report = str(result.get("report") or "").lower()
        return "timed out before a sql query" in report or not report.strip()

    def _needs_runware_sql_retry(self, result: dict) -> bool:
        blocks = [
            block
            for block in result.get("result_blocks") or []
            if isinstance(block, dict)
            and block.get("kind") in {"table", "chart"}
            and block.get("sql_query")
        ]
        if not blocks:
            return True
        return all(
            int(
                block.get("row_count")
                or (len(block.get("raw_data")) if isinstance(block.get("raw_data"), list) else 0)
                or 0
            )
            == 0
            for block in blocks
        )

    def _result_sql_keys(self, result: dict) -> set[str]:
        keys: set[str] = set()
        for block in result.get("result_blocks") or []:
            if not isinstance(block, dict):
                continue
            key = normalize_sql_key(str(block.get("sql_query") or ""))
            if key:
                keys.add(key)
        key = normalize_sql_key(str(result.get("sql_query") or ""))
        if key:
            keys.add(key)
        return keys

    def _merge_runware_results(
        self,
        base: dict,
        incoming: dict,
        executed_sql_keys: set[str],
    ) -> tuple[dict, int]:
        merged = dict(base or {})
        blocks = list(merged.get("result_blocks") or [])
        new_sql_count = 0

        for block in incoming.get("result_blocks") or []:
            if not isinstance(block, dict):
                continue
            key = normalize_sql_key(str(block.get("sql_query") or ""))
            if key:
                if key in executed_sql_keys:
                    continue
                new_sql_count += 1
            else:
                continue
            blocks.append(block)

        merged["result_blocks"] = blocks
        if not merged.get("report") and incoming.get("report"):
            merged["report"] = incoming.get("report")
        if not merged.get("sql_query") and incoming.get("sql_query"):
            merged["sql_query"] = incoming.get("sql_query")
        if not merged.get("raw_data") and incoming.get("raw_data"):
            merged["raw_data"] = incoming.get("raw_data")
        if not merged.get("chart_config") and incoming.get("chart_config"):
            merged["chart_config"] = incoming.get("chart_config")
        return merged, new_sql_count

    def _runware_followup_context(self, result: dict, executed_sql_keys: set[str]) -> dict:
        evidence = _evidence_from_result(result)
        compact_blocks = []
        for block in evidence.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            compact_blocks.append(
                {
                    "kind": block.get("kind"),
                    "title": block.get("title"),
                    "sql_query": block.get("sql_query"),
                    "row_count": block.get("row_count"),
                    "total_count": block.get("total_count"),
                    "truncated": block.get("truncated"),
                    "loaded_sample_rows": block.get("loaded_sample_rows"),
                    "columns": block.get("columns"),
                    "column_stats": block.get("column_stats"),
                    "sample_rows": (block.get("sample_rows") or [])[:30],
                    "chart_type": block.get("chart_type"),
                    "labels": (block.get("labels") or [])[:40],
                }
            )
        return {
            "user_query": self.payload.query,
            "max_total_sql_rounds": 6,
            "executed_sql_keys": sorted(executed_sql_keys),
            "executed_blocks": compact_blocks,
            "instruction": (
                "Return additional SQL blocks only if the current evidence is missing "
                "important details needed to answer the user fully. Otherwise return "
                "an empty result_blocks array."
            ),
        }

    def _runware_repair_context(self, result: dict, attempt: int) -> dict:
        blocks = []
        for block in result.get("result_blocks") or []:
            if not isinstance(block, dict) or not block.get("sql_query"):
                continue
            blocks.append(
                {
                    "kind": block.get("kind"),
                    "title": block.get("title"),
                    "sql_query": block.get("sql_query"),
                    "row_count": block.get("row_count"),
                    "truncated": block.get("truncated"),
                    "columns": list(block.get("raw_data", [{}])[0].keys())
                    if block.get("raw_data")
                    else [],
                }
            )
        return {
            "attempt": attempt + 1,
            "reason": "The previous SQL produced no rows or no executable data block.",
            "user_query": self.payload.query,
            "previous_blocks": blocks,
            "instruction": (
                "Generate corrected SQL that directly answers the same user question. "
                "Prefer less restrictive filters, verify the correct fact/detail table, "
                "and use appropriate joins to human-readable dimensions when needed."
            ),
        }

    def _is_cancelled(self) -> bool:
        if cache.get(f"cancel_{self.payload.session_id}"):
            cache.delete(f"cancel_{self.payload.session_id}")
            return True
        return False

    def _merge_actual_usage(self, *parts: dict | None) -> dict:
        merged = {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "estimated_cost": 0.0,
        }
        for part in parts:
            if not isinstance(part, dict):
                continue
            merged["input_tokens"] += int(part.get("input_tokens") or 0)
            merged["output_tokens"] += int(part.get("output_tokens") or 0)
            merged["thinking_tokens"] += int(part.get("thinking_tokens") or 0)
            merged["estimated_cost"] += float(part.get("estimated_cost") or 0)
        return merged

    def _finalize(self, result, tool_state, budget, model_config, stream_data) -> Generator[dict, None, None]:
        """Phase 3: Telemetry & Final Save."""
        exec_time = time.time() - self.ctx.start_time
        actual_usage = result.pop("_actual_usage", None) if isinstance(result, dict) else None
        
        # If no explicit actual_usage (Runware path), check if standard agent path captured usage
        if not actual_usage and isinstance(stream_data, dict) and stream_data.get("usage"):
            su = stream_data["usage"]
            if su.get("input_tokens") or su.get("output_tokens"):
                actual_usage = {
                    "input_tokens": su.get("input_tokens"),
                    "output_tokens": su.get("output_tokens"),
                    "thinking_tokens": su.get("thinking_tokens"),
                    "estimated_cost": (su.get("input_tokens", 0) / 1_000_000) * model_config.cost_per_1m_input +
                                      ((su.get("output_tokens", 0) + su.get("thinking_tokens", 0)) / 1_000_000) * model_config.cost_per_1m_output
                }

        if not isinstance(actual_usage, dict) or not (
            actual_usage.get("input_tokens")
            or actual_usage.get("output_tokens")
            or actual_usage.get("estimated_cost")
        ):
            # Token usage estimation (for standard agents)
            # 1. Output tokens: content + tool args + final report
            out_tokens = int((count_tokens(stream_data.get("full_content", "")) + count_tokens(stream_data.get("full_tool_args_str", "")) + count_tokens(result.get("report", ""))) * 1.05)
            
            # 2. Input tokens: account for recursive turns
            # Every turn sends back the entire history.
            initial_in = int(budget["total_used"])
            steps = int(stream_data.get("steps_count") or 0)
            
            # Total input tokens ≈ initial_prompt * (steps + 1) + roughly half of history_tokens_acc per step
            # This is a much better approximation than just the initial prompt.
            in_tokens = int((initial_in * (steps + 1)) + (stream_data.get("history_tokens_acc", 0) * (steps / 2)) * 1.1)
            
            cost = (in_tokens / 1_000_000) * model_config.cost_per_1m_input + (out_tokens / 1_000_000) * model_config.cost_per_1m_output
            think_tokens = 0
        else:
            in_tokens = int(actual_usage.get("input_tokens") or 0)
            out_tokens = int(actual_usage.get("output_tokens") or 0)
            think_tokens = int(actual_usage.get("thinking_tokens") or 0)
            cost = float(actual_usage.get("estimated_cost") or 0)

        # Update History
        self.history_entry.report = result["report"]
        self.history_entry.chart_config = result["chart_config"]
        self.history_entry.raw_data = [sanitize_row(r) for r in result["raw_data"]] if isinstance(result.get("raw_data"), list) else None
        self.history_entry.sql_query = result["sql_query"]
        self.history_entry.execution_time = exec_time
        self.history_entry.input_tokens = in_tokens
        self.history_entry.output_tokens = out_tokens
        self.history_entry.thinking_tokens = think_tokens
        self.history_entry.thinking_steps = result.get("thinking_steps")
        self.history_entry.estimated_cost = round(cost, 6)
        self.history_entry.result_blocks = deep_sanitize(result.get("result_blocks"))
        self.history_entry.save()

        yield {"event": "usage", "data": {"input_tokens": in_tokens, "output_tokens": out_tokens, "thinking_tokens": think_tokens, "estimated_cost": round(cost, 6)}}
        yield {"event": "result", "data": {**result, "execution_time": exec_time, "usage": {"input_tokens": in_tokens, "output_tokens": out_tokens, "thinking_tokens": think_tokens}, "done": True}}

        logger.info("Pipeline completed", extra={"data": {**self.ctx.to_dict(), "total_time_ms": round(exec_time * 1000, 2)}})

    def _finalize_cancellation(self):
        self.history_entry.report = "_Analysis cancelled by user._"
        self.history_entry.execution_time = -1
        self.history_entry.save()

    def _handle_error(self, e: Exception) -> Generator[dict, None, None]:
        import traceback
        err_msg = str(e)
        logger.error("Pipeline error", exc_info=True, extra={"data": {**self.ctx.to_dict(), "error": err_msg}})
        
        if self.history_entry:
            self.history_entry.report = f"Error: {err_msg}"
            self.history_entry.execution_time = self.history_entry.execution_time or 0.1
            self.history_entry.save()
            
        yield {"event": "error", "data": {"message": f"Error: {err_msg}"}}
