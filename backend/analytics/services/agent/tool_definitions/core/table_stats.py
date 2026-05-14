"""
Table Stats Tool - Get statistical overview of a table.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_table_stats_tool(
    db, tool_state, ctx, _status, _ctx, _full_table, _quote_ident
):
    """Factory to create the get_table_stats tool."""

    @tool
    def get_table_stats(table_name: str) -> str:
        """
        Get statistical overview of a table: total row count, and for each column:
        null count, distinct value count, and data type.
        Use this to understand data quality, volume, and what columns contain
        before writing analytical queries.
        """
        tname = (table_name or "").strip()
        cache_key = (
            "get_table_stats",
            (getattr(db, "_schema", "") or "").lower(),
            tname.lower(),
        )
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
        counts["get_table_stats"] = int(counts.get("get_table_stats") or 0) + 1
        if int(limits.get("get_table_stats") or 0) and counts["get_table_stats"] > int(
            limits["get_table_stats"]
        ):
            msg = "get_table_stats call limit reached. Proceed using table schema and a targeted SELECT with LIMIT."
            cache[cache_key] = msg
            return msg

        _status(f"Analyzing table statistics: {tname}...")
        start = time.time()
        table_name = tname

        try:
            full_table = _full_table(table_name)

            with db._engine.connect() as conn:
                # Get row count (avoid COUNT(*) on MSSQL; it's slow on large tables)
                total_rows = None
                approximate = False
                try:
                    if "mssql" in db._engine.url.drivername:
                        approximate = True
                        schema = db._schema or "dbo"
                        rc = conn.execute(
                            text(
                                """
                                SELECT SUM(p.row_count) AS row_count
                                FROM sys.dm_db_partition_stats p
                                JOIN sys.objects o ON p.object_id = o.object_id
                                JOIN sys.schemas s ON o.schema_id = s.schema_id
                                WHERE o.type = 'U'
                                  AND o.name = :table
                                  AND s.name = :schema
                                  AND p.index_id IN (0, 1)
                                """
                            ),
                            {"table": table_name, "schema": schema},
                        ).scalar()
                        total_rows = int(rc or 0)
                    else:
                        count_result = conn.execute(
                            text(f"SELECT COUNT(*) FROM {full_table}")
                        )
                        total_rows = int(count_result.scalar() or 0)
                except Exception:
                    # Final fallback: try COUNT(*)
                    count_result = conn.execute(
                        text(f"SELECT COUNT(*) FROM {full_table}")
                    )
                    total_rows = int(count_result.scalar() or 0)
                    approximate = False

                # Get column info with null counts and distinct counts
                row_line = f"Total Rows: {total_rows}"
                if approximate:
                    row_line += " (approx.)"
                stats_lines = [f"Table: {table_name}", row_line, ""]

                # Get columns
                columns_result = conn.execute(
                    text(f"""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns 
                    WHERE table_name = :table AND table_schema = :schema
                """),
                    {"table": table_name, "schema": db._schema or "public"},
                )

                columns_info = list(columns_result.fetchall())

                # To avoid massive performance issues on large tables, we only do a basic row count
                # and return the schema info, instead of doing COUNT(DISTINCT) on every column.

                for col_name, data_type, is_nullable in columns_info:
                    nullable_str = "nullable" if is_nullable == "YES" else "not null"
                    stats_lines.append(f"  {col_name}: {data_type} ({nullable_str})")

            elapsed_ms = round((time.time() - start) * 1000, 2)
            logger.info(
                "Tool: get_table_stats",
                extra={
                    **_ctx,
                    "table": table_name,
                    "rows": total_rows,
                    "time_ms": elapsed_ms,
                },
            )

            result = "\n".join(stats_lines)
            cache[cache_key] = result
            return result

        except Exception as e:
            logger.error(
                "get_table_stats failed",
                extra={
                    **_ctx,
                    "table": table_name,
                    "error": str(e),
                },
            )
            result = f"Error getting stats for {table_name}: {str(e)}"
            cache[cache_key] = result
            return result

    return get_table_stats

