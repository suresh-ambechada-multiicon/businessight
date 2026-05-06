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
        "best_raw_data": None,  # Largest result set across all queries (for data grid)
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
            # Prevent redundant execution and infinite loops
            # If the exact same query is run again, return the previous result from cache
            query_cache = tool_state.setdefault("query_cache", {})
            normalized_query = query.strip().lower()
            
            if normalized_query in query_cache:
                logger.info("SQL cache hit", extra={"data": {
                    **_ctx, "query_preview": query[:200],
                }})
                # Return the cached result so the AI can move on instead of looping
                return query_cache[normalized_query]

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

            # Keep the largest result set for the data grid display
            # This prevents aggregation queries from overwriting list query results
            best = tool_state.get("best_raw_data")
            if not best or len(rows) > len(best):
                tool_state["best_raw_data"] = rows

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
            
            # Cache the successful result
            query_cache[normalized_query] = output_str
            
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

    @tool
    def get_table_stats(table_name: str) -> str:
        """
        Get statistical overview of a table: total row count, and for each column:
        null count, distinct value count, and data type.
        Use this to understand data quality, volume, and what columns contain
        before writing analytical queries.
        """
        _status(f"Analyzing table statistics: {table_name}...")
        start = time.time()
        table_name = table_name.strip()

        try:
            schema_prefix = f"{db._schema}." if db._schema else ""
            full_table = f"{schema_prefix}{table_name}"

            with db._engine.connect() as conn:
                # Get row count
                count_result = conn.execute(text(f"SELECT COUNT(*) FROM {full_table}"))
                total_rows = count_result.scalar()

                # Get column info with null counts and distinct counts
                # Use information_schema for column names/types
                db_inspector = inspect(db._engine)
                columns = db_inspector.get_columns(table_name, schema=db._schema)

                stats_lines = [f"Table: {table_name}", f"Total Rows: {total_rows}", ""]
                stats_lines.append("Column Statistics:")

                for col in columns:
                    col_name = col["name"]
                    col_type = str(col["type"])
                    try:
                        stat_query = text(
                            f"SELECT COUNT(*) - COUNT({col_name}) as nulls, "
                            f"COUNT(DISTINCT {col_name}) as distincts "
                            f"FROM {full_table}"
                        )
                        stat_result = conn.execute(stat_query)
                        row = stat_result.fetchone()
                        null_count = row[0]
                        distinct_count = row[1]
                        null_pct = round((null_count / total_rows * 100), 1) if total_rows > 0 else 0
                        stats_lines.append(
                            f"  - {col_name} ({col_type}): {distinct_count} distinct values, "
                            f"{null_count} nulls ({null_pct}%)"
                        )
                    except Exception:
                        stats_lines.append(f"  - {col_name} ({col_type}): stats unavailable")

            elapsed_ms = round((time.time() - start) * 1000, 2)
            logger.info("Tool: get_table_stats", extra={"data": {
                **_ctx, "table": table_name, "rows": total_rows, "time_ms": elapsed_ms,
            }})
            return "\n".join(stats_lines)

        except Exception as e:
            logger.error("get_table_stats failed", extra={"data": {
                **_ctx, "table": table_name, "error": str(e),
            }})
            return f"Error getting stats for {table_name}: {str(e)}"

    @tool
    def get_column_values(table_name: str, column_name: str) -> str:
        """
        Get distinct values and their counts for a specific column.
        Use this for flag, status, enum, boolean, or category columns
        to understand what values exist BEFORE writing analytical queries.
        Example: get_column_values('agents', 'status') -> 'Active: 500, Dormant: 1037, Blocked: 21'
        """
        _status(f"Checking values in {table_name}.{column_name}...")
        start = time.time()
        table_name = table_name.strip()
        column_name = column_name.strip()

        try:
            schema_prefix = f"{db._schema}." if db._schema else ""
            full_table = f"{schema_prefix}{table_name}"

            with db._engine.connect() as conn:
                query = text(
                    f"SELECT {column_name}, COUNT(*) as cnt "
                    f"FROM {full_table} "
                    f"GROUP BY {column_name} "
                    f"ORDER BY cnt DESC "
                    f"LIMIT 50"
                )
                result = conn.execute(query)
                rows = result.fetchall()

                if not rows:
                    return f"Column {column_name} in {table_name}: no data found."

                lines = [f"Distinct values in {table_name}.{column_name}:"]
                for row in rows:
                    val = row[0]
                    cnt = row[1]
                    if val is None:
                        val = "NULL"
                    elif isinstance(val, bool):
                        val = str(val).lower()
                    lines.append(f"  - {val}: {cnt}")

            elapsed_ms = round((time.time() - start) * 1000, 2)
            logger.info("Tool: get_column_values", extra={"data": {
                **_ctx, "table": table_name, "column": column_name,
                "distinct_values": len(rows), "time_ms": elapsed_ms,
            }})
            return "\n".join(lines)

        except Exception as e:
            logger.error("get_column_values failed", extra={"data": {
                **_ctx, "table": table_name, "column": column_name, "error": str(e),
            }})
            return f"Error: {str(e)}"

    @tool
    def get_table_relationships(table_name: str) -> str:
        """
        Detect foreign key relationships for a table.
        Shows which columns reference other tables (outgoing FKs)
        and which other tables reference this table (incoming FKs).
        Use this to understand how tables are connected before writing JOINs.
        """
        _status(f"Detecting relationships for {table_name}...")
        start = time.time()
        table_name = table_name.strip()

        try:
            db_inspector = inspect(db._engine)

            # Outgoing foreign keys (this table references others)
            fks = db_inspector.get_foreign_keys(table_name, schema=db._schema)
            lines = [f"Relationships for table: {table_name}", ""]

            if fks:
                lines.append("Outgoing References (this table -> other tables):")
                for fk in fks:
                    cols = ", ".join(fk["constrained_columns"])
                    ref_table = fk["referred_table"]
                    ref_cols = ", ".join(fk["referred_columns"])
                    ref_schema = fk.get("referred_schema", "")
                    ref_full = f"{ref_schema}.{ref_table}" if ref_schema else ref_table
                    lines.append(f"  - {cols} -> {ref_full}({ref_cols})")
            else:
                lines.append("No outgoing foreign keys found.")

            # Incoming foreign keys (other tables reference this one)
            lines.append("")
            incoming = []
            for other_table in usable_tables:
                if other_table == table_name:
                    continue
                try:
                    other_fks = db_inspector.get_foreign_keys(other_table, schema=db._schema)
                    for fk in other_fks:
                        if fk["referred_table"] == table_name:
                            cols = ", ".join(fk["constrained_columns"])
                            incoming.append(f"  - {other_table}({cols}) -> this table")
                except Exception:
                    continue

            if incoming:
                lines.append("Incoming References (other tables -> this table):")
                lines.extend(incoming[:20])  # Limit to 20 to avoid token explosion
            else:
                lines.append("No incoming foreign keys detected.")

            # Also detect likely FK columns by naming convention (_id suffix)
            lines.append("")
            columns = db_inspector.get_columns(table_name, schema=db._schema)
            likely_fks = [c["name"] for c in columns if c["name"].endswith("_id")]
            if likely_fks:
                lines.append(f"Columns that may be foreign keys (by naming convention): {', '.join(likely_fks)}")

            elapsed_ms = round((time.time() - start) * 1000, 2)
            logger.info("Tool: get_table_relationships", extra={"data": {
                **_ctx, "table": table_name,
                "outgoing_fks": len(fks), "incoming_fks": len(incoming),
                "time_ms": elapsed_ms,
            }})
            return "\n".join(lines)

        except Exception as e:
            logger.error("get_table_relationships failed", extra={"data": {
                **_ctx, "table": table_name, "error": str(e),
            }})
            return f"Error: {str(e)}"

    tools = [
        execute_read_only_sql,
        get_table_info,
        search_schema,
        get_table_stats,
        get_column_values,
        get_table_relationships,
    ]
    return tools, tool_state
