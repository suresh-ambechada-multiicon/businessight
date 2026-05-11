"""
Query-aware table ranking for large catalogs (Genie-style specialized retrieval).

Combines:
- Keyword / token overlap on table names (always, no extra API cost)
- Optional dense embeddings (Google or OpenAI) when the main model uses a
  compatible provider and ``semantic_table_rank`` is enabled.

Vectors for the table corpus are cached in Redis keyed by DB hash + catalog
fingerprint so repeated sessions on the same database avoid re-embedding.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import TYPE_CHECKING

from django.core.cache import cache

from analytics.services.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("agent")

EMBED_CACHE_TTL = 3600
MAX_EMBED_TABLES = 120
BATCH = 32


def _catalog_fingerprint(tables: list[str]) -> str:
    return hashlib.md5(",".join(sorted(tables)).encode()).hexdigest()[:16]


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", text.lower()) if len(t) >= 2]


def _keyword_scores(usable_tables: list[str], query: str) -> dict[str, float]:
    qtok = set(_tokenize(query))
    scores: dict[str, float] = {}
    for t in usable_tables:
        ttoks = set(_tokenize(t.replace("_", " ")))
        overlap = len(qtok & ttoks)
        sub = sum(1 for q in qtok if q in t.lower())
        scores[t] = overlap * 3.0 + sub * 1.5 + (0.5 if any(c for c in qtok if c in t.lower()) else 0)
    return scores


def _embedding_backend(model: str) -> str | None:
    m = (model or "").lower()
    if "google_genai:" in model or "gemini" in m:
        return "google_genai"
    if "openai:" in model or m.startswith("gpt"):
        return "openai"
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _table_doc(table: str, column_hint: str) -> str:
    hint = (column_hint or "").replace("Table", "").strip()
    return f"{table.replace('_', ' ')} {table} {hint[:400]}"


def rank_tables_for_query(
    *,
    usable_tables: list[str],
    user_query: str,
    db,
    db_uri_hash: str,
    api_key: str,
    primary_model: str,
    semantic_table_rank: bool,
    column_hint_fn,
) -> list[str]:
    """
    Return ``usable_tables`` sorted by descending relevance to ``user_query``.
    """
    if not usable_tables:
        return []

    kw = _keyword_scores(usable_tables, user_query)
    backend = _embedding_backend(primary_model)
    sem: dict[str, float] = {}

    if semantic_table_rank and backend and len(usable_tables) > 8 and api_key:
        fp = _catalog_fingerprint(usable_tables)
        cache_key = f"tblrank:emb:v1:{db_uri_hash}:{fp}"
        corpus = cache.get(cache_key)

        subset = usable_tables[:MAX_EMBED_TABLES]
        try:
            if corpus is None:
                texts = [_table_doc(t, column_hint_fn(t)) for t in subset]
                vecs: list[list[float]] = []
                if backend == "google_genai":
                    from langchain_google_genai import GoogleGenerativeAIEmbeddings

                    emb = GoogleGenerativeAIEmbeddings(
                        model="models/text-embedding-004",
                        google_api_key=api_key,
                    )
                    for i in range(0, len(texts), BATCH):
                        vecs.extend(emb.embed_documents(texts[i : i + BATCH]))
                else:
                    from langchain_openai import OpenAIEmbeddings

                    emb = OpenAIEmbeddings(
                        model="text-embedding-3-small",
                        api_key=api_key,
                    )
                    for i in range(0, len(texts), BATCH):
                        vecs.extend(emb.embed_documents(texts[i : i + BATCH]))

                corpus = {"tables": subset, "vecs": vecs}
                cache.set(cache_key, corpus, timeout=EMBED_CACHE_TTL)
                logger.info(
                    "Table corpus embedded for retrieval",
                    extra={
                        "data": {
                            "db_uri_hash": db_uri_hash,
                            "tables_embedded": len(subset),
                            "backend": backend,
                        }
                    },
                )

            if corpus and corpus.get("vecs"):
                tables_c = corpus["tables"]
                vecs_c = corpus["vecs"]
                if backend == "google_genai":
                    from langchain_google_genai import GoogleGenerativeAIEmbeddings

                    qemb = GoogleGenerativeAIEmbeddings(
                        model="models/text-embedding-004",
                        google_api_key=api_key,
                    ).embed_query(user_query)
                else:
                    from langchain_openai import OpenAIEmbeddings

                    qemb = OpenAIEmbeddings(
                        model="text-embedding-3-small",
                        api_key=api_key,
                    ).embed_query(user_query)

                for t, v in zip(tables_c, vecs_c):
                    sem[t] = _cosine(qemb, v)
        except Exception as e:
            logger.warning(
                "Semantic table rank skipped",
                extra={"data": {"db_uri_hash": db_uri_hash, "error": str(e)[:300]}},
            )
            sem = {}

    # Blend scores (keyword dominant; semantic adds tie-break)
    combined: dict[str, float] = {}
    for t in usable_tables:
        s = kw.get(t, 0.0) + 2.5 * sem.get(t, 0.0)
        combined[t] = s

    ordered = sorted(usable_tables, key=lambda x: combined.get(x, 0.0), reverse=True)
    logger.info(
        "Tables ranked for query",
        extra={
            "data": {
                "db_uri_hash": db_uri_hash,
                "total": len(usable_tables),
                "top_5": ordered[:5],
                "semantic_used": bool(sem),
            }
        },
    )
    return ordered
