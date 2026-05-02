"""
Database connection utilities.

Handles URI normalization (postgres/mysql/mssql driver injection),
schema detection, and SQLAlchemy engine creation.
"""

import os
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from django.conf import settings
from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine, inspect


# Prefixes to exclude from "business tables" list
INTERNAL_TABLE_PREFIXES = ('django_', 'auth_', 'analytics_queryhistory')


def normalize_db_uri(db_uri: str) -> str:
    """
    Normalize a raw database URI into a SQLAlchemy-compatible connection string.
    Injects the correct driver for postgres, mysql, and mssql URIs.
    """
    if not db_uri:
        db_uri = os.environ.get(
            "DATABASE_URL", f"sqlite:///{settings.BASE_DIR}/db.sqlite3"
        )

    # PostgreSQL — ensure psycopg2 driver
    if db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql+psycopg2://", 1)
    elif db_uri.startswith("postgresql://") and not db_uri.startswith("postgresql+psycopg2://"):
        db_uri = db_uri.replace("postgresql://", "postgresql+psycopg2://", 1)

    # MySQL — ensure pymysql driver
    elif db_uri.startswith("mysql://") and not db_uri.startswith("mysql+pymysql://"):
        db_uri = db_uri.replace("mysql://", "mysql+pymysql://", 1)

    # MSSQL — ensure pymssql driver and strip unsupported JDBC kwargs
    elif db_uri.startswith(("sqlserver://", "mssql://", "mssql+pymssql://")):
        if db_uri.startswith("sqlserver://"):
            db_uri = db_uri.replace("sqlserver://", "mssql+pymssql://", 1)
        elif db_uri.startswith("mssql://") and not db_uri.startswith("mssql+pymssql://"):
            db_uri = db_uri.replace("mssql://", "mssql+pymssql://", 1)

        # pymssql does not support JDBC-style kwargs like encrypt=true
        parsed = urlparse(db_uri)
        if parsed.query:
            qs = parse_qs(parsed.query)
            keys_to_remove = [k for k in qs if k.lower() in ("encrypt", "trustservercertificate")]
            for k in keys_to_remove:
                qs.pop(k, None)
            db_uri = parsed._replace(query=urlencode(qs, doseq=True)).geturl()

    return db_uri


def build_engine_args(db_uri: str) -> dict:
    """Return SQLAlchemy engine kwargs appropriate for the dialect."""
    engine_args = {"pool_pre_ping": True}

    if not db_uri.startswith("sqlite"):
        engine_args.update({"pool_size": 5, "max_overflow": 10})

    if db_uri.startswith("mssql+pymssql://"):
        engine_args["connect_args"] = {"timeout": 15, "login_timeout": 15}

    return engine_args


def detect_active_schema(db_uri: str, engine_args: dict):
    """
    Detect the best schema for databases where the default schema is empty.
    Returns (possibly modified db_uri, active_schema).
    """
    temp_engine = create_engine(db_uri, **engine_args)
    db_inspector = inspect(temp_engine)

    active_schema = None
    if not db_inspector.get_table_names():
        for s in db_inspector.get_schema_names():
            if s not in ('information_schema', 'pg_catalog', 'public'):
                if db_inspector.get_table_names(schema=s):
                    active_schema = s
                    break
    temp_engine.dispose()

    # For PostgreSQL, set search_path so queries don't need schema prefix
    if active_schema and "postgresql" in db_uri:
        parsed = urlparse(db_uri)
        qs = parse_qs(parsed.query)
        qs['options'] = [f"-c search_path={active_schema},public"]
        db_uri = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
        active_schema = None  # search_path handles it now

    return db_uri, active_schema


def create_database(db_uri: str, engine_args: dict, active_schema):
    """Create the LangChain SQLDatabase instance."""
    return SQLDatabase.from_uri(
        db_uri,
        engine_args=engine_args,
        schema=active_schema,
        sample_rows_in_table_info=0,
        view_support=False,
        include_tables=[],
    )


def discover_tables(db, active_schema) -> list[str]:
    """
    List all business tables in the database, filtering out
    internal Django/system tables.
    """
    db_inspector = inspect(db._engine)
    all_tables = db_inspector.get_table_names(schema=active_schema)
    return [t for t in all_tables if not t.startswith(INTERNAL_TABLE_PREFIXES)]


def detect_dialect(db_uri: str) -> str:
    """Detect the SQL dialect from the connection URI."""
    if "mssql" in db_uri or "sqlserver" in db_uri:
        return "Microsoft SQL Server"
    elif "mysql" in db_uri:
        return "MySQL"
    elif "sqlite" in db_uri:
        return "SQLite"
    return "PostgreSQL"
