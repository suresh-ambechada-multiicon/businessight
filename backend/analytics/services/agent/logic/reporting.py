"""Final answer writing from backend-executed SQL evidence."""

import json

from analytics.schemas import VerifiedReportResponse
from analytics.services.logger import get_logger

logger = get_logger("agent")


def _column_stats(rows: list[dict], columns: list[str]) -> dict:
    """Compute lightweight per-column stats so the report LLM understands
    the full dataset shape, not just the sample rows."""
    stats: dict[str, dict] = {}
    for col in columns:
        values = [r.get(col) for r in rows if r.get(col) is not None]
        if not values:
            continue
        entry: dict = {"non_null": len(values)}
        # Distinct count for categorical understanding
        try:
            distinct = set(str(v) for v in values)
            entry["distinct"] = len(distinct)
            if len(distinct) <= 15:
                entry["unique_values"] = sorted(distinct)
        except Exception:
            pass
        # Min/max for numerics
        numeric_vals = [v for v in values if isinstance(v, (int, float))]
        if numeric_vals:
            entry["min"] = min(numeric_vals)
            entry["max"] = max(numeric_vals)
            entry["sum"] = round(sum(numeric_vals), 2)
        stats[col] = entry
    return stats


def _evidence_from_result(result: dict, *, max_rows_per_block: int = 80) -> dict:
    evidence_blocks: list[dict] = []
    for idx, block in enumerate(result.get("result_blocks") or []):
        if not isinstance(block, dict):
            continue
        kind = block.get("kind")
        if kind == "table" and block.get("sql_query"):
            rows = (
                block.get("raw_data") if isinstance(block.get("raw_data"), list) else []
            )
            columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
            truncated = bool(block.get("truncated"))
            loaded_rows = len(rows)
            evidence_block = {
                "index": idx,
                "kind": "table",
                "title": block.get("title") or "",
                "sql_query": block.get("sql_query"),
                "total_count": block.get("total_count"),
                "truncated": truncated,
                "loaded_sample_rows": loaded_rows,
                "columns": columns,
                "column_stats": _column_stats(rows, columns),
                "sample_rows": rows[:max_rows_per_block],
            }
            if not truncated:
                evidence_block["row_count"] = block.get("row_count", loaded_rows)
            else:
                evidence_block["row_count"] = None
                evidence_block["count_note"] = (
                    "This block is truncated. loaded_sample_rows is only the number of rows "
                    "loaded into the UI sample, not the total matching record count."
                )
            evidence_blocks.append(
                evidence_block
            )
        elif kind == "chart" and block.get("sql_query"):
            chart = (
                block.get("chart_config")
                if isinstance(block.get("chart_config"), dict)
                else {}
            )
            chart_data = (
                chart.get("data") if isinstance(chart.get("data"), dict) else {}
            )
            truncated = bool(block.get("truncated"))
            evidence_blocks.append(
                {
                    "index": idx,
                    "kind": "chart",
                    "title": block.get("title") or "",
                    "sql_query": block.get("sql_query"),
                    "row_count": None if truncated else block.get("row_count"),
                    "total_count": block.get("total_count"),
                    "truncated": truncated,
                    "loaded_sample_rows": block.get("row_count"),
                    "chart_type": chart.get("type"),
                    "x_label": chart.get("x_label"),
                    "y_label": chart.get("y_label"),
                    "labels": chart_data.get("labels", [])[:50],
                    "datasets": chart_data.get("datasets", [])[:5],
                }
            )
    non_empty_blocks = [
        block
        for block in evidence_blocks
        if int(block.get("row_count") or block.get("loaded_sample_rows") or 0) > 0
    ]
    if non_empty_blocks:
        return {
            "blocks": non_empty_blocks,
            "ignored_empty_blocks": [
                {
                    "index": block.get("index"),
                    "kind": block.get("kind"),
                    "title": block.get("title"),
                    "sql_query": block.get("sql_query"),
                    "row_count": block.get("row_count"),
                    "loaded_sample_rows": block.get("loaded_sample_rows"),
                }
                for block in evidence_blocks
                if int(block.get("row_count") or block.get("loaded_sample_rows") or 0) == 0
            ],
        }
    return {"blocks": evidence_blocks}


def has_executed_evidence(result: dict) -> bool:
    evidence = _evidence_from_result(result)
    return bool(evidence.get("blocks"))


def write_verified_report(llm, user_query: str, result: dict, ctx=None) -> str:
    """
    Final answer writer. It receives only backend-executed SQL evidence and
    returns Markdown. It must not rely on draft agent prose.
    """
    evidence = _evidence_from_result(result)
    if not evidence.get("blocks"):
        return str(result.get("report") or "").strip()

    _ctx = ctx.to_dict() if ctx else {}
    system_prompt = (
        "You are a senior data analyst writing the final user-facing answer.\n"
        "Your goal is to provide a professional, insightful summary of the data.\n"
        "Use only the provided executed SQL evidence. Do not invent counts, fields, "
        "trends, labels, or explanations not supported by evidence.\n"
        "Write natural Markdown that fits the user's question. Do not use a fixed template, "
        "do not add generic headings, and do not call the output a report.\n"
        "When multiple evidence blocks are present, write deeper analysis: compare peaks "
        "and lows, totals, averages, period-over-period movement, concentration, and "
        "notable gaps when those facts are visible in the evidence.\n"
        "Keep the answer brief and explanatory. It will be shown with chart/table blocks, "
        "so describe what the displayed data says without introducing the answer.\n"
        "If the evidence is a single COUNT row, provide a clear, professional statement of the total and its significance.\n"
        "If the user asks for a longer window but the evidence contains fewer populated periods, "
        "state both the requested window and the observed populated period count clearly.\n"
        "If `truncated` is true and `total_count` is null, the total matching record count is unknown. "
        "Never present `loaded_sample_rows` as the total dataset size; say only that the UI shows a capped sample.\n"
        "When some candidate SQL blocks are empty but others return rows, ignore the empty candidates in the findings. "
        "Do not conclude that data is unavailable if any executed evidence block has rows.\n"
        "Maintain a professional and helpful tone. Do not include raw SQL in the text."
    )
    user_payload = {
        "question": user_query,
        "executed_evidence": evidence,
    }
    try:
        structured_llm = llm.with_structured_output(VerifiedReportResponse)
        response = structured_llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, default=str),
                },
            ]
        )
        if hasattr(response, "report"):
            report = str(response.report or "").strip()
        elif isinstance(response, dict):
            report = str(response.get("report") or "").strip()
        else:
            report = ""
        logger.info(
            "Verified report written",
            extra={
                "data": {
                    **_ctx,
                    "evidence_blocks": len(evidence.get("blocks") or []),
                    "report_length": len(report),
                }
            },
        )
        return report or str(result.get("report") or "").strip()
    except Exception as exc:
        logger.warning(
            "Verified report generation failed",
            exc_info=True,
            extra={"data": {**_ctx, "error": str(exc)[:300]}},
        )
        return str(result.get("report") or "").strip()


def apply_verified_report(result: dict, report: str) -> dict:
    """Keep model-requested evidence blocks and place verified narrative around them."""
    clean_report = (report or "").strip()
    if not clean_report:
        return result

    existing_blocks = [
        block
        for block in result.get("result_blocks") or []
        if isinstance(block, dict)
    ]
    table_blocks = [block for block in existing_blocks if block.get("kind") == "table"]
    chart_blocks = [block for block in existing_blocks if block.get("kind") == "chart"]
    data_blocks = [*table_blocks, *chart_blocks]
    text_blocks = [
        block
        for block in existing_blocks
        if block.get("kind") in {"text", "summary"} and str(block.get("text") or "").strip()
    ]

    result["report"] = clean_report
    if data_blocks:
        overview = text_blocks[:1] or [{"kind": "summary", "title": "Summary", "text": clean_report}]
        extra_text = text_blocks[1:]
        result["result_blocks"] = [
            *overview,
            *table_blocks,
            *extra_text,
            *chart_blocks,
            {"kind": "summary", "title": "Interpretation", "text": clean_report},
        ]
    else:
        result["result_blocks"] = [{"kind": "summary", "text": clean_report}]
    return result


# ── Auto Chart Generation ──────────────────────────────────────────────
