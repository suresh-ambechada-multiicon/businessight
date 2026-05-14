from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import uuid

from sqlalchemy import text

from analytics.services.database.security import validate_sql
from analytics.services.logger import get_logger
from analytics.services.sql_utils import normalize_sql_key

logger = get_logger("pipeline.sql")


def serialize_value(obj):
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
        return {str(k): serialize_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_value(i) for i in obj]
    return str(obj)


def serialize_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append({k: serialize_value(v) for k, v in row.items()})
    return out


def row_dicts_from_result(result, max_rows: int) -> tuple[list[dict], bool]:
    rows = result.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]
    columns = result.keys()
    return [dict(zip(columns, row)) for row in rows], truncated


def run_readonly_select(
    db,
    query: str,
    ctx,
    max_rows: int,
) -> tuple[list[dict] | None, str | None, bool]:
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
            data, truncated = row_dicts_from_result(result, max_rows)
            return serialize_rows(data), None, truncated
    except Exception as exc:
        logger.warning(
            "Hydration SQL failed",
            extra={
                "data": {
                    **(ctx.to_dict() if ctx else {}),
                    "error": str(exc)[:300],
                }
            },
        )
        return None, f"Error executing query: {str(exc)}", False


def rows_from_cache_or_run(
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


def normalize_numeric_nulls(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows

    numeric_cols: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_cols.add(str(key))

    if not numeric_cols:
        return rows

    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            normalized.append(row)
            continue
        out = dict(row)
        for key, value in out.items():
            if value is None and str(key) in numeric_cols:
                out[key] = 0
        normalized.append(out)
    return normalized
