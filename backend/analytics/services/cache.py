"""
Caching and connection pooling for database operations.

Uses Redis (via Django cache) for schema caching and provides
a thread-safe engine pool to avoid creating new SQLAlchemy engines per request.
"""

import hashlib
import threading

from django.core.cache import cache
from sqlalchemy import create_engine

from analytics.services.logger import get_logger

logger = get_logger("cache")

# ── Thread-safe engine pool ─────────────────────────────────────────────
# Maps {uri_hash: Engine}. Engines are reused across requests for the same DB.
_engine_pool: dict[str, any] = {}
_engine_lock = threading.Lock()

# Cache TTL for schema discovery
SCHEMA_CACHE_TTL = 3600  # 1 hour


def get_db_uri_hash(db_uri: str) -> str:
    """Generate a short hash of the DB URI for cache keys and safe logging."""
    return hashlib.md5(db_uri.encode()).hexdigest()[:12]


# ── Schema Cache ────────────────────────────────────────────────────────

def get_cached_tables(db_uri_hash: str) -> list[str] | None:
    """Retrieve cached table list from Redis. Returns None on miss."""
    cache_key = f"schema:tables:{db_uri_hash}"
    result = cache.get(cache_key)
    if result is not None:
        logger.debug("Schema cache HIT", extra={"data": {
            "db_uri_hash": db_uri_hash,
            "table_count": len(result),
        }})
    return result


def set_cached_tables(db_uri_hash: str, tables: list[str]):
    """Store table list in Redis cache."""
    cache_key = f"schema:tables:{db_uri_hash}"
    cache.set(cache_key, tables, timeout=SCHEMA_CACHE_TTL)
    logger.info("Schema cached", extra={"data": {
        "db_uri_hash": db_uri_hash,
        "table_count": len(tables),
        "ttl_seconds": SCHEMA_CACHE_TTL,
    }})


def get_cached_schema(db_uri_hash: str) -> str | None:
    """Retrieve the detected active schema name from cache."""
    return cache.get(f"schema:active:{db_uri_hash}")


def set_cached_schema(db_uri_hash: str, schema_name: str):
    """Store the detected active schema name in cache."""
    cache.set(f"schema:active:{db_uri_hash}", schema_name, timeout=SCHEMA_CACHE_TTL)


def get_cached_schema_context(db_uri_hash: str) -> str | None:
    """Retrieve the full schema context string from cache."""
    return cache.get(f"schema:context:{db_uri_hash}")


def set_cached_schema_context(db_uri_hash: str, context: str):
    """Store the full schema context string in cache."""
    cache.set(f"schema:context:{db_uri_hash}", context, timeout=SCHEMA_CACHE_TTL)
    logger.info("Schema context cached", extra={"data": {
        "db_uri_hash": db_uri_hash,
        "context_length": len(context),
    }})


def get_cached_column_info(db_uri_hash: str, table_name: str) -> str | None:
    """Retrieve cached column info for a specific table."""
    return cache.get(f"schema:cols:{db_uri_hash}:{table_name}")


def set_cached_column_info(db_uri_hash: str, table_name: str, info: str):
    """Store column info for a specific table."""
    cache.set(f"schema:cols:{db_uri_hash}:{table_name}", info, timeout=SCHEMA_CACHE_TTL)


def invalidate_schema_cache(db_uri_hash: str):
    """Force-clear the schema cache for a specific database."""
    cache.delete(f"schema:tables:{db_uri_hash}")
    cache.delete(f"schema:active:{db_uri_hash}")
    cache.delete(f"schema:context:{db_uri_hash}")
    logger.info("Schema cache invalidated", extra={"data": {"db_uri_hash": db_uri_hash}})


# ── Engine Pool ─────────────────────────────────────────────────────────

def get_or_create_engine(db_uri: str, engine_args: dict):
    """
    Thread-safe engine pool. Reuses existing engines for the same URI.
    Eliminates the cost of creating a new engine + connection pool per request.
    """
    uri_hash = get_db_uri_hash(db_uri)
    with _engine_lock:
        if uri_hash not in _engine_pool:
            _engine_pool[uri_hash] = create_engine(db_uri, **engine_args)
            logger.info("New engine created", extra={"data": {"db_uri_hash": uri_hash}})
        else:
            logger.debug("Engine reused from pool", extra={"data": {"db_uri_hash": uri_hash}})
        return _engine_pool[uri_hash]


def dispose_engine(db_uri: str):
    """Dispose of a pooled engine (e.g., on connection error)."""
    uri_hash = get_db_uri_hash(db_uri)
    with _engine_lock:
        engine = _engine_pool.pop(uri_hash, None)
        if engine:
            engine.dispose()
            logger.info("Engine disposed", extra={"data": {"db_uri_hash": uri_hash}})
