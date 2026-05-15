from __future__ import annotations

from typing import Callable

from analytics.services.agent.logic.reporting import _evidence_from_result
from analytics.services.agent.tools import sql_max_rows_from_budget
from analytics.services.database.value_search import search_database_values
from analytics.services.pipeline.hydration import hydrate_analytics_result
from analytics.services.runware import invoke_runware_analytics
from analytics.services.runware.parsing import sanitize_analytics_payload
from analytics.services.sql_utils import normalize_sql_key
from analytics.services.status import send_status


def empty_runware_result() -> dict:
    return {
        "report": "",
        "result_blocks": [],
        "raw_data": [],
        "chart_config": None,
        "sql_query": "",
    }


class RunwareExecutionLoop:
    """Multi-round Runware SQL planning + backend hydration loop."""

    def __init__(
        self,
        *,
        payload,
        ctx,
        db,
        usable_tables: list[str],
        history_entry,
        is_cancelled: Callable[[], bool],
        finalize_cancellation: Callable[[], None],
        planner: Callable[..., dict] | None = None,
        planner_label: str = "Runware",
    ):
        self.payload = payload
        self.ctx = ctx
        self.db = db
        self.usable_tables = usable_tables
        self.history_entry = history_entry
        self.is_cancelled = is_cancelled
        self.finalize_cancellation = finalize_cancellation
        self.planner = planner or invoke_runware_analytics
        self.planner_label = planner_label

    def run(
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
            if self.is_cancelled():
                self.finalize_cancellation()
                return result or empty_runware_result(), runware_usage

            is_first = round_idx == 0
            if is_first:
                send_status(self.ctx.task_id, f"Generating SQL evidence pack with {self.planner_label}...")
                value_search = search_database_values(
                    self.db,
                    user_query=self.payload.query,
                    table_names=self._ranked_tables(),
                    ctx=self.ctx,
                    max_matches=8,
                )
                followup_context = (
                    {
                        "value_search": value_search,
                        "instruction": (
                            "User terms may be stored as row values, not table or column names. "
                            "If value_search has matches, prioritize those table/column/value locations "
                            "when generating SQL."
                        ),
                    }
                    if value_search.get("matches")
                    else None
                )
                repair_context = None
            else:
                send_status(
                    self.ctx.task_id,
                    f"Reviewing executed results with {self.planner_label} ({round_idx + 1}/{max_rounds})...",
                )
                followup_context = self.followup_context(result or {}, executed_sql_keys)
                if self.needs_sql_retry(result or {}):
                    followup_context["value_search"] = search_database_values(
                        self.db,
                        user_query=self.payload.query,
                        table_names=self._ranked_tables(),
                        ctx=self.ctx,
                    )
                repair_context = (
                    self.repair_context(result or {}, round_idx - 1)
                    if self.needs_sql_retry(result or {})
                    else None
                )

            planned = self.planner(
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
            runware_usage = self.merge_usage(
                runware_usage,
                planned.pop("_planner_usage", {}) if isinstance(planned, dict) else {},
                planned.pop("_runware_usage", {}) if isinstance(planned, dict) else {},
            )
            planned = sanitize_analytics_payload(planned if isinstance(planned, dict) else {})

            send_status(
                self.ctx.task_id,
                f"Loading SQL result data ({round_idx + 1}/{max_rounds})...",
            )
            hydrated = hydrate_analytics_result(
                planned,
                self.db,
                self.ctx,
                sql_max_rows_from_budget(budget),
                tool_state,
                user_query=self.payload.query,
            )

            if result is None:
                result = self.dedupe_result_blocks(hydrated)
                executed_sql_keys.update(self.result_sql_keys(hydrated))
                if self.has_sufficient_evidence(result):
                    break
                continue

            result, new_sql_count = self.merge_results(
                result,
                hydrated,
                executed_sql_keys,
            )
            if new_sql_count == 0:
                break
            executed_sql_keys.update(self.result_sql_keys(hydrated))
            if self.has_sufficient_evidence(result):
                break

        return result or empty_runware_result(), runware_usage

    @staticmethod
    def merge_usage(*parts: dict | None) -> dict:
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

    @staticmethod
    def needs_sql_retry(result: dict) -> bool:
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

    def has_sufficient_evidence(self, result: dict) -> bool:
        if self.needs_sql_retry(result):
            return False
        count = self.non_empty_data_block_count(result)
        if self.wants_multi_evidence():
            return count >= 2
        return count >= 1

    @staticmethod
    def non_empty_data_block_count(result: dict) -> int:
        count = 0
        for block in result.get("result_blocks") or []:
            if not isinstance(block, dict):
                continue
            if block.get("kind") not in {"table", "chart"} or not block.get("sql_query"):
                continue
            row_count = int(
                block.get("row_count")
                or (len(block.get("raw_data")) if isinstance(block.get("raw_data"), list) else 0)
                or 0
            )
            if row_count > 0:
                count += 1
        return count

    def wants_multi_evidence(self) -> bool:
        query = str(getattr(self.payload, "query", "") or "").lower()
        if getattr(self.payload, "direct_sql", None) or getattr(self.payload, "direct_sqls", None):
            return False
        multi_terms = {
            "analysis",
            "analyze",
            "detail",
            "details",
            "trend",
            "compare",
            "comparison",
            "breakdown",
            "summary",
            "overview",
            "insight",
            "performance",
            "ranking",
            "top",
            "highest",
            "lowest",
            "monthly",
            "quarterly",
            "yearly",
            "wise",
            " by ",
            " per ",
            " grouped ",
        }
        return any(term in query for term in multi_terms)

    @staticmethod
    def result_sql_keys(result: dict) -> set[str]:
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

    @staticmethod
    def dedupe_result_blocks(result: dict) -> dict:
        deduped = dict(result or {})
        blocks = []
        existing_signatures = set()

        for block in deduped.get("result_blocks") or []:
            if not isinstance(block, dict):
                continue
            if block.get("kind") not in {"table", "chart"}:
                blocks.append(block)
                continue
            signature = RunwareExecutionLoop.block_signature(block)
            if signature in existing_signatures:
                continue
            existing_signatures.add(signature)
            blocks.append(block)

        deduped["result_blocks"] = blocks
        return deduped

    @staticmethod
    def merge_results(
        base: dict,
        incoming: dict,
        executed_sql_keys: set[str],
    ) -> tuple[dict, int]:
        merged = dict(base or {})
        blocks = list(merged.get("result_blocks") or [])
        existing_signatures = {
            RunwareExecutionLoop.block_signature(block)
            for block in blocks
            if isinstance(block, dict)
        }
        new_sql_count = 0

        for block in incoming.get("result_blocks") or []:
            if not isinstance(block, dict):
                continue
            key = normalize_sql_key(str(block.get("sql_query") or ""))
            if key:
                if key in executed_sql_keys:
                    continue
            else:
                continue
            signature = RunwareExecutionLoop.block_signature(block)
            if signature in existing_signatures:
                continue
            existing_signatures.add(signature)
            new_sql_count += 1
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

    @staticmethod
    def block_signature(block: dict) -> tuple:
        kind = block.get("kind")
        rows = block.get("raw_data") if isinstance(block.get("raw_data"), list) else []
        columns = tuple(rows[0].keys()) if rows and isinstance(rows[0], dict) else ()
        sample = tuple(
            tuple(str(row.get(col, "")) for col in columns[:6])
            for row in rows[:5]
            if isinstance(row, dict)
        )
        return kind, columns[:8], sample

    def followup_context(self, result: dict, executed_sql_keys: set[str]) -> dict:
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

    def repair_context(self, result: dict, attempt: int) -> dict:
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
                "and use appropriate joins to human-readable dimensions when needed. "
                "If `value_search` found matching table/column/value locations, use those "
                "tables and columns as the primary clue. User terms may be stored as row "
                "values, not table or column names."
            ),
        }

    def _ranked_tables(self) -> list[str]:
        try:
            from analytics.services.agent.logic.table_retrieval import rank_tables_for_query

            return rank_tables_for_query(self.usable_tables, self.payload.query, self.ctx.db_uri_hash)
        except Exception:
            return self.usable_tables
