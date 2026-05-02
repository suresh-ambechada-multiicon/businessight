"""
AI agent tools for database analytics.

Defines the LangChain tools that the AI agent uses to interact with
the client database: execute SQL, inspect schemas, and search tables.
Every tool call is logged with timing and context.
"""

import json
import time

from decimal import Decimal
from langchain.tools import tool
from sqlalchemy import inspect, text

from analytics.services.logger import get_logger
from analytics.services.security import validate_sql

logger = get_logger("tools")


# Maximum rows returned to the AI to prevent context token explosion
MAX_ROWS_FOR_AI = 500


def create_tools(db, usable_tables: list[str], ctx=None):
    """
    Factory that creates the three analytics tools bound to a specific
    database connection and table list.

    Returns (tools_list, tool_state_dict).
    tool_state tracks executed queries and their timings.
    """

    tool_state = {
        "last_sql_query": "",
        "last_raw_data": None,
        "all_sql_queries": [],  # List of dicts: {"query": str, "time": float}
    }

    # Log context helper
    _ctx = ctx.to_dict() if ctx else {}

    def _get_table_schema(table_names: str) -> str:
        """Internal helper to fetch column info for one or more tables."""
        try:
            tables = [t.strip() for t in table_names.split(",") if t.strip()]
            db_inspector = inspect(db._engine)
            output = []
            for t in tables:
                columns = db_inspector.get_columns(t, schema=db._schema)
                cols_str = ", ".join([f"{c['name']} {str(c['type'])}" for c in columns])
                output.append(f"Table '{t}' columns: {cols_str}")
            return "\n".join(output) if output else "No tables found."
        except Exception as e:
            logger.error("Schema inspection failed", extra={"data": {
                **_ctx, "tables": table_names, "error": str(e),
            }})
            return f"Error getting table info: {str(e)}"

    @tool
    def execute_read_only_sql(query: str) -> str:
        """
        Executes a read-only SQL SELECT query against the connected database.
        Use this tool to fetch data to answer the user's analytical questions.
        IMPORTANT: This returns a JSON string array of dicts representing the rows.
        """
        # Security validation
        is_safe, reason = validate_sql(query, ctx)
        if not is_safe:
            return json.dumps({"error": reason})

        try:
            if query.strip() == tool_state.get("last_sql_query", "").strip():
                logger.warning("Duplicate SQL blocked", extra={"data": {
                    **_ctx, "query_preview": query[:200],
                }})
                return json.dumps({
                    "error": "You just ran this exact query. "
                             "It is either returning the same result or failing. "
                             "Please try a different approach or stop."
                })

            tool_state["last_sql_query"] = query
            tool_state["last_raw_data"] = None

            start_q_time = time.time()

            with db._engine.connect() as connection:
                result = connection.execute(text(query))
                keys = result.keys()

                fetched = result.fetchmany(MAX_ROWS_FOR_AI + 1)
                has_more = len(fetched) > MAX_ROWS_FOR_AI
                to_process = fetched[:MAX_ROWS_FOR_AI]

                rows = []
                for row in to_process:
                    row_dict = {}
                    for i, key in enumerate(keys):
                        val = row[i]
                        if isinstance(val, Decimal):
                            val = float(val)
                        elif hasattr(val, "isoformat"):
                            val = val.isoformat()
                        row_dict[key] = val
                    rows.append(row_dict)

            q_time = time.time() - start_q_time
            tool_state["all_sql_queries"].append({"query": query, "time": q_time})
            tool_state["last_raw_data"] = rows

            logger.info("SQL executed", extra={"data": {
                **_ctx,
                "query": query,
                "rows_returned": len(rows),
                "truncated": has_more,
                "execution_time_ms": round(q_time * 1000, 2),
                "query_index": len(tool_state["all_sql_queries"]),
            }})

            output_str = json.dumps(rows)
            if has_more:
                output_str += (
                    f"\n\nWARNING: The query returned too many rows. Output has been "
                    f"truncated to the first {MAX_ROWS_FOR_AI} rows to prevent memory "
                    f"overflow. If you need total counts or aggregated data, you MUST "
                    f"rewrite your SQL query using COUNT(), SUM(), or GROUP BY instead "
                    f"of SELECT *."
                )
            return output_str
        except Exception as e:
            logger.error("SQL execution failed", extra={"data": {
                **_ctx,
                "query_preview": query[:300],
                "error": str(e),
            }})
            return json.dumps({"error": f"Error executing query: {str(e)}"})

    @tool
    def get_table_info(table_names: str) -> str:
        """
        Get the schema for the specified tables.
        Pass a comma-separated list of table names, e.g., 'users, orders'.
        """
        start = time.time()
        result = _get_table_schema(table_names)
        elapsed = round((time.time() - start) * 1000, 2)

        logger.info("Tool: get_table_info", extra={"data": {
            **_ctx,
            "tables": table_names,
            "time_ms": elapsed,
        }})
        return result

    @tool
    def search_schema(keyword: str) -> str:
        """
        Search for tables matching a keyword (e.g., 'sales', 'price', 'user').
        Use this tool when there are many tables and you don't know which one contains the data.
        """
        start = time.time()
        keyword = keyword.strip().lower().replace("'", "").replace("%", "")
        if not keyword:
            return "Please provide a valid keyword."

        matching_tables = [t for t in usable_tables if keyword in t.lower()]

        if not matching_tables:
            logger.info("Tool: search_schema (no matches)", extra={"data": {
                **_ctx,
                "keyword": keyword,
                "matches": 0,
                "time_ms": round((time.time() - start) * 1000, 2),
            }})
            return (
                f"No tables found matching '{keyword}'. "
                f"Try a different keyword (e.g., 'booking', 'master', 'customer')."
            )

        # Limit to top 10 matches to avoid overwhelming context
        matching_tables = matching_tables[:10]
        result = (
            f"Found {len(matching_tables)} matching tables:\n"
            + _get_table_schema(", ".join(matching_tables))
        )

        elapsed = round((time.time() - start) * 1000, 2)
        logger.info("Tool: search_schema", extra={"data": {
            **_ctx,
            "keyword": keyword,
            "matches": len(matching_tables),
            "matched_tables": matching_tables,
            "time_ms": elapsed,
        }})

        return result

    tools = [execute_read_only_sql, get_table_info, search_schema]
    return tools, tool_state
