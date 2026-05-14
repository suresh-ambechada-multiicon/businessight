"""
Hydrate agent `result_blocks` by executing `sql_query` server-side.

The LLM must not embed row payloads or chart datasets — only SQL text plus
optional chart metadata (type, labels). Rows and chart `data` are filled here.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from analytics.services.database.security import validate_sql
from analytics.services.logger import get_logger
from analytics.services.sql_utils import extract_first_sql_from_combined, normalize_sql_key

logger = get_logger("pipeline.hydration")

_ID_COLUMN_EXCLUDE_RE = re.compile(r"(^id$|session_id|task_id|request_id|uuid|guid)", re.IGNORECASE)
_DISPLAY_COLUMN_EXCLUDE_RE = re.compile(
    r"(^id$|_id$|password|token|secret|email|phone|mobile|address|url|image|photo|json|xml|html|description|comment|note)",
    re.IGNORECASE,
)


def _auto_chart(partial_cfg: dict | None, rows: list, title_sql: str):
    """Lazy import avoids loading chart helpers unless needed."""
    from analytics.services.agent.logic.charts import auto_generate_chart

    return auto_generate_chart(partial_cfg, rows, query=title_sql)


def _row_dicts_from_result(result, max_rows: int) -> tuple[list[dict], bool]:
    """Fetch up to max_rows rows as dicts; returns (rows, truncated)."""
    rows = result.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]
    columns = result.keys()
    return [dict(zip(columns, row)) for row in rows], truncated


def run_readonly_select(
    db, query: str, ctx, max_rows: int
) -> tuple[list[dict] | None, str | None, bool]:
    """
    Execute a single read-only SELECT. Returns (rows, error_message, truncated).
    """
    stripped = (query or "").strip()
    if not stripped:
        return None, "Empty SQL query.", False

    is_safe, reason = validate_sql(stripped, ctx)
    if not is_safe:
        return None, reason, False

    try:
        with db._engine.connect() as conn:
            try:
                if "postgres" in db._engine.url.drivername:
                    conn.execute(text("SET statement_timeout = 45000"))
                elif "mysql" in db._engine.url.drivername:
                    conn.execute(text("SET max_execution_time = 45000"))
            except Exception:
                pass

            result = conn.execution_options(stream_results=True).execute(text(stripped))
            data, truncated = _row_dicts_from_result(result, max_rows)
            return _serialize_rows(data), None, truncated
    except Exception as e:
        logger.warning(
            "Hydration SQL failed",
            extra={"data": {**(ctx.to_dict() if ctx else {}), "error": str(e)[:300]}},
        )
        return None, f"Error executing query: {str(e)}", False


def _serialize_rows(rows: list[dict]) -> list[dict]:
    """JSON-safe row dicts (dates, decimals, UUIDs, bytes)."""

    def _one(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date, time)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (bytes, memoryview)):
            return "(binary data)"
        if isinstance(obj, dict):
            return {str(k): _one(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_one(i) for i in obj]
        return str(obj)

    out = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append({k: _one(v) for k, v in row.items()})
    return out


def _strip_chart_data(chart_cfg: dict | None) -> dict | None:
    if not chart_cfg or not isinstance(chart_cfg, dict):
        return None
    out = {k: v for k, v in chart_cfg.items() if k != "data"}
    return out if out else None


def _rows_from_cache_or_run(
    sql: str,
    db,
    ctx,
    max_rows: int,
    query_cache: dict,
) -> tuple[list[dict] | None, str | None, bool]:
    key = normalize_sql_key(sql)
    if key and isinstance(query_cache, dict) and key in query_cache:
        cached = query_cache[key]
        if isinstance(cached, list):
            return cached, None, False
    return run_readonly_select(db, sql, ctx, max_rows)


def _table_meta(rows: list[dict], truncated: bool = False) -> dict:
    row_count = len(rows or [])
    meta = {
        "row_count": row_count,
        "truncated": bool(truncated),
    }
    if not truncated:
        meta["total_count"] = row_count
    return meta


def _normalize_numeric_nulls(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    columns_with_numeric_values: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                columns_with_numeric_values.add(str(key))

    if not columns_with_numeric_values:
        return rows

    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            normalized.append(row)
            continue
        out = dict(row)
        for key, value in out.items():
            key_str = str(key)
            if value is None and key_str in columns_with_numeric_values:
                out[key] = 0
        normalized.append(out)
    return normalized


def _quote_ident_for_db(db, name: str) -> str:
    clean = str(name).strip().strip('"').strip("[]").strip("`")
    if hasattr(db, "_engine") and "mssql" in db._engine.url.drivername:
        return f"[{clean.replace(']', ']]')}]"
    return f'"{clean.replace(chr(34), chr(34) + chr(34))}"'


def _qualified_table_for_db(db, table_name: str) -> str:
    table = _quote_ident_for_db(db, table_name)
    schema = getattr(db, "_schema", None)
    return f"{_quote_ident_for_db(db, schema)}.{table}" if schema else table


def _is_lookup_id_column(column_name: str) -> bool:
    name = str(column_name or "")
    return name.lower().endswith("_id") and not _ID_COLUMN_EXCLUDE_RE.search(name)


def _candidate_lookup_tables(base: str, table_names: list[str]) -> list[str]:
    base_l = base.lower()
    wanted = [
        base_l,
        f"{base_l}_master",
        f"{base_l}_masters",
        f"{base_l}_details",
        f"{base_l}_detail",
        f"{base_l}s",
    ]
    scored: list[tuple[int, str]] = []
    for table in table_names:
        t = table.lower()
        score = 0
        if t in wanted:
            score = 100 - wanted.index(t)
        elif t.endswith(f"_{base_l}_master") or t.endswith(f"_{base_l}"):
            score = 80
        elif base_l in t and ("master" in t or "lookup" in t or "ref" in t):
            score = 60
        elif base_l in t:
            score = 30
        if score:
            scored.append((score, table))
    return [table for _, table in sorted(scored, reverse=True)[:6]]


def _pick_lookup_columns(base: str, columns: list[dict]) -> tuple[str, str] | None:
    names = [str(c.get("name") or "") for c in columns]
    names_l = {n.lower(): n for n in names}
    id_candidates = [
        f"{base}_id",
        "id",
        f"{base}id",
        "code",
        "short_code",
    ]
    display_candidates = [
        f"{base}_name",
        "name",
        "title",
        "display_name",
        "full_name",
        "label",
        "short_name",
        "code",
        "short_code",
    ]

    id_col = next((names_l[c] for c in id_candidates if c in names_l), None)
    if not id_col:
        return None

    display_col = next(
        (
            names_l[c]
            for c in display_candidates
            if c in names_l and names_l[c] != id_col and not _DISPLAY_COLUMN_EXCLUDE_RE.search(names_l[c])
        ),
        None,
    )
    if not display_col:
        for name in names:
            if name != id_col and not _DISPLAY_COLUMN_EXCLUDE_RE.search(name):
                display_col = name
                break
    if not display_col:
        return None
    return id_col, display_col


def _lookup_values_for_id_column(
    db,
    *,
    id_column: str,
    values: list,
) -> tuple[str, dict] | None:
    base = id_column[:-3]
    try:
        inspector = sa_inspect(db._engine)
        schema = getattr(db, "_schema", None)
        table_names = inspector.get_table_names(schema=schema)
    except Exception:
        return None

    for table_name in _candidate_lookup_tables(base, table_names):
        try:
            columns = inspector.get_columns(table_name, schema=getattr(db, "_schema", None))
        except Exception:
            continue
        picked = _pick_lookup_columns(base, columns)
        if not picked:
            continue
        lookup_id_col, display_col = picked
        params = {f"v{i}": value for i, value in enumerate(values[:200])}
        if not params:
            return None
        placeholders = ", ".join(f":{key}" for key in params)
        sql = (
            f"SELECT {_quote_ident_for_db(db, lookup_id_col)} AS lookup_id, "
            f"{_quote_ident_for_db(db, display_col)} AS display_value "
            f"FROM {_qualified_table_for_db(db, table_name)} "
            f"WHERE {_quote_ident_for_db(db, lookup_id_col)} IN ({placeholders})"
        )
        try:
            mapping = {}
            with db._engine.connect() as conn:
                for row in conn.execute(text(sql), params):
                    key = row[0]
                    value = row[1]
                    if key is not None and value is not None:
                        mapping[str(key)] = value
            if mapping:
                out_col = (
                    f"{base}_{display_col}"
                    if display_col.lower() in {"name", "title", "code", "short_code", "label"}
                    else display_col
                )
                return out_col, mapping
        except Exception:
            continue
    return None


def _enrich_id_columns_with_names(rows: list[dict], db) -> list[dict]:
    if not rows:
        return rows
    first = rows[0] if isinstance(rows[0], dict) else {}
    if not isinstance(first, dict):
        return rows

    existing_cols_l = {str(k).lower() for k in first.keys()}
    id_columns = [
        str(col)
        for col in first.keys()
        if _is_lookup_id_column(str(col))
        and f"{str(col)[:-3]}_name".lower() not in existing_cols_l
        and str(col)[:-3].lower() not in existing_cols_l
    ][:4]
    if not id_columns:
        return rows

    enrichments: dict[str, tuple[str, dict]] = {}
    for col in id_columns:
        values = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get(col)
            if value is None or str(value) in seen:
                continue
            seen.add(str(value))
            values.append(value)
            if len(values) >= 200:
                break
        lookup = _lookup_values_for_id_column(db, id_column=col, values=values)
        if lookup:
            out_col, mapping = lookup
            if out_col.lower() in existing_cols_l:
                out_col = f"{col[:-3]}_{out_col}"
            enrichments[col] = (out_col, mapping)

    if not enrichments:
        return rows

    enriched = []
    for row in rows:
        if not isinstance(row, dict):
            enriched.append(row)
            continue
        out = {}
        for key, value in row.items():
            out[key] = value
            enrichment = enrichments.get(str(key))
            if enrichment:
                out_col, mapping = enrichment
                out[out_col] = mapping.get(str(value))
        enriched.append(out)
    return enriched


def hydrate_analytics_result(
    result: dict,
    db,
    ctx,
    max_rows: int,
    tool_state: dict | None = None,
    user_query: str = "",
) -> dict:
    """
    Execute SQL on table/chart blocks; fill `raw_data` / chart `data` from DB only.

    Mutates and returns `result` with hydrated `result_blocks`, plus top-level
    `report`, `sql_query`, `raw_data`, `chart_config` derived for compatibility.
    """
    tool_state = tool_state or {}
    query_cache = tool_state.get("query_cache") if isinstance(tool_state, dict) else {}
    if not isinstance(query_cache, dict):
        query_cache = {}

    preserved_report = (result.get("report") or "").strip()
    blocks_in = list(result.get("result_blocks") or [])

    # Legacy: agent returned flat report + sql_query but no structured blocks
    if not blocks_in:
        sql_flat = extract_first_sql_from_combined(result.get("sql_query") or "")
        if preserved_report:
            blocks_in.append({"kind": "text", "text": preserved_report})
        if sql_flat:
            blocks_in.append({"kind": "table", "sql_query": sql_flat})

    if not blocks_in and preserved_report:
        blocks_in = [{"kind": "text", "text": preserved_report}]

    out_blocks: list[dict] = []

    for block in blocks_in:
        if not isinstance(block, dict):
            continue
        kind = str(block.get("kind") or "text").lower()
        if kind not in {"text", "summary", "table", "chart"}:
            kind = "text"

        if kind in {"text", "summary"}:
            item = {
                "kind": "summary" if kind == "summary" else "text",
                "title": block.get("title"),
                "text": block.get("text") or block.get("report") or "",
            }
            item = {k: v for k, v in item.items() if v is not None and v != ""}
            if item.get("text"):
                out_blocks.append(item)
            continue

        sql_q = str(block.get("sql_query") or "").strip()
        title = block.get("title")

        if kind == "table":
            if not sql_q:
                msg = "*Table block is missing `sql_query` — nothing to fetch.*"
                out_blocks.append(
                    {
                        "kind": "text",
                        "title": title,
                        "text": msg,
                    }
                )
                continue
            rows, err, truncated = _rows_from_cache_or_run(sql_q, db, ctx, max_rows, query_cache)
            if err:
                out_blocks.append(
                    {
                        "kind": "text",
                        "title": title,
                        "text": f"**Could not load table data.** {err}",
                    }
                )
                continue
            row_out = _enrich_id_columns_with_names(_normalize_numeric_nulls(rows or []), db)
            item = {
                "kind": "table",
                "sql_query": sql_q,
                "raw_data": row_out,
                **_table_meta(row_out, truncated),
            }
            if title:
                item["title"] = title
            out_blocks.append(item)
            continue

        if kind == "chart":
            if not sql_q:
                out_blocks.append(
                    {
                        "kind": "text",
                        "title": title,
                        "text": "*Chart block is missing `sql_query` — cannot plot.*",
                    }
                )
                continue
            rows, err, truncated = _rows_from_cache_or_run(sql_q, db, ctx, max_rows, query_cache)
            if err:
                out_blocks.append(
                    {
                        "kind": "text",
                        "title": title,
                        "text": f"**Could not load chart data.** {err}",
                    }
                )
                continue
            row_out = _enrich_id_columns_with_names(_normalize_numeric_nulls(rows or []), db)
            partial = _strip_chart_data(block.get("chart_config"))
            filled = _auto_chart(
                partial,
                row_out,
                f"{title or ''} {sql_q}".strip(),
            )
            item = {
                "kind": "chart",
                "sql_query": sql_q,
                **_table_meta(row_out, truncated),
            }
            if title:
                item["title"] = title
            if isinstance(filled, dict) and filled.get("data"):
                item["chart_config"] = filled
            elif isinstance(filled, list) and filled:
                item["chart_config"] = filled[0]
            else:
                continue
            out_blocks.append(item)

    result["result_blocks"] = out_blocks

    # Top-level compatibility — narrative from text blocks, or preserve agent prose
    text_parts = [
        str(b.get("text") or "").strip()
        for b in out_blocks
        if isinstance(b, dict)
        and b.get("kind") in {"text", "summary"}
        and str(b.get("text") or "").strip()
    ]
    if text_parts:
        result["report"] = "\n\n".join(text_parts)
    elif preserved_report:
        result["report"] = preserved_report

    first_sql = ""
    first_rows: list | None = None
    first_chart = None
    for b in out_blocks:
        if not isinstance(b, dict):
            continue
        if b.get("kind") == "table" and b.get("sql_query"):
            if not first_sql:
                first_sql = str(b["sql_query"])
            if first_rows is None and isinstance(b.get("raw_data"), list):
                first_rows = b["raw_data"]
        if b.get("kind") == "chart" and b.get("chart_config"):
            if first_chart is None:
                first_chart = b.get("chart_config")

    if first_sql:
        result["sql_query"] = first_sql
    if first_rows is not None:
        result["raw_data"] = first_rows
    else:
        result["raw_data"] = []
    result["chart_config"] = first_chart

    generic_fallback = "The AI did not produce a readable summary"
    has_text_block = any(
        isinstance(b, dict)
        and b.get("kind") in {"text", "summary"}
        and str(b.get("text") or "").strip()
        for b in out_blocks
    )
    report_text = str(result.get("report") or "").strip()

    # Only inject a generic summary when the report is truly absent or is the
    # exact hardcoded fallback.  Never overwrite a real analytical report that
    # the verified-report pass or the agent already produced.
    report_is_missing = not report_text or report_text == generic_fallback
    if first_rows is not None and report_is_missing and not has_text_block:
        first_total_count = None
        first_truncated = False
        for b in out_blocks:
            if isinstance(b, dict) and b.get("kind") == "table" and isinstance(b.get("raw_data"), list):
                first_total_count = b.get("total_count")
                first_truncated = bool(b.get("truncated"))
                break

        loaded_count = len(first_rows)
        total_count = first_total_count if isinstance(first_total_count, int) else None
        if loaded_count == 0:
            summary = "No matching rows were found."
        else:
            cols = list(first_rows[0].keys()) if isinstance(first_rows[0], dict) else []
            field_text = f" Fields: {', '.join(cols[:8])}." if cols else ""
            if len(cols) > 8:
                field_text = f" Fields: {', '.join(cols[:8])} and {len(cols) - 8} more."
            query_hint = f" for `{user_query.strip()}`" if user_query.strip() else ""
            if first_truncated:
                summary = (
                    f"Showing the first {loaded_count} matching rows{query_hint}. "
                    f"The full count was not computed to keep the query fast.{field_text}"
                )
            else:
                total_count = total_count if total_count is not None else loaded_count
                summary = f"Found {total_count} matching rows{query_hint}.{field_text}"

        summary_block = {"kind": "summary", "text": summary}
        result["result_blocks"] = [summary_block, *out_blocks]
        result["report"] = summary

    return result
