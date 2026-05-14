"""Schema context construction for the analytics agent."""

import re

from analytics.services.logger import get_logger

logger = get_logger("agent")


_VALUE_HINT_NAME_RE = re.compile(
    r"(^name$|_name$|^code$|_code$|short_code|status|state|type|kind|class|category|group|segment|source|channel|mode|label|title|remark|service)",
    re.IGNORECASE,
)
_VALUE_HINT_EXCLUDE_RE = re.compile(
    r"(email|phone|mobile|password|token|secret|address|url|image|photo|comment|description|note|json|xml|html)",
    re.IGNORECASE,
)


def _quote_ident(name: str, dialect: str) -> str:
    if "mssql" in dialect:
        return f"[{name.replace(']', ']]')}]"
    return f'"{name.replace(chr(34), chr(34) + chr(34))}"'


def _qualified_table(schema: str | None, table_name: str, dialect: str) -> str:
    table = _quote_ident(table_name, dialect)
    return f"{_quote_ident(schema, dialect)}.{table}" if schema else table


def _parse_columns_from_info(col_info: str) -> list[tuple[str, str]]:
    _, _, tail = (col_info or "").partition(" columns: ")
    cols: list[tuple[str, str]] = []
    for part in tail.split(", "):
        name, _, type_name = part.partition(" ")
        name = name.strip()
        if name:
            cols.append((name, type_name.strip()))
    return cols


def _should_sample_values(column_name: str, type_name: str) -> bool:
    name = str(column_name or "")
    type_l = str(type_name or "").lower()
    if _VALUE_HINT_EXCLUDE_RE.search(name):
        return False
    if not _VALUE_HINT_NAME_RE.search(name):
        return False
    return any(t in type_l for t in ("char", "text", "string", "uuid", "uniqueidentifier")) or "int" in type_l


def build_schema_context(
    usable_tables: list[str],
    active_schema,
    db,
    ctx=None,
    *,
    table_rank_order: list[str] | None = None,
    skip_full_context_cache: bool = False,
) -> str:
    """
    Build the schema context string that gets injected into the system prompt.

    Always include full column details for every usable table. This can be
    expensive on large databases, but it gives the report agent complete schema
    visibility and avoids guessing from a partial table list.
    """
    from analytics.services.cache import (
        get_cached_schema_context,
        set_cached_schema_context,
        get_cached_column_info,
        set_cached_column_info,
    )

    db_uri_hash = ctx.db_uri_hash if ctx else ""
    schema_name = active_schema or getattr(db, "_schema", None) or "__default__"
    schema_cache_key = f"{db_uri_hash}:{schema_name}"

    has_query_specific_order = bool(table_rank_order)
    use_full_context_cache = not skip_full_context_cache and not has_query_specific_order

    # 1. Try full context cache first (fastest path). Query-ranked context is
    # intentionally rebuilt so value hints are focused on the current question.
    if db_uri_hash and use_full_context_cache:
        cached = get_cached_schema_context(schema_cache_key)
        if cached is not None:
            logger.info(
                "Schema context from cache",
                extra={
                    "data": {
                        **(ctx.to_dict() if ctx else {}),
                        "table_count": len(usable_tables),
                        "source": "redis_cache",
                    }
                },
            )
            return cached

    # 2. Build context
    def _get_table_columns(table_name: str) -> str:
        """Get column info for a single table, with per-table caching."""
        # Check per-table cache
        if db_uri_hash:
            cached_cols = get_cached_column_info(schema_cache_key, table_name)
            if cached_cols is not None:
                return cached_cols

        # Try fast MSSQL path
        col_str = ""
        try:
            if hasattr(db, "_engine") and "mssql" in db._engine.url.drivername:
                from sqlalchemy import text

                with db._engine.connect() as conn:
                    full_name = (
                        f"{active_schema}.{table_name}" if active_schema else table_name
                    )
                    result = conn.execute(
                        text(
                            f"SELECT c.name, t.name as type_name "
                            f"FROM sys.columns c "
                            f"JOIN sys.types t ON c.user_type_id = t.user_type_id "
                            f"WHERE c.object_id = OBJECT_ID('{full_name}')"
                        )
                    )
                    cols = [f"{row[0]} {row[1]}" for row in result]
                    if cols:
                        col_str = f"Table '{table_name}' columns: {', '.join(cols)}"
        except Exception:
            pass

        # Fallback to SQLAlchemy inspector
        if not col_str:
            try:
                from sqlalchemy import inspect as sa_inspect

                db_inspector = sa_inspect(db._engine)
                columns = db_inspector.get_columns(table_name, schema=db._schema)
                cols_str = ", ".join([f"{c['name']} {str(c['type'])}" for c in columns])
                col_str = f"Table '{table_name}' columns: {cols_str}"
            except Exception:
                col_str = f"Table '{table_name}': (schema unavailable)"

        # Cache per-table result
        if db_uri_hash and col_str:
            set_cached_column_info(schema_cache_key, table_name, col_str)

        return col_str

    def _get_value_hints(table_name: str, columns: list[tuple[str, str]]) -> str:
        """Sample small categorical/code values so the model can match DB vocabulary."""
        if not hasattr(db, "_engine"):
            return ""
        dialect = db._engine.url.drivername
        candidates = [
            (name, type_name)
            for name, type_name in columns
            if _should_sample_values(name, type_name)
        ][:6]
        if not candidates:
            return ""

        hints: list[str] = []
        try:
            from sqlalchemy import text

            table_ref = _qualified_table(active_schema or getattr(db, "_schema", None), table_name, dialect)
            with db._engine.connect() as conn:
                for col_name, _type_name in candidates:
                    col_ref = _quote_ident(col_name, dialect)
                    if "mssql" in dialect:
                        sql = (
                            f"SELECT DISTINCT TOP 12 {col_ref} AS value "
                            f"FROM {table_ref} WHERE {col_ref} IS NOT NULL ORDER BY {col_ref}"
                        )
                    else:
                        sql = (
                            f"SELECT DISTINCT {col_ref} AS value "
                            f"FROM {table_ref} WHERE {col_ref} IS NOT NULL "
                            f"ORDER BY {col_ref} LIMIT 12"
                        )
                    try:
                        values = []
                        for row in conn.execute(text(sql)):
                            value = row[0]
                            if value is None:
                                continue
                            text_value = str(value).strip()
                            if text_value:
                                values.append(text_value[:80])
                        if values:
                            hints.append(f"{col_name}: {', '.join(values)}")
                    except Exception:
                        continue
        except Exception:
            return ""

        if not hints:
            return ""
        return f"Table '{table_name}' value hints: " + " | ".join(hints)

    schema_context = ""
    if active_schema:
        schema_context += (
            f"Active Schema: {active_schema}\n"
            f"Use schema `{active_schema}` for table references when qualifying names. "
            "Do not use `public` unless it is explicitly listed as the active schema.\n\n"
        )

    ordered_tables = usable_tables
    if table_rank_order:
        ranked = [t for t in table_rank_order if t in usable_tables]
        remaining = [t for t in usable_tables if t not in set(ranked)]
        ordered_tables = [*ranked, *remaining]

    lines = [_get_table_columns(t) for t in ordered_tables]
    schema_context += "Detailed Schema:\n" + "\n".join(lines)

    hint_tables = ordered_tables[:8]
    value_hint_lines = []
    for table_name, col_info in zip(ordered_tables, lines):
        if table_name not in hint_tables:
            continue
        hint = _get_value_hints(table_name, _parse_columns_from_info(col_info))
        if hint:
            value_hint_lines.append(hint)
    if value_hint_lines:
        schema_context += (
            "\n\nValue Hints (sample distinct values for likely lookup/status/code/name columns; "
            "not exhaustive, use them to match exact database vocabulary):\n"
            + "\n".join(value_hint_lines)
        )

    # 3. Cache the full context (skip when query-specific ranking was applied)
    if db_uri_hash and use_full_context_cache:
        set_cached_schema_context(schema_cache_key, schema_context)

    _ctx = ctx.to_dict() if ctx else {}
    mode = "full_detailed"
    logger.info(
        "Schema context built",
        extra={
            "data": {
                **_ctx,
                "table_count": len(usable_tables),
                "mode": mode,
                "context_length": len(schema_context),
            }
        },
    )

    return schema_context


# ── LLM Initialization ─────────────────────────────────────────────────
