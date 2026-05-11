"""
Column Values Tool - Get distinct values and counts for a column.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_column_values_tool(db, ctx, _status, _ctx, _full_table, _quote_ident, _select_top):
    """Factory to create the get_column_values tool."""

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
            full_table = _full_table(table_name)
            quoted_col = _quote_ident(column_name)

            with db._engine.connect() as conn:
                sql = _select_top(
                    f"{quoted_col} as value, COUNT(*) as count",
                    full_table,
                    50,
                    f"GROUP BY {quoted_col} ORDER BY count DESC"
                )
                result = conn.execute(text(sql))
                rows = result.fetchall()

            lines = [f"Column: {table_name}.{column_name}", ""]
            
            for value, count in rows:
                display_val = str(value) if value is not None else "NULL"
                lines.append(f"  {display_val}: {count}")
            
            if len(rows) == 50:
                lines.append(f"  ... (showing top 50 of {len(rows)}+ values)")

            elapsed = round((time.time() - start) * 1000, 2)
            logger.info("Tool: get_column_values failed", extra={
                **_ctx, "table": table_name, "column": column_name, "time_ms": elapsed,
            })
            
            return "\n".join(lines)

        except Exception as e:
            logger.error("get_column_values failed", extra={
                **_ctx, "table": table_name, "column": column_name, "error": str(e),
            })
            return f"Error: {str(e)}"

    return get_column_values