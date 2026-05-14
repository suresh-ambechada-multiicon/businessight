"""
SQL security validation.

Enforces read-only access by blocking dangerous SQL patterns
beyond the simple SELECT check. Catches injection attempts via
semicolons, CTEs with side effects, and MSSQL-specific exploits.
"""

import re
import sqlparse

from analytics.constants import BLOCKED_PATTERNS
from analytics.services.logger import get_logger

logger = get_logger("security")

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]


def validate_sql(query: str, ctx=None) -> tuple[bool, str]:
    """
    Validate that a SQL query is safe to execute.
    Returns (is_safe, reason).
    """
    stripped = query.strip()
    normalized = stripped.lstrip(" \t\r\n(").upper()

    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        log_data = {"query_preview": stripped[:200]}
        if ctx:
            log_data.update(ctx.to_dict())
        logger.warning("SQL blocked: not a read-only query", extra={"data": log_data})
        return False, "Only read-only SELECT or CTE queries are allowed."

    # Layer 2: Parse AST — reject any non-SELECT statement
    try:
        parsed = sqlparse.parse(stripped)
        for statement in parsed:
            stmt_type = statement.get_type()
            # sqlparse sometimes returns 'UNKNOWN' for complex CTEs; allow read-only CTEs.
            if stmt_type not in {"SELECT", "UNKNOWN"}:
                log_data = {
                    "query_preview": stripped[:200],
                    "blocked_statement": stmt_type,
                }
                if ctx:
                    log_data.update(ctx.to_dict())
                logger.warning("SQL blocked: non-SELECT statement detected via AST", extra={"data": log_data})
                return False, f"Blocked: {stmt_type} statement detected."
    except Exception as e:
        logger.warning("SQL AST parsing failed", extra={"data": {"error": str(e)}})

    # Layer 3: Keep existing regex as extra safety net
    for pattern in _compiled_patterns:
        if pattern.search(stripped):
            log_data = {
                "query_preview": stripped[:200],
                "blocked_pattern": pattern.pattern,
            }
            if ctx:
                log_data.update(ctx.to_dict())
            logger.warning("SQL blocked: dangerous pattern detected", extra={"data": log_data})
            return False, "Query contains a blocked operation."

    return True, ""
