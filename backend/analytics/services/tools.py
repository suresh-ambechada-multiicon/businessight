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
from analytics.services.status import send_status

logger = get_logger("tools")


def create_tools(db, usable_tables: list[str], ctx=None, token_budget=None):
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

    # Dynamic row limit calculation based on budget
    max_rows = 1000
    if token_budget:
        available = token_budget.get("available_for_tools", 100000)
        # Assume ~150 tokens per row for an average table (10 columns * 15 tokens)
        tokens_per_row = 150
        usable_budget = int(available * 0.7)  # reserve 30% for reasoning
        max_rows = max(20, min(1000, usable_budget // tokens_per_row))

    # Log context helper
    _ctx = ctx.to_dict() if ctx else {}
    _task_id = ctx.task_id if ctx else ""
    _db_uri_hash = ctx.db_uri_hash if ctx else ""

    def _status(msg: str):
        send_status(_task_id, msg)

    def _get_table_schema(table_names: str) -> str:
        """Internal helper to fetch column info for one or more tables. Uses per-table cache."""
        from analytics.services.cache import get_cached_column_info, set_cached_column_info
        
        try:
            tables = [t.strip() for t in table_names.split(",") if t.strip()]
            output = []
            
            for t in tables:
                # Check per-table cache first
                if _db_uri_hash:
                    cached = get_cached_column_info(_db_uri_hash, t)
                    if cached is not None:
                        output.append(cached)
                        continue

                # Try fast MSSQL path
                col_str = ""
                try:
                    if "mssql" in db.engine.url.drivername:
                        with db.engine.connect() as conn:
                            full_table_name = f"{db._schema}.{t}" if db._schema else t
                            query = f"""
                                SELECT c.name, tp.name as type 
                                FROM sys.columns c 
                                JOIN sys.types tp ON c.user_type_id = tp.user_type_id 
                                WHERE c.object_id = OBJECT_ID('{full_table_name}')
                            """
                            result = conn.execute(text(query))
                            cols = [f"{row[0]} {row[1]}" for row in result]
                            if cols:
                                col_str = f"Table '{t}' columns: {', '.join(cols)}"
                except Exception:
                    pass
                
                # Fallback to SQLAlchemy inspector
                if not col_str:
                    db_inspector = inspect(db._engine)
                    columns = db_inspector.get_columns(t, schema=db._schema)
                    cols_str = ", ".join([f"{c['name']} {str(c['type'])}" for c in columns])
                    col_str = f"Table '{t}' columns: {cols_str}"
                
                # Cache per-table result
                if _db_uri_hash and col_str:
                    set_cached_column_info(_db_uri_hash, t, col_str)

                output.append(col_str)
            
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
        # Note: stream_agent already emits a 'tool' event with the query text.
        # Don't send a status here — it would overwrite the SQL display in the UI.
        # Security validation
        is_safe, reason = validate_sql(query, ctx)
        if not is_safe:
            return json.dumps({"error": reason})

        try:
            # Prevent infinite loops (e.g. alternating Query A, Query B, Query A...)
            past_queries = [q["query"].strip() for q in tool_state.get("all_sql_queries", [])]
            if query.strip() in past_queries:
                logger.warning("Duplicate SQL loop blocked", extra={"data": {
                    **_ctx, "query_preview": query[:200],
                }})
                return json.dumps({
                    "error": "You have already executed this exact query earlier in this session. "
                             "You are stuck in a loop. You MUST STOP querying now and write your final report using the data you already have."
                })

            tool_state["last_sql_query"] = query
            tool_state["last_raw_data"] = None

            start_q_time = time.time()

            with db._engine.connect() as connection:
                result = connection.execute(text(query))
                keys = result.keys()

                fetched = result.fetchmany(max_rows + 1)
                has_more = len(fetched) > max_rows
                to_process = fetched[:max_rows]

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

            output_str = f"Query returned {len(rows)} rows.\n" + json.dumps(rows)
            if has_more:
                output_str += (
                    f"\n\nWARNING: The query returned too many rows. Output has been "
                    f"truncated to the first {max_rows} rows to prevent memory "
                    f"overflow. If you need total counts or aggregated data, you MUST "
                    f"rewrite your SQL query using COUNT(), SUM(), or GROUP BY instead "
                    f"of SELECT *."
                )
            # Note: Deliberately NOT sending a status update here so the frontend
            # keeps displaying the SQL query bubble instead of overwriting it with row counts.
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
        _status(f"Inspecting table: {table_names}...")
        start = time.time()
        result = _get_table_schema(table_names)
        elapsed = round((time.time() - start) * 1000, 2)

        logger.info("Tool: get_table_info", extra={"data": {
            **_ctx,
            "tables": table_names,
            "time_ms": elapsed,
        }})
        _status("Table inspection complete")
        return result

    @tool
    def search_schema(keyword: str) -> str:
        """
        Search for tables matching a keyword (e.g., 'sales', 'price', 'user').
        Use this tool when there are many tables and you don't know which one contains the data.
        """
        _status(f"Searching for '{keyword}'...")
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
            _status(f"No tables found matching '{keyword}'")
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

        _status(f"Found {len(matching_tables)} relevant tables")
        return result

    tools = [execute_read_only_sql, get_table_info, search_schema]
    return tools, tool_state
