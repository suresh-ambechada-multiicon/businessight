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
from typing import Generator

from django.core.cache import cache

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.services.agent.logic.extraction import (
    extract_final_result,
    repair_missing_sql_result,
)
from analytics.services.agent.core.llm import build_messages, init_llm
from analytics.services.agent.core.runware import (
    stream_runware_verified_report,
)
from analytics.services.agent.logic.reporting import (
    _evidence_from_result,
    apply_verified_answer,
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
from analytics.services.pipeline.finalization import PipelineFinalizer
from analytics.services.pipeline.runware_loop import RunwareExecutionLoop
from analytics.services.prompts import SYSTEM_PROMPT
from analytics.services.sql_utils import (
    extract_sql_blocks_from_combined,
    format_sql_blocks,
    normalize_sql_key,
)
from analytics.services.status import send_status
from analytics.services.tokens import estimate_query_budget

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
        direct_sql_blocks = self._direct_sql_blocks()
        if direct_sql_blocks:
            sql_label = "queries" if len(direct_sql_blocks) > 1 else "query"
            agent_query += (
                f"\n\nExecute these exact SQL {sql_label} as separate output blocks "
                f"and preserve their order:\n```sql\n{format_sql_blocks(direct_sql_blocks)}\n```"
            )

        messages = build_messages(self.payload.session_id, agent_query)
        budget = estimate_query_budget(model_config, formatted_prompt, messages)
        tools, tool_state = create_tools(self.db, self.usable_tables, self.ctx, budget)

        if model_config.provider == "runware":
            result, runware_usage = RunwareExecutionLoop(
                payload=self.payload,
                ctx=self.ctx,
                db=self.db,
                usable_tables=self.usable_tables,
                history_entry=self.history_entry,
                is_cancelled=self._is_cancelled,
                finalize_cancellation=self._finalize_cancellation,
            ).run(
                exec_model=exec_model,
                formatted_prompt=formatted_prompt,
                agent_query=agent_query,
                budget=budget,
                tool_state=tool_state,
            )
            if self._is_cancelled():
                self._finalize_cancellation()
                return
            send_status(self.ctx.task_id, "Writing final answer with Runware...")
            verified_answer: dict = {}
            verified_overview = ""
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
                            verified_overview = chunk["report"]
                            yield {
                                "event": "report",
                                "data": {"content": verified_overview, "partial": True},
                            }
                        if "usage" in chunk:
                            # Forward live usage update if needed, though finalize handles it too
                            pass
                    except StopIteration as done:
                        verified_answer = done.value or {}
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
            if verified_answer:
                result = apply_verified_answer(result, verified_answer)
            elif verified_overview:
                result = apply_verified_answer(
                    result,
                    {"overview": verified_overview, "block_insights": []},
                )
            if thinking_steps_acc:
                result["thinking_steps"] = thinking_steps_acc
            result["_actual_usage"] = PipelineFinalizer.merge_usage(
                runware_usage,
                report_usage,
            )
            yield from PipelineFinalizer(
                history_entry=self.history_entry,
                ctx=self.ctx,
            ).finalize(
                result=result,
                budget=budget,
                model_config=model_config,
                stream_data={
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

        yield from PipelineFinalizer(
            history_entry=self.history_entry,
            ctx=self.ctx,
        ).finalize(
            result=result,
            budget=budget,
            model_config=model_config,
            stream_data=result_holder.data,
        )

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

    def _is_cancelled(self) -> bool:
        if cache.get(f"cancel_{self.payload.session_id}"):
            cache.delete(f"cancel_{self.payload.session_id}")
            return True
        return False

    def _direct_sql_blocks(self) -> list[str]:
        sql_blocks: list[str] = []
        for sql in getattr(self.payload, "direct_sqls", None) or []:
            sql_blocks.extend(extract_sql_blocks_from_combined(sql))
        direct_sql = getattr(self.payload, "direct_sql", None)
        if direct_sql:
            sql_blocks.extend(extract_sql_blocks_from_combined(direct_sql))

        out: list[str] = []
        seen: set[str] = set()
        for sql in sql_blocks:
            key = normalize_sql_key(sql)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(sql)
        return out

    def _finalize_cancellation(self):
        PipelineFinalizer(history_entry=self.history_entry, ctx=self.ctx).cancel()

    def _handle_error(self, e: Exception) -> Generator[dict, None, None]:
        err_msg = str(e)
        logger.error("Pipeline error", exc_info=True, extra={"data": {**self.ctx.to_dict(), "error": err_msg}})
        
        PipelineFinalizer(history_entry=self.history_entry, ctx=self.ctx).mark_error(e)
             
        yield {"event": "error", "data": {"message": f"Error: {err_msg}"}}
