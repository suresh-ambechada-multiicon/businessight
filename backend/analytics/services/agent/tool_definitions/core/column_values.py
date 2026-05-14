"""
Column Values Tool - Get distinct values and counts for a column.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_column_values_tool(
    db, tool_state, ctx, _status, _ctx, _full_table, _quote_ident, _select_top
):
    """Factory to create the get_column_values tool."""

    @tool
    def get_column_values(table_name: str, column_name: str) -> str:
        """
        Get distinct values and their counts for a specific column.
        Use this for flag, status, enum, boolean, or category columns
        to understand what values exist BEFORE writing analytical queries.
        Example: get_column_values('accounts', 'status') -> 'Active: 500, Inactive: 37'
        """
        table_name = table_name.strip()
        column_name = column_name.strip()
        cache_key = ("get_column_values", table_name.lower(), column_name.lower())
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
        counts["get_column_values"] = int(counts.get("get_column_values") or 0) + 1
        if int(limits.get("get_column_values") or 0) and counts[
            "get_column_values"
        ] > int(limits["get_column_values"]):
            msg = "get_column_values call limit reached. Use inspected values and proceed to final SQL."
            cache[cache_key] = msg
            return msg

        _status(f"Checking values in {table_name}.{column_name}...")
        start = time.time()

        try:
            full_table = _full_table(table_name)
            quoted_col = _quote_ident(column_name)

            with db._engine.connect() as conn:
                sql = _select_top(
                    f"{quoted_col} as value, COUNT(*) as count",
                    full_table,
                    50,
                    f"GROUP BY {quoted_col} ORDER BY count DESC",
                )
                result = conn.execute(text(sql))
                rows = result.fetchall()

            lines = [f"Column: {table_name}.{column_name}", ""]

            for value, count in rows:
                display_val = str(value) if value is not None else "NULL"
                lines.append(f"  {display_val}: {count}")

            if len(rows) == 50:
                lines.append(
                    "  ... (top 50 value groups; more distinct values may exist)"
                )

            elapsed = round((time.time() - start) * 1000, 2)
            logger.info(
                "Tool: get_column_values",
                extra={
                    **_ctx,
                    "table": table_name,
                    "column": column_name,
                    "distinct_values": len(rows),
                    "time_ms": elapsed,
                },
            )

            result_text = "\n".join(lines)
            cache[cache_key] = result_text
            return result_text

        except Exception as e:
            logger.error(
                "get_column_values failed",
                extra={
                    **_ctx,
                    "table": table_name,
                    "column": column_name,
                    "error": str(e),
                },
            )
            result_text = f"Error: {str(e)}"
            cache[cache_key] = result_text
            return result_text

    return get_column_values
