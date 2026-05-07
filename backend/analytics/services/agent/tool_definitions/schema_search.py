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
            inspector = inspect(db._schema if db._schema else db._engine)
            matching_tables = []
            
            for table_name in usable_tables:
                if keyword_lower in table_name.lower():
                    matching_tables.append(table_name)
                    continue
                    
                # Check columns
                try:
                    columns = inspector.get_columns(table_name, schema=db._schema)
                    for col in columns:
                        if keyword_lower in col["name"].lower():
                            matching_tables.append(table_name)
                            break
                except:
                    pass
            
            if not matching_tables:
                return f"No tables or columns found matching '{keyword}'"
            
            # Get column info for matching tables
            result_lines = [f"Found {len(matching_tables)} matching tables:", ""]
            
            for table_name in matching_tables:
                try:
                    columns = inspector.get_columns(table_name, schema=db._schema)
                    col_names = [f"{c['name']}: {c['type']}" for c in columns[:10]]
                    if len(columns) > 10:
                        col_names.append(f"... and {len(columns) - 10} more columns")
                    result_lines.append(f"  {table_name}:")
                    result_lines.append(f"    {', '.join(col_names)}")
                except Exception as e:
                    result_lines.append(f"  {table_name}: Error - {str(e)}")
            
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