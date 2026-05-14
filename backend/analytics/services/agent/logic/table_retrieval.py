"""
Query-aware table ranking for large catalogs.

This module now uses keyword/token overlap only. Embeddings are intentionally
removed so ranking stays fast, deterministic, and provider-agnostic.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from analytics.services.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("agent")


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", text.lower()) if len(t) >= 2]


def _keyword_scores(usable_tables: list[str], query: str) -> dict[str, float]:
    qtok = set(_tokenize(query))

    # Boost tables that commonly contain user/agent data
    user_keywords = {
        "user",
        "agent",
        "customer",
        "member",
        "client",
        "master",
        "profile",
    }
    query_lower = query.lower()
    has_user_context = any(k in query_lower for k in user_keywords)

    scores: dict[str, float] = {}
    for t in usable_tables:
        ttoks = set(_tokenize(t.replace("_", " ")))
        overlap = len(qtok & ttoks)
        sub = sum(1 for q in qtok if q in t.lower())
        base_score = (
            overlap * 3.0
            + sub * 1.5
            + (0.5 if any(c for c in qtok if c in t.lower()) else 0)
        )

        # Boost tables with user-related keywords when query mentions user context
        if has_user_context:
            t_lower = t.lower()
            if any(k in t_lower for k in user_keywords):
                base_score += 2.0

        scores[t] = base_score
    return scores


def rank_tables_for_query(
    usable_tables: list[str],
    user_query: str,
    db_uri_hash: str,
) -> list[str]:
    """
    Return ``usable_tables`` sorted by descending relevance to ``user_query``.
    """
    if not usable_tables:
        return []

    kw = _keyword_scores(usable_tables, user_query)

    # Keyword-only ranking. No embedding calls.
    combined: dict[str, float] = {}
    for t in usable_tables:
        combined[t] = kw.get(t, 0.0)

    ordered = sorted(usable_tables, key=lambda x: combined.get(x, 0.0), reverse=True)
    logger.info(
        "Tables ranked for query",
        extra={
            "data": {
                "db_uri_hash": db_uri_hash,
                "total": len(usable_tables),
                "top_5": ordered[:5],
                "semantic_used": False,
            }
        },
    )
    return ordered
