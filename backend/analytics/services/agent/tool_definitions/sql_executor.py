"""
SQL Executor Tool - Execute read-only SELECT queries against the database.
"""

import json
import re
import time
import datetime
from decimal import Decimal
import uuid

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.database.security import validate_sql
from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def _normalize_sql_key(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def create_sql_executor(db, tool_state, ctx, _status, _ctx, _quote_ident, _full_table, _select_top, max_rows):
    """Factory to create the SQL executor tool."""

    @tool
    def execute_read_only_sql(query: str) -> str:
        """
        Executes a read-only SQL SELECT query against the connected database.
        Use this tool to fetch data to answer the user's analytical questions.
        IMPORTANT: This returns a JSON string array of dicts representing the rows.
        """
        return _run_sql(query, mark_final=False)

    @tool
    def execute_final_sql(query: str) -> str:
        """
        Executes a read-only SQL SELECT query and marks it as the final dataset for reporting.
        Use this tool once you have the correct query that directly answers the user.
        """
        return _run_sql(query, mark_final=True)

    def _run_sql(query: str, *, mark_final: bool) -> str:
        def _query_fingerprint(q: str) -> str:
            """Normalize query shape to detect near-duplicate thrashing attempts."""
            norm = " ".join((q or "").strip().lower().split())
            norm = re.sub(r"\btop\s+\d+\b", "top ?", norm)
            norm = re.sub(r"\blimit\s+\d+\b", "limit ?", norm)
            norm = re.sub(r"\boffset\s+\d+\b", "offset ?", norm)
            return norm

        # Clean query if it has wrapper comments
        matches = list(
            re.finditer(
                r"-- Query \d+(?: \([^)]+\))?\s*\n([\s\S]*?)(?=-- Query \d+|$)",
                query or "",
            )
        )
        if matches:
            query = matches[0].group(1).strip()

        # Enforce single statement at tool boundary (defense in depth).
        q_stripped = (query or "").strip()
        if ";" in q_stripped[:-1]:
            return json.dumps(
                {
                    "error": "Only single-statement SELECT queries are allowed.",
                    "reason": "multi_statement_semicolon",
                }
            )

        # Security validation
        is_safe, reason = validate_sql(query, ctx)
        if not is_safe:
            return json.dumps({"error": reason})

        try:
            # Prevent redundant execution
            query_cache = tool_state.setdefault("query_cache", {})
            normalized_query = _normalize_sql_key(query)
            query_fingerprint = _query_fingerprint(query)

            # Hard cap on how many times the agent can call this tool per request.
            tool_state["sql_call_count"] = int(tool_state.get("sql_call_count") or 0) + 1
            sql_limit = int(tool_state.get("sql_call_limit") or 8)
            if tool_state["sql_call_count"] > sql_limit:
                logger.warning(
                    "SQL tool call budget exceeded",
                    extra={
                        **_ctx,
                        "sql_call_count": tool_state["sql_call_count"],
                        "sql_call_limit": sql_limit,
                        "query_preview": query[:200],
                    },
                )
                from langchain_core.exceptions import OutputParserException
                raise ValueError("SQL tool call budget exceeded. Too many SQL queries executed.")

            fp_counts = tool_state.setdefault("query_fingerprint_counts", {})
            fp_counts[query_fingerprint] = int(fp_counts.get(query_fingerprint) or 0) + 1
            if fp_counts[query_fingerprint] > 2:
                logger.warning(
                    "Blocked repetitive SQL query shape",
                    extra={
                        **_ctx,
                        "query_preview": query[:200],
                        "fingerprint": query_fingerprint[:300],
                        "repeats": fp_counts[query_fingerprint],
                    },
                )
                return json.dumps(
                    {
                        "error": (
                            "Repeated near-duplicate SQL query detected. "
                            "Use the existing result and finalize your report."
                        )
                    }
                )

            if normalized_query in query_cache:
                logger.info(
                    "Tool: execute_read_only_sql (cached)",
                    extra={**_ctx, "query_preview": query[:200], "query": query},
                )
                data = query_cache[normalized_query]
                tool_state["last_sql_query"] = query
                tool_state["last_raw_data"] = data
                if mark_final:
                    tool_state["final_sql_query"] = query
                    tool_state["final_raw_data"] = data
                    tool_state["final_query_reason"] = "execute_final_sql"
                return json.dumps({"cached": True, "data": data})

            _status(f"Executing SQL: {query}")
            start = time.time()

            with db._engine.connect() as conn:
                try:
                    # Apply defensive query timeouts based on dialect
                    if "postgres" in db._engine.url.drivername:
                        conn.execute(text("SET statement_timeout = 45000"))
                    elif "mysql" in db._engine.url.drivername:
                        conn.execute(text("SET max_execution_time = 45000"))
                except Exception:
                    pass

                # Use stream_results=True to use server-side cursors (prevents OOM on large tables)
                result = conn.execution_options(stream_results=True).execute(text(query))
                # Use fetchmany instead of fetchall to avoid loading millions of rows into RAM
                rows = result.fetchmany(max_rows + 1)
                
                has_more = len(rows) > max_rows
                if has_more:
                    rows = rows[:max_rows]
                
                # Convert to dicts
                columns = result.keys()
                data = [dict(zip(columns, row)) for row in rows]

            elapsed = round((time.time() - start) * 1000, 2)
            
            # Cache for future
            query_cache[normalized_query] = data
            
            # Update tool state
            tool_state["last_sql_query"] = query
            tool_state["last_raw_data"] = data
            if len(data) > len(tool_state.get("best_raw_data") or []):
                tool_state["best_raw_data"] = data
            if mark_final:
                tool_state["final_sql_query"] = query
                tool_state["final_raw_data"] = data
                tool_state["final_query_reason"] = "execute_final_sql"
            tool_state["all_sql_queries"].append({
                "query": query,
                "time": elapsed,
                "rows": len(data),
            })

            logger.info("Tool: execute_read_only_sql", extra={
                **_ctx,
                "query_preview": query[:200],
                "query": query,  # Full query for debugging
                "time_ms": elapsed,
                "rows": len(data),
            })

            # Track in state for later reference (full data for UI)
            tool_state["last_tool_call"] = "execute_read_only_sql"
            
            def json_serializer(obj):
                if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
                    return obj.isoformat()
                if isinstance(obj, Decimal):
                    return float(obj)
                if isinstance(obj, uuid.UUID):
                    return str(obj)
                if isinstance(obj, (bytes, memoryview)):
                    return "(binary data)"
                return str(obj)

            # Truncate data returned to the LLM to save tokens
            # The UI will still get the full 'data' array from tool_state
            LLM_MAX_ROWS = 50
            if len(data) > LLM_MAX_ROWS:
                total_msg = f"{len(data)}+" if has_more else str(len(data))
                llm_response = {
                    "_meta": f"Result truncated. Found {total_msg} rows total. Showing first {LLM_MAX_ROWS} rows. CRITICAL: DO NOT rewrite the query to avoid truncation. Use this truncated sample to generate your final report immediately.",
                    "total_rows_found": len(data),
                    "data": data[:LLM_MAX_ROWS]
                }
                return json.dumps(llm_response, default=json_serializer)
            
            return json.dumps(data, default=json_serializer)
        except Exception as e:
            logger.error("SQL execution failed", extra={**_ctx, "query_preview": query[:500], "query": query, "error": str(e)})
            return json.dumps({"error": f"Error executing query: {str(e)}"})

    return [execute_read_only_sql, execute_final_sql]