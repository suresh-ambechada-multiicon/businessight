"""
Database connection utilities.

Handles URI normalization (postgres/mysql/mssql driver injection),
schema detection, SQLAlchemy engine creation with connection pooling,
and Redis-cached table discovery.
"""

import os
import time
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

from django.conf import settings
from langchain_community.utilities import SQLDatabase
from sqlalchemy import inspect

from analytics.services.cache import (
    get_cached_tables,
    get_db_uri_hash,
    get_or_create_engine,
    set_cached_tables,
)
from analytics.services.logger import get_logger

logger = get_logger("db")


# Prefixes to exclude from "business tables" list
INTERNAL_TABLE_PREFIXES = ("django_", "auth_", "analytics_")


def normalize_db_uri(db_uri: str) -> str:
    """
    Normalize a raw database URI into a SQLAlchemy-compatible connection string.
    Injects the correct driver for postgres, mysql, and mssql URIs.
    """
    if not db_uri:
        db_uri = os.environ.get(
            "DATABASE_URL", f"sqlite:///{settings.BASE_DIR}/db.sqlite3"
        )

    # Fix unquoted special characters in password (like @)
    if "://" in db_uri:
        scheme, rest = db_uri.split("://", 1)
        if "@" in rest:
            credentials, host_path = rest.rsplit("@", 1)
            if ":" in credentials:
                user, password = credentials.split(":", 1)
                password = quote(unquote(password), safe="")
                db_uri = f"{scheme}://{user}:{password}@{host_path}"

    # PostgreSQL — ensure psycopg2 driver
    if db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql+psycopg2://", 1)
    elif db_uri.startswith("postgresql://") and not db_uri.startswith(
        "postgresql+psycopg2://"
    ):
        db_uri = db_uri.replace("postgresql://", "postgresql+psycopg2://", 1)

    # MySQL — ensure pymysql driver
    elif db_uri.startswith("mysql://") and not db_uri.startswith("mysql+pymysql://"):
        db_uri = db_uri.replace("mysql://", "mysql+pymysql://", 1)

    # MSSQL — ensure pymssql driver and strip unsupported JDBC kwargs
    elif db_uri.startswith(("sqlserver://", "mssql://", "mssql+pymssql://")):
        if db_uri.startswith("sqlserver://"):
            db_uri = db_uri.replace("sqlserver://", "mssql+pymssql://", 1)
        elif db_uri.startswith("mssql://") and not db_uri.startswith(
            "mssql+pymssql://"
        ):
            db_uri = db_uri.replace("mssql://", "mssql+pymssql://", 1)

        # pymssql does not support JDBC-style kwargs like encrypt=true
        parsed = urlparse(db_uri)
        if parsed.query:
            qs = parse_qs(parsed.query)
            keys_to_remove = [
                k
                for k in qs
                if k.lower()
                in ("encrypt", "trustservercertificate", "multipleactiveresultsets")
            ]
            for k in keys_to_remove:
                qs.pop(k, None)

            # Reconstruct the query string
            new_query = urlencode(qs, doseq=True)
            # Reconstruct the full URL
            db_uri = urlunparse(parsed._replace(query=new_query))

    return db_uri


def build_engine_args(db_uri: str) -> dict:
    """Return SQLAlchemy engine kwargs appropriate for the dialect."""
    engine_args = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,  # Recycle connections every 30 mins
        "pool_size": 10,
        "max_overflow": 20,
    }

    if db_uri.startswith("mssql+pymssql://"):
        parsed = urlparse(db_uri)
        qs = parse_qs(parsed.query)

        # pymssql expects these in connect_args, not URI
        encrypt = qs.get("encrypt", ["false"])[0].lower() == "true"

        engine_args["connect_args"] = {
            "timeout": 30,  # Query timeout
            "login_timeout": 15,  # Connection timeout - fail fast!
            "autocommit": True,
            "tds_version": "7.4",
        }

        if encrypt:
            # Note: pymssql's encryption support depends on FreeTDS configuration
            pass

    return engine_args


def detect_active_schema(db_uri: str, engine_args: dict, ctx=None):
    """
    Detect the best schema for databases where the default schema is empty.
    Uses Redis cache to skip expensive introspection on repeated requests.
    """
    db_uri_hash = get_db_uri_hash(db_uri)
    from analytics.services.cache import get_cached_schema, set_cached_schema

    # 1. Try cache first
    cached_schema = get_cached_schema(db_uri_hash)
    if cached_schema is not None:
        if cached_schema and "postgresql" in db_uri:
            parsed = urlparse(db_uri)
            qs = parse_qs(parsed.query)
            qs["options"] = [f"-c search_path={cached_schema},public"]
            db_uri = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
            return db_uri, None
        return db_uri, cached_schema if cached_schema else None

    # 2. Cache miss — inspect
    start_detect = time.time()

    # Send status if we have a task ID
    from analytics.services.status import send_status

    task_id = ctx.task_id if ctx else ""
    send_status(task_id, "Connecting to database...")

    engine = get_or_create_engine(db_uri, engine_args)
    db_inspector = inspect(engine)
    active_schema = None

    # Fast path for SQL Server
    if "mssql" in db_uri:
        try:
            if db_inspector.get_table_names(schema="dbo"):
                active_schema = "dbo"
        except Exception:
            pass

    if not active_schema:
        # Fallback to default schema inspection
        try:
            if not db_inspector.get_table_names():
                for s in db_inspector.get_schema_names():
                    if s.lower() in (
                        "information_schema",
                        "pg_catalog",
                        "public",
                        "guest",
                        "sys",
                        "information_schema",
                    ):
                        continue
                    try:
                        if db_inspector.get_table_names(schema=s):
                            active_schema = s
                            break
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"Schema detection error: {str(e)}")

    # 3. Store result in cache (even if None, as empty string)
    set_cached_schema(db_uri_hash, active_schema or "")

    detect_time = round((time.time() - start_detect) * 1000, 2)
    logger.info(
        "Active schema detected",
        extra={
            "data": {
                "schema": active_schema,
                "db_uri_hash": db_uri_hash,
                "detect_time_ms": detect_time,
            }
        },
    )

    # For PostgreSQL, set search_path so queries don't need schema prefix
    if active_schema and "postgresql" in db_uri:
        parsed = urlparse(db_uri)
        qs = parse_qs(parsed.query)
        qs["options"] = [f"-c search_path={active_schema},public"]
        db_uri = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
        active_schema = None  # search_path handles it now

    return db_uri, active_schema


def create_database(db_uri: str, engine_args: dict, active_schema):
    """Create the LangChain SQLDatabase instance using the pooled engine."""
    from sqlalchemy import MetaData

    engine = get_or_create_engine(db_uri, engine_args)
    # lazy_table_reflection=True prevents LangChain from calling
    # metadata.reflect() on init, which reflects ALL tables (columns, FKs,
    # indexes) and takes 2+ minutes on large SQL Server databases.
    # Tables are reflected on-demand when the AI tools actually need them.
    return SQLDatabase(
        engine=engine,
        schema=active_schema,
        sample_rows_in_table_info=0,
        view_support=False,
        metadata=MetaData(),
        lazy_table_reflection=True,
    )


def discover_tables(db, active_schema, ctx=None) -> list[str]:
    """
    List all business tables in the database, filtering out
    internal Django/system tables. Uses Redis cache to avoid
    re-inspecting on every request.
    """
    db_uri_hash = ctx.db_uri_hash if ctx else ""

    # Try cache first
    if db_uri_hash:
        cached = get_cached_tables(db_uri_hash)
        if cached is not None:
            logger.info(
                "Tables loaded from cache",
                extra={
                    "data": {
                        **(ctx.to_dict() if ctx else {}),
                        "table_count": len(cached),
                        "source": "redis_cache",
                    }
                },
            )
            return cached

    # Cache miss — inspect the database
    start = time.time()
    all_tables = []
    try:
        # Use a faster direct query for SQL Server to bypass slow SQLAlchemy inspection
        if "mssql" in db._engine.url.drivername:
            from sqlalchemy import text as sa_text
            with db._engine.connect() as conn:
                # Use sys.tables which is much faster than INFORMATION_SCHEMA in many cases
                query = "SELECT name FROM sys.tables WHERE is_ms_shipped = 0"
                if active_schema:
                    query += f" AND SCHEMA_NAME(schema_id) = '{active_schema}'"
                result = conn.execute(sa_text(query))
                all_tables = [row[0] for row in result]

        if not all_tables:
            db_inspector = inspect(db._engine)
            all_tables = db_inspector.get_table_names(schema=active_schema)

    except Exception as e:
        logger.warning(f"Fast table discovery failed, falling back: {str(e)}")
        db_inspector = inspect(db._engine)
        all_tables = db_inspector.get_table_names(schema=active_schema)

    usable = [t for t in all_tables if not t.startswith(INTERNAL_TABLE_PREFIXES)]
    inspect_time = round((time.time() - start) * 1000, 2)

    logger.info(
        "Tables discovered via inspection",
        extra={
            "data": {
                **(ctx.to_dict() if ctx else {}),
                "total_tables": len(all_tables),
                "usable_tables": len(usable),
                "inspect_time_ms": inspect_time,
                "source": "db_inspector",
            }
        },
    )

    # Cache the result
    if db_uri_hash:
        set_cached_tables(db_uri_hash, usable)

    return usable


def detect_dialect(db_uri: str) -> str:
    """Detect the SQL dialect from the connection URI."""
    if "mssql" in db_uri or "sqlserver" in db_uri:
        return "Microsoft SQL Server"
    elif "mysql" in db_uri:
        return "MySQL"
    elif "sqlite" in db_uri:
        return "SQLite"
    elif "oracle" in db_uri:
        return "Oracle"
    elif "postgresql" in db_uri or "postgres" in db_uri:
        return "PostgreSQL"
    return "PostgreSQL"  # Safe default for psycopg2-based URIs
