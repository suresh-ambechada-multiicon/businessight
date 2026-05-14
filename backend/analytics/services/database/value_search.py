from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from analytics.constants import INTERNAL_TABLE_PREFIXES
from analytics.services.logger import get_logger

logger = get_logger("db.value_search")

TEXT_TYPE_MARKERS = (
    "char",
    "text",
    "string",
    "varchar",
    "nvarchar",
    "uniqueidentifier",
    "uuid",
)
GENERIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "give",
    "how",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def extract_entity_terms(query: str) -> list[str]:
    raw = (query or "").strip()
    if not raw:
        return []
    terms = [*_quoted_terms(raw), *_word_terms(raw)]
    cleaned: list[str] = []
    for term in terms:
        value = term.strip().strip("`.,:;()[]{}")
        if not _is_candidate_term(value):
            continue
        if value not in cleaned:
            cleaned.append(value)
    return cleaned[:4]


def _quoted_terms(text_value: str) -> list[str]:
    terms: list[str] = []
    quote = ""
    start = -1
    for idx, char in enumerate(text_value):
        if char not in {'"', "'"}:
            continue
        if not quote:
            quote = char
            start = idx + 1
        elif quote == char:
            value = text_value[start:idx].strip()
            if value:
                terms.append(value)
            quote = ""
            start = -1
    return terms


def _word_terms(text_value: str) -> list[str]:
    terms: list[str] = []
    current: list[str] = []
    for char in text_value:
        if char.isalnum() or char in {"_", "-"}:
            current.append(char)
            continue
        if current:
            terms.append("".join(current))
            current = []
    if current:
        terms.append("".join(current))
    return terms


def _is_candidate_term(value: str) -> bool:
    if len(value) < 3:
        return False
    lower = value.lower()
    if lower in GENERIC_STOPWORDS:
        return False
    has_identifier_shape = "_" in value or "-" in value or any(ch.isdigit() for ch in value)
    has_mixed_case = any(ch.isupper() for ch in value[1:])
    return has_identifier_shape or has_mixed_case or len(value) >= 5


def search_database_values(
    db,
    *,
    user_query: str,
    table_names: list[str],
    ctx=None,
    max_tables: int = 80,
    max_matches: int = 12,
) -> dict[str, Any]:
    terms = extract_entity_terms(user_query)
    if not terms:
        return {"terms": [], "matches": []}

    try:
        inspector = sa_inspect(db._engine)
        schema = getattr(db, "_schema", None)
    except Exception as exc:
        logger.warning(
            "Value search inspector failed",
            extra={"data": {**(ctx.to_dict() if ctx else {}), "error": str(exc)[:200]}},
        )
        return {"terms": terms, "matches": []}

    matches: list[dict[str, Any]] = []
    scanned_tables = 0
    for table_name in table_names[:max_tables]:
        if table_name.startswith(INTERNAL_TABLE_PREFIXES):
            continue
        try:
            columns = inspector.get_columns(table_name, schema=schema)
        except Exception:
            continue
        candidate_cols = [
            str(col.get("name") or "")
            for col in columns
            if _is_searchable_column(col)
        ][:12]
        if not candidate_cols:
            continue
        scanned_tables += 1
        for column_name in candidate_cols:
            for term in terms:
                found = _search_column(db, table_name, column_name, term)
                for row in found:
                    matches.append(row)
                    if len(matches) >= max_matches:
                        return {
                            "terms": terms,
                            "scanned_tables": scanned_tables,
                            "matches": matches,
                        }
    return {"terms": terms, "scanned_tables": scanned_tables, "matches": matches}


def _is_searchable_column(col: dict) -> bool:
    name = str(col.get("name") or "")
    type_name = str(col.get("type") or "").lower()
    if not name:
        return False
    return any(marker in type_name for marker in TEXT_TYPE_MARKERS)


def _search_column(db, table_name: str, column_name: str, term: str) -> list[dict[str, Any]]:
    dialect = db._engine.url.drivername
    table_ref = _qualified_table(db, table_name)
    col_ref = _quote_ident(db, column_name)
    if "mssql" in dialect:
        sql = f"SELECT TOP 5 {col_ref} AS matched_value FROM {table_ref} WHERE LOWER(CAST({col_ref} AS NVARCHAR(MAX))) LIKE :term"
    elif "mysql" in dialect:
        sql = f"SELECT {col_ref} AS matched_value FROM {table_ref} WHERE LOWER(CAST({col_ref} AS CHAR)) LIKE :term LIMIT 5"
    else:
        sql = f"SELECT {col_ref} AS matched_value FROM {table_ref} WHERE LOWER(CAST({col_ref} AS TEXT)) LIKE :term LIMIT 5"
    try:
        with db._engine.connect() as conn:
            rows = conn.execute(text(sql), {"term": f"%{term.lower()}%"}).fetchall()
        return [
            {
                "search_term": term,
                "table": table_name,
                "column": column_name,
                "matched_value": row[0],
            }
            for row in rows
            if row and row[0] is not None
        ]
    except Exception:
        return []


def _quote_ident(db, name: str) -> str:
    clean = str(name).strip().strip('"').strip("[]").strip("`")
    if hasattr(db, "_engine") and "mssql" in db._engine.url.drivername:
        return f"[{clean.replace(']', ']]')}]"
    return f'"{clean.replace(chr(34), chr(34) + chr(34))}"'


def _qualified_table(db, table_name: str) -> str:
    table = _quote_ident(db, table_name)
    schema = getattr(db, "_schema", None)
    return f"{_quote_ident(db, schema)}.{table}" if schema else table
