"""Hydrate agent result blocks by executing backend-validated SQL."""

from __future__ import annotations

from analytics.services.agent.logic.charts import auto_generate_chart
from analytics.services.pipeline.lookup_enrichment import enrich_id_columns_with_names
from analytics.services.pipeline.sql_execution import (
    normalize_numeric_nulls,
    rows_from_cache_or_run,
    run_readonly_select,
)
from analytics.services.sql_utils import extract_first_sql_from_combined

__all__ = ["hydrate_analytics_result", "run_readonly_select"]


def table_meta(rows: list[dict], truncated: bool = False) -> dict:
    row_count = len(rows or [])
    meta = {"row_count": row_count, "truncated": bool(truncated)}
    if not truncated:
        meta["total_count"] = row_count
    return meta


def strip_chart_data(chart_cfg: dict | None) -> dict | None:
    if not chart_cfg or not isinstance(chart_cfg, dict):
        return None
    out = {key: value for key, value in chart_cfg.items() if key != "data"}
    return out if out else None


class ResultHydrator:
    def __init__(
        self,
        *,
        result: dict,
        db,
        ctx,
        max_rows: int,
        tool_state: dict | None = None,
        user_query: str = "",
    ):
        self.result = result
        self.db = db
        self.ctx = ctx
        self.max_rows = max_rows
        self.tool_state = tool_state or {}
        self.user_query = user_query
        self.query_cache = self._query_cache()
        self.preserved_report = (result.get("report") or "").strip()

    def hydrate(self) -> dict:
        out_blocks = []
        for block in self.input_blocks():
            hydrated = self.hydrate_block(block)
            if hydrated:
                out_blocks.extend(hydrated)

        self.result["result_blocks"] = out_blocks
        self.apply_top_level_compat(out_blocks)
        self.apply_missing_summary(out_blocks)
        return self.result

    def input_blocks(self) -> list[dict]:
        blocks = list(self.result.get("result_blocks") or [])
        if not blocks:
            sql_flat = extract_first_sql_from_combined(self.result.get("sql_query") or "")
            if self.preserved_report:
                blocks.append({"kind": "text", "text": self.preserved_report})
            if sql_flat:
                blocks.append({"kind": "table", "sql_query": sql_flat})
        if not blocks and self.preserved_report:
            blocks = [{"kind": "text", "text": self.preserved_report}]
        return [block for block in blocks if isinstance(block, dict)]

    def hydrate_block(self, block: dict) -> list[dict]:
        kind = str(block.get("kind") or "text").lower()
        if kind not in {"text", "summary", "table", "chart"}:
            kind = "text"
        if kind in {"text", "summary"}:
            item = self.text_block(block, kind)
            return [item] if item else []
        if kind == "table":
            return [self.table_block(block)]
        if kind == "chart":
            chart = self.chart_block(block)
            return [chart] if chart else []
        return []

    @staticmethod
    def text_block(block: dict, kind: str) -> dict | None:
        item = {
            "kind": "summary" if kind == "summary" else "text",
            "title": block.get("title"),
            "text": block.get("text") or block.get("report") or "",
        }
        item = {key: value for key, value in item.items() if value is not None and value != ""}
        return item if item.get("text") else None

    def table_block(self, block: dict) -> dict:
        sql_q = str(block.get("sql_query") or "").strip()
        title = block.get("title")
        if not sql_q:
            return self.error_text(title, "*Table block is missing `sql_query` - nothing to fetch.*")

        rows, err, truncated = rows_from_cache_or_run(
            sql_q,
            self.db,
            self.ctx,
            self.max_rows,
            self.query_cache,
        )
        if err:
            return self.error_text(title, f"**Could not load table data.** {err}")

        row_out = self.clean_rows(rows or [])
        item = {
            "kind": "table",
            "sql_query": sql_q,
            "raw_data": row_out,
            **table_meta(row_out, truncated),
        }
        if title:
            item["title"] = title
        return item

    def chart_block(self, block: dict) -> dict | None:
        sql_q = str(block.get("sql_query") or "").strip()
        title = block.get("title")
        if not sql_q:
            return self.error_text(title, "*Chart block is missing `sql_query` - cannot plot.*")

        rows, err, truncated = rows_from_cache_or_run(
            sql_q,
            self.db,
            self.ctx,
            self.max_rows,
            self.query_cache,
        )
        if err:
            return self.error_text(title, f"**Could not load chart data.** {err}")

        row_out = self.clean_rows(rows or [])
        chart_config = auto_generate_chart(
            strip_chart_data(block.get("chart_config")),
            row_out,
            f"{title or ''} {sql_q}".strip(),
        )
        item = {"kind": "chart", "sql_query": sql_q, **table_meta(row_out, truncated)}
        if title:
            item["title"] = title
        if isinstance(chart_config, dict) and chart_config.get("data"):
            item["chart_config"] = chart_config
        elif isinstance(chart_config, list) and chart_config:
            item["chart_config"] = chart_config[0]
        else:
            return None
        return item

    def clean_rows(self, rows: list[dict]) -> list[dict]:
        return enrich_id_columns_with_names(normalize_numeric_nulls(rows), self.db)

    @staticmethod
    def error_text(title, text: str) -> dict:
        item = {"kind": "text", "text": text}
        if title:
            item["title"] = title
        return item

    def apply_top_level_compat(self, out_blocks: list[dict]) -> None:
        text_parts = [
            str(block.get("text") or "").strip()
            for block in out_blocks
            if block.get("kind") in {"text", "summary"}
            and str(block.get("text") or "").strip()
        ]
        if text_parts:
            self.result["report"] = "\n\n".join(text_parts)
        elif self.preserved_report:
            self.result["report"] = self.preserved_report

        first_sql = ""
        first_rows: list | None = None
        first_chart = None
        for block in out_blocks:
            if block.get("kind") == "table" and block.get("sql_query"):
                if not first_sql:
                    first_sql = str(block["sql_query"])
                if first_rows is None and isinstance(block.get("raw_data"), list):
                    first_rows = block["raw_data"]
            if block.get("kind") == "chart" and block.get("chart_config") and first_chart is None:
                first_chart = block.get("chart_config")

        if first_sql:
            self.result["sql_query"] = first_sql
        self.result["raw_data"] = first_rows if first_rows is not None else []
        self.result["chart_config"] = first_chart

    def apply_missing_summary(self, out_blocks: list[dict]) -> None:
        first_rows, table_block = self.first_table_rows(out_blocks)
        if first_rows is None:
            return

        report_text = str(self.result.get("report") or "").strip()
        has_text_block = any(
            block.get("kind") in {"text", "summary"}
            and str(block.get("text") or "").strip()
            for block in out_blocks
        )
        generic_fallback = "The AI did not produce a readable summary"
        if report_text and report_text != generic_fallback:
            return
        if has_text_block:
            return

        summary = self.summary_for_rows(
            first_rows,
            total_count=table_block.get("total_count") if table_block else None,
            truncated=bool(table_block.get("truncated")) if table_block else False,
        )
        summary_block = {"kind": "summary", "text": summary}
        self.result["result_blocks"] = [summary_block, *out_blocks]
        self.result["report"] = summary

    @staticmethod
    def first_table_rows(out_blocks: list[dict]) -> tuple[list | None, dict | None]:
        for block in out_blocks:
            if block.get("kind") == "table" and isinstance(block.get("raw_data"), list):
                return block["raw_data"], block
        return None, None

    def summary_for_rows(self, rows: list, *, total_count, truncated: bool) -> str:
        loaded_count = len(rows)
        if loaded_count == 0:
            return "No matching rows were found."

        cols = list(rows[0].keys()) if isinstance(rows[0], dict) else []
        field_text = f" Fields: {', '.join(cols[:8])}." if cols else ""
        if len(cols) > 8:
            field_text = f" Fields: {', '.join(cols[:8])} and {len(cols) - 8} more."
        query_hint = f" for `{self.user_query.strip()}`" if self.user_query.strip() else ""
        if truncated:
            return (
                f"Showing the first {loaded_count} matching rows{query_hint}. "
                f"The full count was not computed to keep the query fast.{field_text}"
            )
        total = total_count if isinstance(total_count, int) else loaded_count
        return f"Found {total} matching rows{query_hint}.{field_text}"

    def _query_cache(self) -> dict:
        query_cache = self.tool_state.get("query_cache") if isinstance(self.tool_state, dict) else {}
        return query_cache if isinstance(query_cache, dict) else {}


def hydrate_analytics_result(
    result: dict,
    db,
    ctx,
    max_rows: int,
    tool_state: dict | None = None,
    user_query: str = "",
) -> dict:
    return ResultHydrator(
        result=result,
        db=db,
        ctx=ctx,
        max_rows=max_rows,
        tool_state=tool_state,
        user_query=user_query,
    ).hydrate()
