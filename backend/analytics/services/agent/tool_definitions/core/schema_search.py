"""
Schema Search Tool - Search tables/columns by keyword.
"""

import time

from langchain.tools import tool
from sqlalchemy import inspect

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_schema_search_tool(db, usable_tables, tool_state, ctx, _status, _ctx):
    """Factory to create the search_schema tool."""

    @tool
    def search_schema(keyword: str) -> str:
        """
        Search for tables and columns by keyword.
        Use this when you don't know the exact table name but have a general idea.
        Returns matching table names and their column names.
        """
        # Budget + cache to avoid redundant loops
        kw = (keyword or "").strip()
        cache_key = ("search_schema", kw.lower())
        cache = (
            tool_state.setdefault("tool_cache", {})
            if isinstance(tool_state, dict)
            else {}
        )
        if cache_key in cache:
            return cache[cache_key]

        counts = (
            tool_state.setdefault("tool_call_counts", {})
            if isinstance(tool_state, dict)
            else {}
        )
        limits = (
            tool_state.setdefault("tool_call_limits", {})
            if isinstance(tool_state, dict)
            else {}
        )
        counts["search_schema"] = int(counts.get("search_schema") or 0) + 1
        if int(limits.get("search_schema") or 0) and counts["search_schema"] > int(
            limits["search_schema"]
        ):
            msg = (
                "search_schema call limit reached. Use the best matching tables already identified, "
                "or call get_table_info on a specific table name."
            )
            cache[cache_key] = msg
            return msg

        _status(f"Searching schema for: {kw}...")
        start = time.time()
        keyword_lower = kw.lower()

        try:
            from sqlalchemy import text

            with db._engine.connect() as conn:
                # MSSQL: information_schema scan can be slow on large catalogs; use sys tables + TOP.
                if "mssql" in db._engine.url.drivername:
                    schema = db._schema or "dbo"
                    query = text(
                        """
                        SELECT TOP 600
                               t.name  AS table_name,
                               c.name  AS column_name,
                               ty.name AS data_type
                        FROM sys.tables t
                        JOIN sys.schemas s ON t.schema_id = s.schema_id
                        JOIN sys.columns c ON t.object_id = c.object_id
                        JOIN sys.types ty ON c.user_type_id = ty.user_type_id
                        WHERE s.name = :schema
                          AND (LOWER(t.name) LIKE :kw OR LOWER(c.name) LIKE :kw)
                        ORDER BY t.name
                        """
                    )
                    res = conn.execute(
                        query, {"kw": f"%{keyword_lower}%", "schema": schema}
                    )
                    rows = res.fetchall()
                else:
                    # Other dialects: information_schema is fine, but still cap rows.
                    query = text(
                        """
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE (LOWER(table_name) LIKE :kw OR LOWER(column_name) LIKE :kw)
                          AND table_schema = :schema
                        ORDER BY table_name
                        """
                    )
                    schema = db._schema or (
                        "public" if db._engine.dialect.name == "postgresql" else "dbo"
                    )
                    res = conn.execute(
                        query, {"kw": f"%{keyword_lower}%", "schema": schema}
                    )
                    rows = res.fetchmany(1200)

            if not rows:
                result = f"No tables or columns found matching '{kw}'"
                cache[cache_key] = result
                return result

            # Group by table
            tables_map = {}
            for t_name, c_name, c_type in rows:
                if t_name not in usable_tables:
                    continue
                if t_name not in tables_map:
                    tables_map[t_name] = []
                tables_map[t_name].append(f"{c_name} ({c_type})")

            if not tables_map:
                result = f"No usable tables found matching '{kw}'"
                cache[cache_key] = result
                return result

            matching_tables = list(tables_map.keys())
            result_lines = [f"Found {len(matching_tables)} matching tables:", ""]

            for t_name, cols in tables_map.items():
                col_str = ", ".join(cols[:10])
                if len(cols) > 10:
                    col_str += f" ... and {len(cols) - 10} more"
                result_lines.append(f"  {t_name}:")
                result_lines.append(f"    {col_str}")

            if not matching_tables:
                result = f"No tables or columns found matching '{kw}'"
                cache[cache_key] = result
                return result

            result = "\n".join(result_lines)

            elapsed = round((time.time() - start) * 1000, 2)
            logger.info(
                "Tool: search_schema",
                extra={
                    **_ctx,
                    "keyword": kw,
                    "matches": len(matching_tables),
                    "matched_tables": matching_tables,
                    "time_ms": elapsed,
                },
            )

            _status(f"Found {len(matching_tables)} relevant tables")
            cache[cache_key] = result
            return result
        except Exception as e:
            logger.error(
                "search_schema failed",
                extra={**_ctx, "keyword": keyword, "error": str(e)},
            )
            result = f"Error searching schema: {str(e)}"
            cache[cache_key] = result
            return result

    return search_schema
