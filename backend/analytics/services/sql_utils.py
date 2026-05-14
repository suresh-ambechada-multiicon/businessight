"""Small SQL string helpers shared across tools and hydration."""

from __future__ import annotations

import re


def normalize_sql_key(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def extract_first_sql_from_combined(sql_blob: str) -> str:
    """If `sql_query` is the multi-query debug dump, return the **last** SELECT body.

    The last query in the agent's execution trace is almost always the refined
    answer query, while the first is typically schema exploration.  Despite the
    legacy name, callers expect the "best" single query for hydration.
    """
    s = (sql_blob or "").strip()
    if not s:
        return ""
    matches = list(
        re.finditer(
            r"-- Query \d+(?: \([^)]+\))?\s*\n([\s\S]*?)(?=-- Query \d+|$)",
            s,
        )
    )
    if matches:
        return matches[-1].group(1).strip()
    return s
