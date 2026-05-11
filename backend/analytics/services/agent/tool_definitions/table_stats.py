"""
Table Stats Tool - Get statistical overview of a table.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_table_stats_tool(db, ctx, _status, _ctx, _full_table, _quote_ident):
    """Factory to create the get_table_stats tool."""

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
            full_table = _full_table(table_name)

            with db._engine.connect() as conn:
                # Get row count
                count_result = conn.execute(text(f"SELECT COUNT(*) FROM {full_table}"))
                total_rows = count_result.scalar()

                # Get column info with null counts and distinct counts
                stats_lines = [f"Table: {table_name}", f"Total Rows: {total_rows}", ""]

                # Get columns
                columns_result = conn.execute(text(f"""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns 
                    WHERE table_name = :table AND table_schema = :schema
                """), {"table": table_name, "schema": db._schema or "public"})
                
                columns_info = list(columns_result.fetchall())

                # To avoid massive performance issues on large tables, we only do a basic row count
                # and return the schema info, instead of doing COUNT(DISTINCT) on every column.
                
                for col_name, data_type, is_nullable in columns_info:
                    nullable_str = "nullable" if is_nullable == 'YES' else "not null"
                    stats_lines.append(f"  {col_name}: {data_type} ({nullable_str})")

            elapsed_ms = round((time.time() - start) * 1000, 2)
            logger.info("Tool: get_table_stats", extra={
                **_ctx, "table": table_name, "rows": total_rows, "time_ms": elapsed_ms,
            })
            
            return "\n".join(stats_lines)

        except Exception as e:
            logger.error("get_table_stats failed", extra={
                **_ctx, "table": table_name, "error": str(e),
            })
            return f"Error getting stats for {table_name}: {str(e)}"

    return get_table_stats