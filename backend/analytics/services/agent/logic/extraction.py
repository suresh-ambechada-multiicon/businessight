"""Normalize and repair structured agent output."""

from langchain_core.utils.json import parse_partial_json

from analytics.schemas import AnalyticsResponse
from analytics.services.logger import get_logger
from analytics.services.sql_utils import (
    extract_first_sql_from_combined,
    extract_sql_blocks_from_combined,
    normalize_sql_key,
)

logger = get_logger("agent")


def _normalize_result_blocks(
    ans: dict | None,
    fallback_report: str,
    *,
    fallback_sql_query: str = "",
):
    """
    Normalize agent `result_blocks`. Table/chart rows and chart datasets are NOT
    trusted from the LLM — only `sql_query` and optional chart metadata survive.
    """
    if not isinstance(ans, dict):
        ans = {}

    blocks = ans.get("result_blocks") or ans.get("blocks") or []
    normalized: list[dict] = []
    if isinstance(blocks, list):
        for block in blocks:
            if hasattr(block, "model_dump"):
                block = block.model_dump()
            if not isinstance(block, dict):
                continue
            kind = str(block.get("kind") or "text").lower()
            if kind not in {"text", "summary", "chart", "table"}:
                kind = "text"
            item: dict = {"kind": kind}
            if block.get("title"):
                item["title"] = block["title"]
            block_sql = str(block.get("sql_query") or "").strip()
            if block_sql:
                item["sql_query"] = block_sql
            text = block.get("text") or block.get("report")
            if isinstance(text, str) and text.strip():
                item["text"] = text
            if kind == "chart":
                chart = block.get("chart_config")
                if isinstance(chart, dict):
                    # Keep type/labels only — never LLM-supplied datasets
                    slim = {k: v for k, v in chart.items() if k != "data"}
                    if slim:
                        item["chart_config"] = slim
            if kind in {"text", "summary"} and item.get("text"):
                normalized.append(item)
            elif kind == "table" and block_sql:
                normalized.append(item)
            elif kind == "chart" and block_sql:
                normalized.append(item)

    if normalized:
        return normalized

    # Legacy flat answer: narrative + optional primary SQL (no embedded rows)
    out: list[dict] = []
    if (fallback_report or "").strip():
        out.append({"kind": "text", "text": fallback_report.strip()})
    sql_blocks = extract_sql_blocks_from_combined(fallback_sql_query or "")
    for idx, sql in enumerate(sql_blocks, 1):
        item = {"kind": "table", "sql_query": sql}
        if len(sql_blocks) > 1:
            item["title"] = f"Query {idx}"
        out.append(item)
    return out


def extract_final_result(stream_data: dict, tool_state: dict, ctx=None) -> dict:
    """
    Parse the accumulated stream data and tool state into the final
    structured response dict with report, chart_config, raw_data, sql_query.
    """
    full_content = stream_data.get("full_content", "")
    full_tool_args_str = stream_data.get("full_tool_args_str", "")
    last_tool_args = stream_data.get("last_tool_args", {})
    last_non_empty_report = stream_data.get("last_non_empty_report", "")

    # Recovery data from tool execution
    # Prefer best_raw_data (largest result set) so aggregation queries don't
    # overwrite the actual list data the user wanted to see
    # Prefer explicit final dataset contract when available (more accurate than last/best heuristics).
    recovered_raw_data = (
        tool_state.get("final_raw_data")
        or tool_state.get("best_raw_data")
        or tool_state.get("last_raw_data")
    )
    recovered_sql_query = tool_state.get("final_sql_query") or tool_state.get(
        "last_sql_query", ""
    )

    # Parse the structured response.
    # Priority: complete tool_args > partial JSON parse > raw content fallback.
    # last_tool_args is the fully-parsed final tool call from LangChain and is
    # always more reliable than re-parsing the streaming token buffer which may
    # contain truncated or concatenated JSON fragments.
    if (
        last_tool_args
        and isinstance(last_tool_args, dict)
        and (last_tool_args.get("report") or last_tool_args.get("result_blocks"))
    ):
        final_result = last_tool_args
    else:
        try:
            raw_text = full_tool_args_str or full_content or ""
            if raw_text.strip().startswith("{"):
                final_result = parse_partial_json(raw_text)
            else:
                final_result = {
                    "report": last_non_empty_report
                    or raw_text
                    or "No output generated."
                }
        except Exception:
            final_result = {
                "report": last_non_empty_report
                or full_content
                or "Error parsing output"
            }

    # Unwrap nested response structures
    ans = final_result
    if isinstance(ans, dict):
        if "structured_response" in ans:
            ans = ans["structured_response"]
        elif "output" in ans:
            ans = ans["output"]

    # Combine all executed queries with their timings
    all_queries = tool_state.get("all_sql_queries", [])
    query_cache = (
        tool_state.get("query_cache", {}) if isinstance(tool_state, dict) else {}
    )
    combined_sql = ""
    if all_queries:
        for i, q_info in enumerate(all_queries):
            combined_sql += f"-- Query {i + 1} (Execution Time: {q_info['time']:.3f}s)\n{q_info['query']}\n\n"

    # Extract fields — never trust LLM-embedded row payloads or chart datasets
    if isinstance(ans, dict):
        report = ans.get("report") or last_non_empty_report or ""
        sql_query = (ans.get("sql_query") or recovered_sql_query or "").strip()
        if not sql_query:
            sql_query = combined_sql.strip()
    else:
        report = getattr(ans, "report", "") or last_non_empty_report or ""
        sql_query = (getattr(ans, "sql_query", "") or recovered_sql_query or "").strip()
        if not sql_query:
            sql_query = combined_sql.strip()

    sql_query_blob = sql_query
    sql_query = extract_first_sql_from_combined(sql_query_blob) if sql_query_blob else ""

    preview_raw: list = []
    if sql_query:
        nk = normalize_sql_key(sql_query)
        if nk and nk in query_cache:
            preview_raw = query_cache[nk]
    if not preview_raw and isinstance(recovered_raw_data, list):
        preview_raw = recovered_raw_data

    result_blocks = _normalize_result_blocks(
        ans if isinstance(ans, dict) else None,
        fallback_report=report,
        fallback_sql_query=sql_query_blob or combined_sql,
    )

    if not report and result_blocks:
        text_parts = [
            str(block.get("text") or "").strip()
            for block in result_blocks
            if isinstance(block, dict) and str(block.get("text") or "").strip()
        ]
        if text_parts:
            report = "\n\n".join(text_parts)

    # Regex extraction fallback if JSON parsing failed completely
    if (not report or report.strip() == "") and full_tool_args_str:
        import re

        # Look for "report": "..." allowing nested quotes if they are escaped (heuristic)
        match = re.search(
            r'"report"\s*:\s*"(.+?)"(?:\s*,\s*"\w+"\s*:|\s*})',
            full_tool_args_str,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            report = match.group(1).replace("\\n", "\n").replace('\\"', '"')

    # Fallback for empty report
    if (not report or report.strip() == "") and full_content:
        if full_content.strip().startswith("{"):
            try:
                pj = parse_partial_json(full_content)
                report = pj.get("report", "")
            except Exception:
                report = ""
        if not report:
            report = full_content

    has_data_block = any(
        isinstance(block, dict)
        and block.get("kind") in {"table", "chart"}
        and block.get("sql_query")
        for block in result_blocks
    )

    if not report or report.strip() == "":
        if has_data_block:
            report = ""
        elif preview_raw and isinstance(preview_raw, list) and len(preview_raw) > 0:
            cols = list(preview_raw[0].keys())
            report = (
                f"### Query returned {len(preview_raw)} rows\n\n"
                f"Fields: {', '.join(cols[:8])}"
            )
            if len(cols) > 8:
                report += f" and {len(cols) - 8} more"
        else:
            report = (
                "The analysis timed out before a SQL query or final answer was produced. "
                "Try a more specific question, choose a faster model, or save this as a direct SQL prompt."
            )

    _ctx = ctx.to_dict() if ctx else {}
    logger.info(
        "Result extracted",
        extra={
            "data": {
                **_ctx,
                "report_length": len(report),
                "block_count": len(result_blocks),
                "sql_queries_count": len(all_queries),
            }
        },
    )

    return {
        "report": report,
        "chart_config": None,
        "raw_data": [],
        "sql_query": sql_query,
        "result_blocks": result_blocks,
    }


def repair_missing_sql_result(
    llm,
    formatted_prompt: str,
    user_query: str,
    ctx=None,
    repair_reason: str = "",
) -> dict | None:
    """
    Generic repair pass when the agent exits without SQL.

    This does not execute or infer data. It asks the model to return the same
    structured contract from the schema/prompt only, or ask for clarification.
    """
    _ctx = ctx.to_dict() if ctx else {}
    repair_prompt = (
        formatted_prompt
        + "\n\nYou are now in finalization repair mode. Do not call tools. "
        "Return only the structured analytics response. If the user asks for data, "
        "include read-only SQL in table/chart result_blocks. For any broad business "
        "analytics query, infer the most likely fact table, grouping dimension, date "
        "column, and metrics from the schema. Prefer human-readable joined dimensions "
        "over IDs. Include sensible default metrics that exist, such as counts, distinct "
        "customers/users, total amount/revenue/value, averages, first/latest dates, and "
        "status/category breakdowns. State assumptions briefly. Ask for clarification only "
        "when no plausible fact table, date column, or requested grouping dimension exists."
    )
    if repair_reason:
        repair_prompt += f"\n\nPrevious output was invalid: {repair_reason}"
    try:
        structured_llm = llm.with_structured_output(AnalyticsResponse)
        repaired = structured_llm.invoke(
            [
                {"role": "system", "content": repair_prompt},
                {"role": "user", "content": user_query},
            ]
        )
        if hasattr(repaired, "model_dump"):
            repaired_dict = repaired.model_dump()
        elif isinstance(repaired, dict):
            repaired_dict = repaired
        else:
            repaired_dict = {}

        blocks = _normalize_result_blocks(
            repaired_dict,
            fallback_report=str(repaired_dict.get("report") or ""),
            fallback_sql_query=str(repaired_dict.get("sql_query") or ""),
        )
        report = str(repaired_dict.get("report") or "").strip()
        if not report:
            text_parts = [
                str(block.get("text") or "").strip()
                for block in blocks
                if isinstance(block, dict) and str(block.get("text") or "").strip()
            ]
            report = "\n\n".join(text_parts)

        sql_query = extract_first_sql_from_combined(
            str(repaired_dict.get("sql_query") or "")
        )
        if not sql_query:
            for block in blocks:
                if isinstance(block, dict) and block.get("sql_query"):
                    sql_query = extract_first_sql_from_combined(str(block["sql_query"]))
                    break

        logger.info(
            "SQL repair pass completed",
            extra={
                "data": {
                    **_ctx,
                    "block_count": len(blocks),
                    "has_sql": bool(sql_query),
                    "report_length": len(report),
                }
            },
        )
        if not report and not blocks and not sql_query:
            return None
        return {
            "report": report,
            "chart_config": None,
            "raw_data": [],
            "sql_query": sql_query,
            "result_blocks": blocks,
        }
    except Exception as exc:
        logger.warning(
            "SQL repair pass failed",
            exc_info=True,
            extra={"data": {**_ctx, "error": str(exc)[:300]}},
        )
        return None
