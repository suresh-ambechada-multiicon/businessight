"""Evidence extraction and verified answer placement."""

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


def apply_verified_answer(result: dict, answer: dict) -> dict:
    """Place overview first, then each table/chart followed by its own insight."""
    overview = str(answer.get("overview") or "").strip()
    if not overview and not answer.get("block_insights"):
        return result

    existing_blocks = [
        block for block in result.get("result_blocks") or [] if isinstance(block, dict)
    ]
    insights = {
        int(item.get("index")): item
        for item in answer.get("block_insights") or []
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    }

    out_blocks: list[dict] = []
    if overview:
        out_blocks.append({"kind": "summary", "title": "Analysis", "text": overview})

    idx = 0
    while idx < len(existing_blocks):
        block = existing_blocks[idx]
        kind = block.get("kind")

        if kind in {"table", "chart"}:
            out_blocks.append(block)
            insight = insights.get(idx)
            if insight:
                out_blocks.append(
                    {
                        "kind": "summary",
                        "title": insight.get("title") or "Insight",
                        "text": str(insight.get("text") or "").strip(),
                    }
                )
            elif idx + 1 < len(existing_blocks) and existing_blocks[idx + 1].get("kind") in {"text", "summary"}:
                out_blocks.append(existing_blocks[idx + 1])
                idx += 1
        elif not overview and kind in {"text", "summary"}:
            out_blocks.append(block)
        idx += 1

    if not out_blocks and overview:
        out_blocks = [{"kind": "summary", "title": "Analysis", "text": overview}]

    result["report"] = overview or str(result.get("report") or "")
    result["result_blocks"] = out_blocks or existing_blocks
    return result


# ── Auto Chart Generation ──────────────────────────────────────────────
