"""
Trend Analysis Tool - Analyze time-series trends in data.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_trend_analysis_tool(
    db, ctx, _status, _ctx, _full_table, _quote_ident, _select_top
):
    """Factory to create the analyze_trends tool."""

    @tool
    def analyze_trends(
        table_name: str, date_column: str, value_column: str, period: str = "day"
    ) -> str:
        """
        Analyze time-series trends in a table.

        Parameters:
        - table_name: The table to analyze
        - date_column: The column containing date/time values
        - value_column: The numeric column to analyze trends
        - period: Aggregation period - 'day', 'week', 'month', 'quarter', 'year'

        Returns trend analysis including:
        - Period-over-period comparison
        - Growth/decline rates
        - Peak and low periods
        - Simple moving averages
        """
        _status(f"Analyzing trends: {table_name}.{value_column}...")
        start = time.time()
        table_name = table_name.strip()
        date_column = date_column.strip()
        value_column = value_column.strip()

        try:
            full_table = _full_table(table_name)
            quoted_date = _quote_ident(date_column)
            quoted_value = _quote_ident(value_column)

            # Map period to SQL
            period_map = {
                "day": "DATE_TRUNC('day', {date_col})",
                "week": "DATE_TRUNC('week', {date_col})",
                "month": "DATE_TRUNC('month', {date_col})",
                "quarter": "DATE_TRUNC('quarter', {date_col})",
                "year": "DATE_TRUNC('year', {date_col})",
            }
            date_trunc = period_map.get(period, period_map["day"]).format(
                date_col=quoted_date
            )

            with db._engine.connect() as conn:
                # Get date range
                range_result = conn.execute(
                    text(f"""
                    SELECT MIN({quoted_date}), MAX({quoted_date}), COUNT(*)
                    FROM {full_table}
                    WHERE {quoted_date} IS NOT NULL AND {quoted_value} IS NOT NULL
                """)
                )
                min_date, max_date, total_rows = range_result.fetchone()

                if not min_date or not max_date:
                    return f"No valid date data found in {date_column}"

                # Get aggregated trend data
                trend_sql = f"""
                    SELECT {date_trunc} as period,
                           SUM({quoted_value}) as total,
                           AVG({quoted_value}) as average,
                           COUNT(*) as count
                    FROM {full_table}
                    WHERE {quoted_date} IS NOT NULL AND {quoted_value} IS NOT NULL
                    GROUP BY {date_trunc}
                    ORDER BY period
                """

                trend_result = conn.execute(text(trend_sql))
                trend_data = list(trend_result.fetchall())

                if not trend_data:
                    return f"No trend data available for {value_column}"

                # Calculate statistics
                totals = [r[1] for r in trend_data if r[1] is not None]
                averages = [r[2] for r in trend_data if r[2] is not None]

                if not totals:
                    return f"No numeric data found in {value_column}"

                current_total = totals[-1] if totals else 0
                previous_total = totals[-2] if len(totals) > 1 else 0
                first_total = totals[0] if totals else 0

                # Calculate growth rates
                period_growth = (
                    ((current_total - previous_total) / previous_total * 100)
                    if previous_total
                    else 0
                )
                overall_growth = (
                    ((current_total - first_total) / first_total * 100)
                    if first_total
                    else 0
                )

                # Find peak and low
                max_idx = totals.index(max(totals))
                min_idx = totals.index(min(totals))
                peak_period = trend_data[max_idx][0]
                low_period = trend_data[min_idx][0]

                # Calculate simple moving average (last 3 periods)
                last_3_avg = (
                    sum(totals[-3:]) / min(3, len(totals))
                    if len(totals) >= 3
                    else sum(totals) / len(totals)
                )

                # Determine trend direction
                if period_growth > 5:
                    trend_direction = "UPWARD"
                elif period_growth < -5:
                    trend_direction = "DOWNWARD"
                else:
                    trend_direction = "STABLE"

                # Build report
                lines = [
                    f"Trend Analysis: {table_name}",
                    f"  Value Column: {value_column}",
                    f"  Date Column: {date_column}",
                    f"  Period: {period}",
                    "",
                    f"Date Range: {min_date.date()} to {max_date.date()}",
                    f"Data Points: {len(trend_data)}",
                    "",
                    "Statistics:",
                    f"  Current Period Total: {current_total:,.2f}",
                    f"  Previous Period Total: {previous_total:,.2f}",
                    f"  First Period Total: {first_total:,.2f}",
                    f"  Average per Period: {sum(totals) / len(totals):,.2f}",
                    f"  Moving Avg (last 3): {last_3_avg:,.2f}",
                    "",
                    f"Trend: {trend_direction}",
                    f"  Period-over-Period: {period_growth:+.2f}%",
                    f"  Overall: {overall_growth:+.2f}%",
                    "",
                    "Extreme Periods:",
                    f"  Peak: {peak_period} ({max(totals):,.2f})",
                    f"  Low: {low_period} ({min(totals):,.2f})",
                ]

                # Show last few periods
                lines.extend(["", "Recent Data:"])
                for period_date, total, avg, count in trend_data[-5:]:
                    lines.append(
                        f"  {period_date}: {total:,.2f} (avg: {avg:,.2f}, count: {count})"
                    )

                elapsed = round((time.time() - start) * 1000, 2)
                logger.info(
                    "Tool: analyze_trends",
                    extra={
                        **_ctx,
                        "table": table_name,
                        "trend": trend_direction,
                        "time_ms": elapsed,
                    },
                )

                return "\n".join(lines)

        except Exception as e:
            logger.error(
                "analyze_trends failed",
                extra={**_ctx, "table": table_name, "error": str(e)},
            )
            return f"Error analyzing trends: {str(e)}"

    return analyze_trends

