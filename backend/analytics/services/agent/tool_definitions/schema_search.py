"""
Schema Search Tool - Search tables/columns by keyword.
"""

import time

from langchain.tools import tool
from sqlalchemy import inspect

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_schema_search_tool(db, usable_tables, ctx, _status, _ctx):
    """Factory to create the search_schema tool."""

    @tool
    def search_schema(keyword: str) -> str:
        """
        Search for tables and columns by keyword.
        Use this when you don't know the exact table name but have a general idea.
        Returns matching table names and their column names.
        """
        _status(f"Searching schema for: {keyword}...")
        start = time.time()
        keyword_lower = keyword.lower()
        
        try:
            from sqlalchemy import text
            
            # Use direct SQL for efficiency - search both table and column names
            query = text("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns 
                WHERE (LOWER(table_name) LIKE :kw OR LOWER(column_name) LIKE :kw)
                AND table_schema = :schema
                ORDER BY table_name
            """)
            
            with db._engine.connect() as conn:
                res = conn.execute(query, {
                    "kw": f"%{keyword_lower}%",
                    "schema": db._schema or ("public" if db._engine.dialect.name == "postgresql" else "dbo")
                })
                rows = res.fetchall()

            if not rows:
                return f"No tables or columns found matching '{keyword}'"

            # Group by table
            tables_map = {}
            for t_name, c_name, c_type in rows:
                if t_name not in usable_tables: continue
                if t_name not in tables_map: tables_map[t_name] = []
                tables_map[t_name].append(f"{c_name} ({c_type})")

            if not tables_map:
                return f"No usable tables found matching '{keyword}'"

            matching_tables = list(tables_map.keys())
            result_lines = [f"Found {len(matching_tables)} matching tables:", ""]
            
            for t_name, cols in tables_map.items():
                col_str = ", ".join(cols[:10])
                if len(cols) > 10:
                    col_str += f" ... and {len(cols)-10} more"
                result_lines.append(f"  {t_name}:")
                result_lines.append(f"    {col_str}")
            
            if not matching_tables:
                return f"No tables or columns found matching '{keyword}'"
            
            result = "\n".join(result_lines)
            
            elapsed = round((time.time() - start) * 1000, 2)
            logger.info("Tool: search_schema", extra={
                **_ctx, "keyword": keyword, "matches": len(matching_tables),
                "matched_tables": matching_tables, "time_ms": elapsed,
            })
            
            _status(f"Found {len(matching_tables)} relevant tables")
            return result
        except Exception as e:
            logger.error("search_schema failed", extra={**_ctx, "keyword": keyword, "error": str(e)})
            return f"Error searching schema: {str(e)}"

    return search_schema