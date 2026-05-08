"""
SQL Executor Tool - Execute read-only SELECT queries against the database.
"""

import json
import re
import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.database.security import validate_sql
from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_sql_executor(db, tool_state, ctx, _status, _ctx, _quote_ident, _full_table, _select_top, max_rows):
    """Factory to create the SQL executor tool."""

    @tool
    def execute_read_only_sql(query: str) -> str:
        """
        Executes a read-only SQL SELECT query against the connected database.
        Use this tool to fetch data to answer the user's analytical questions.
        IMPORTANT: This returns a JSON string array of dicts representing the rows.
        """
        # Clean query if it has wrapper comments
        matches = list(re.finditer(r"-- Query \d+(?: \([^)]+\))?\s*\n([\s\S]*?)(?=-- Query \d+|$)", query))
        if matches:
            query = matches[0].group(1).strip()
            
        # Security validation
        is_safe, reason = validate_sql(query, ctx)
        if not is_safe:
            return json.dumps({"error": reason})

        try:
            # Prevent redundant execution
            query_cache = tool_state.setdefault("query_cache", {})
            normalized_query = query.strip().lower()
            
            if normalized_query in query_cache:
                logger.info("Tool: execute_read_only_sql (cached)", extra={**_ctx, "query_preview": query[:200], "query": query})
                return json.dumps({"cached": True, "data": query_cache[normalized_query]})

            _status(f"Executing SQL: {query}")
            start = time.time()

            with db._engine.connect() as conn:
                result = conn.execute(text(query))
                rows = result.fetchall()
                
                # Limit rows
                if len(rows) > max_rows:
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
            
            # Truncate data returned to the LLM to save tokens
            # The UI will still get the full 'data' array from tool_state
            LLM_MAX_ROWS = 50
            if len(data) > LLM_MAX_ROWS:
                llm_response = {
                    "_meta": f"Result truncated. Found {len(data)} rows total. Showing first {LLM_MAX_ROWS} rows to save tokens.",
                    "total_rows_found": len(data),
                    "data": data[:LLM_MAX_ROWS]
                }
                return json.dumps(llm_response)
            
            return json.dumps(data)
        except Exception as e:
            logger.error("SQL execution failed", extra={**_ctx, "query_preview": query[:500], "query": query, "error": str(e)})
            return json.dumps({"error": f"Error executing query: {str(e)}"})

    return execute_read_only_sql