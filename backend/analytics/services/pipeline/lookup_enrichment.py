from __future__ import annotations

import re

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

ID_COLUMN_EXCLUDE_RE = re.compile(
    r"(^id$|session_id|task_id|request_id|uuid|guid)",
    re.IGNORECASE,
)
DISPLAY_COLUMN_EXCLUDE_RE = re.compile(
    r"(^id$|_id$|password|token|secret|email|phone|mobile|address|url|image|photo|json|xml|html|description|comment|note)",
    re.IGNORECASE,
)


def quote_ident_for_db(db, name: str) -> str:
    clean = str(name).strip().strip('"').strip("[]").strip("`")
    if hasattr(db, "_engine") and "mssql" in db._engine.url.drivername:
        return f"[{clean.replace(']', ']]')}]"
    return f'"{clean.replace(chr(34), chr(34) + chr(34))}"'


def qualified_table_for_db(db, table_name: str) -> str:
    table = quote_ident_for_db(db, table_name)
    schema = getattr(db, "_schema", None)
    return f"{quote_ident_for_db(db, schema)}.{table}" if schema else table


def is_lookup_id_column(column_name: str) -> bool:
    name = str(column_name or "")
    return name.lower().endswith("_id") and not ID_COLUMN_EXCLUDE_RE.search(name)


def candidate_lookup_tables(base: str, table_names: list[str]) -> list[str]:
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


def pick_lookup_columns(base: str, columns: list[dict]) -> tuple[str, str] | None:
    names = [str(c.get("name") or "") for c in columns]
    names_l = {n.lower(): n for n in names}
    id_candidates = [f"{base}_id", "id", f"{base}id", "code", "short_code"]
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
            if c in names_l
            and names_l[c] != id_col
            and not DISPLAY_COLUMN_EXCLUDE_RE.search(names_l[c])
        ),
        None,
    )
    if not display_col:
        display_col = next(
            (
                name
                for name in names
                if name != id_col and not DISPLAY_COLUMN_EXCLUDE_RE.search(name)
            ),
            None,
        )
    return (id_col, display_col) if display_col else None


def lookup_values_for_id_column(
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

    for table_name in candidate_lookup_tables(base, table_names):
        try:
            columns = inspector.get_columns(table_name, schema=getattr(db, "_schema", None))
        except Exception:
            continue
        picked = pick_lookup_columns(base, columns)
        if not picked:
            continue

        lookup_id_col, display_col = picked
        params = {f"v{i}": value for i, value in enumerate(values[:200])}
        if not params:
            return None

        placeholders = ", ".join(f":{key}" for key in params)
        sql = (
            f"SELECT {quote_ident_for_db(db, lookup_id_col)} AS lookup_id, "
            f"{quote_ident_for_db(db, display_col)} AS display_value "
            f"FROM {qualified_table_for_db(db, table_name)} "
            f"WHERE {quote_ident_for_db(db, lookup_id_col)} IN ({placeholders})"
        )
        try:
            mapping = {}
            with db._engine.connect() as conn:
                for row in conn.execute(text(sql), params):
                    key, value = row[0], row[1]
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


def enrich_id_columns_with_names(rows: list[dict], db) -> list[dict]:
    if not rows:
        return rows
    first = rows[0] if isinstance(rows[0], dict) else {}
    if not isinstance(first, dict):
        return rows

    existing_cols_l = {str(k).lower() for k in first.keys()}
    id_columns = [
        str(col)
        for col in first.keys()
        if is_lookup_id_column(str(col))
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
        lookup = lookup_values_for_id_column(db, id_column=col, values=values)
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
