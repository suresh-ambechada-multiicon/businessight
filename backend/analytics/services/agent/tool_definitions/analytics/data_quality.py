"""
Data Quality Analysis Tool - Analyze data quality issues.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_data_quality_tool(db, ctx, _status, _ctx, _full_table, _quote_ident):
    """Factory to create the analyze_data_quality tool."""

    @tool
    def analyze_data_quality(table_name: str) -> str:
        """
        Analyze data quality for a table.
        Checks for: null percentages, duplicate rows, empty strings,
        data type consistency, and unique constraints.
        Returns a comprehensive data quality report.
        """
        _status(f"Analyzing data quality: {table_name}...")
        start = time.time()
        table_name = table_name.strip()

        try:
            full_table = _full_table(table_name)

            with db._engine.connect() as conn:
                # Get total rows
                total_result = conn.execute(text(f"SELECT COUNT(*) FROM {full_table}"))
                total_rows = total_result.scalar()

                if total_rows == 0:
                    return f"Table {table_name} is empty (0 rows)"

                # Get column info
                columns_result = conn.execute(
                    text(f"""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns 
                    WHERE table_name = :table AND table_schema = :schema
                """),
                    {"table": table_name, "schema": db._schema or "public"},
                )

                columns = list(columns_result.fetchall())

                quality_issues = []
                column_stats = []

                for col_name, data_type, is_nullable in columns:
                    quoted_col = _quote_ident(col_name)

                    # Null count
                    null_result = conn.execute(
                        text(f"""
                        SELECT COUNT(*) FROM {full_table} WHERE {quoted_col} IS NULL
                    """)
                    )
                    null_count = null_result.scalar()
                    null_pct = (null_count / total_rows * 100) if total_rows > 0 else 0

                    # Empty string count (for text columns)
                    empty_count = 0
                    if data_type.lower() in [
                        "character varying",
                        "varchar",
                        "text",
                        "char",
                    ]:
                        empty_result = conn.execute(
                            text(f"""
                            SELECT COUNT(*) FROM {full_table} 
                            WHERE {quoted_col} = '' OR {quoted_col} = ' '
                        """)
                        )
                        empty_count = empty_result.scalar()

                    # Distinct count
                    if total_rows > 10000:
                        distinct_count = -1  # Skip for large tables
                    else:
                        distinct_result = conn.execute(
                            text(
                                f"SELECT COUNT(DISTINCT {quoted_col}) FROM {full_table}"
                            )
                        )
                        distinct_count = distinct_result.scalar()

                    # Build column stats
                    issues = []
                    if null_pct > 10:
                        issues.append(f"High nulls ({null_pct:.1f}%)")
                    if empty_count > 0:
                        issues.append(f"Empty strings ({empty_count})")
                    if distinct_count == total_rows:
                        issues.append("Unique")
                    elif distinct_count == 1:
                        issues.append("Constant value")

                    status_icon = "[!]" if issues else "[OK]"
                    distinct_display = (
                        "skipped (large table)"
                        if distinct_count == -1
                        else distinct_count
                    )
                    col_info = f"  {status_icon} {col_name}: {data_type} | nulls: {null_count} ({null_pct:.1f}%) | distinct: {distinct_display}"
                    if issues:
                        col_info += f" | {' '.join(issues)}"
                        quality_issues.append(f"    - {col_name}: {', '.join(issues)}")

                    column_stats.append(col_info)

                # Check for duplicate rows
                if total_rows > 10000:
                    duplicate_rows = 0
                    quality_issues.append(
                        "    - Duplicate row check skipped due to large table size"
                    )
                else:
                    dup_result = conn.execute(
                        text(f"""
                        SELECT COUNT(*) FROM (
                            SELECT {", ".join([_quote_ident(c[0]) for c in columns])}
                            FROM {full_table}
                            GROUP BY {", ".join([_quote_ident(c[0]) for c in columns])}
                            HAVING COUNT(*) > 1
                        ) AS duplicates
                    """)
                    )
                    duplicate_rows = dup_result.scalar() or 0

                # Build report
                lines = [
                    f"Data Quality Report: {table_name}",
                    f"   Total Rows: {total_rows:,}",
                    f"   Columns: {len(columns)}",
                    "",
                    "Column Details:",
                    "\n".join(column_stats),
                ]

                if duplicate_rows > 0:
                    lines.extend(
                        [
                            "",
                            f"WARNING: Duplicate Rows: {duplicate_rows:,} ({(duplicate_rows / total_rows * 100):.2f}%)",
                        ]
                    )
                    quality_issues.append(
                        f"    - {duplicate_rows} duplicate rows found"
                    )

                if quality_issues:
                    lines.extend(["", "Summary Issues:"] + quality_issues)
                else:
                    lines.extend(
                        [
                            "",
                            "OK: Data quality looks good - no significant issues found",
                        ]
                    )

                elapsed = round((time.time() - start) * 1000, 2)
                logger.info(
                    "Tool: analyze_data_quality",
                    extra={
                        **_ctx,
                        "table": table_name,
                        "rows": total_rows,
                        "issues": len(quality_issues),
                        "time_ms": elapsed,
                    },
                )

                return "\n".join(lines)

        except Exception as e:
            logger.error(
                "analyze_data_quality failed",
                extra={**_ctx, "table": table_name, "error": str(e)},
            )
            return f"Error analyzing data quality: {str(e)}"

    return analyze_data_quality

