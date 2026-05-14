"""Small SQL string helpers shared across tools and hydration."""

from __future__ import annotations

import re

import sqlparse


_QUERY_DUMP_PATTERN = re.compile(
    r"-- Query \d+(?: \([^)]+\))?\s*\n([\s\S]*?)(?=-- Query \d+|$)",
    re.IGNORECASE,
)


def normalize_sql_key(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def extract_sql_blocks_from_combined(sql_blob: str) -> list[str]:
    s = (sql_blob or "").strip()
    if not s:
        return []

    matches = list(_QUERY_DUMP_PATTERN.finditer(s))
    if matches:
        return [match.group(1).strip() for match in matches if match.group(1).strip()]

    statements = [statement.strip() for statement in sqlparse.split(s) if statement.strip()]
    return statements or [s]


def extract_first_sql_from_combined(sql_blob: str) -> str:
    """If `sql_query` is the multi-query debug dump, return the **last** SELECT body.

    The last query in the agent's execution trace is almost always the refined
    answer query, while the first is typically schema exploration.  Despite the
    legacy name, callers expect the "best" single query for hydration.
    """
    blocks = extract_sql_blocks_from_combined(sql_blob)
    return blocks[-1] if blocks else ""


def format_sql_blocks(sql_blocks: list[str]) -> str:
    blocks = [str(sql).strip() for sql in sql_blocks if str(sql).strip()]
    if not blocks:
        return ""
    if len(blocks) == 1:
        return blocks[0]
    return "\n\n".join(f"-- Query {idx}\n{sql}" for idx, sql in enumerate(blocks, 1))
