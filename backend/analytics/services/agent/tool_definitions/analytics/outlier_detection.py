"""
Outlier Detection Tool - Find statistical outliers in data.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_outlier_detection_tool(db, ctx, _status, _ctx, _full_table, _quote_ident):
    """Factory to create the detect_outliers tool."""

    @tool
    def detect_outliers(table_name: str, column_name: str, method: str = "iqr") -> str:
        """
        Detect outliers in a numeric column using statistical methods.

        Parameters:
        - table_name: The table to analyze
        - column_name: The numeric column to check for outliers
        - method: Detection method - 'iqr' (Interquartile Range) or 'zscore'

        IQR Method: Values outside Q1-1.5*IQR to Q3+1.5*IQR are outliers
        Z-Score Method: Values with |z-score| > 3 are outliers

        Returns outlier count, examples, and statistics.
        """
        _status(f"Detecting outliers: {table_name}.{column_name}...")
        start = time.time()
        table_name = table_name.strip()
        column_name = column_name.strip()

        try:
            full_table = _full_table(table_name)
            quoted_col = _quote_ident(column_name)

            with db._engine.connect() as conn:
                # Get basic stats
                stats_sql = f"""
                    SELECT 
                        COUNT(*) as total,
                        AVG({quoted_col}) as mean,
                        STDDEV_POP({quoted_col}) as stddev,
                        MIN({quoted_col}) as min_val,
                        MAX({quoted_col}) as max_val,
                        PERCENTILE_CONT(0.25) WITHIN GROUP(ORDER BY {quoted_col}) as q1,
                        PERCENTILE_CONT(0.75) WITHIN GROUP(ORDER BY {quoted_col}) as q3
                    FROM {full_table}
                    WHERE {quoted_col} IS NOT NULL
                """

                stats_result = conn.execute(text(stats_sql))
                stats = stats_result.fetchone()

                if not stats or stats[0] == 0:
                    return f"No data in column {column_name}"

                total, mean, stddev, min_val, max_val, q1, q3 = stats

                if method == "iqr":
                    iqr = q3 - q1
                    lower_bound = q1 - 1.5 * iqr
                    upper_bound = q3 + 1.5 * iqr

                    # Count outliers
                    outlier_sql = f"""
                        SELECT COUNT(*) FROM {full_table}
                        WHERE {quoted_col} IS NOT NULL
                        AND ({quoted_col} < {lower_bound} OR {quoted_col} > {upper_bound})
                    """
                else:  # zscore
                    z_threshold = 3
                    lower_bound = mean - z_threshold * stddev
                    upper_bound = mean + z_threshold * stddev

                    outlier_sql = f"""
                        SELECT COUNT(*) FROM {full_table}
                        WHERE {quoted_col} IS NOT NULL
                        AND (ABS({quoted_col} - {mean}) / NULLIF({stddev}, 0) > {z_threshold})
                    """

                outlier_result = conn.execute(text(outlier_sql))
                outlier_count = outlier_result.scalar() or 0

                # Get outlier examples
                example_sql = f"""
                    SELECT {quoted_col} FROM {full_table}
                    WHERE {quoted_col} IS NOT NULL
                    AND ({quoted_col} < {lower_bound} OR {quoted_col} > {upper_bound})
                    ORDER BY {quoted_col}
                    LIMIT 10
                """

                example_result = conn.execute(text(example_sql))
                outlier_examples = [r[0] for r in example_result.fetchall()]

                # Calculate percentages
                outlier_pct = (outlier_count / total * 100) if total > 0 else 0

                # Build output
                lines = [
                    f"Outlier Detection: {table_name}.{column_name}",
                    f"Method: {method.upper()}",
                    "",
                    "Statistics:",
                    f"  Total rows: {total:,}",
                    f"  Mean: {mean:,.2f}",
                    f"  Std Dev: {stddev:,.2f}",
                    f"  Min: {min_val:,.2f}",
                    f"  Max: {max_val:,.2f}",
                    f"  Q1 (25th): {q1:,.2f}",
                    f"  Q3 (75th): {q3:,.2f}",
                ]

                if method == "iqr":
                    lines.extend(
                        [
                            "",
                            "IQR Method:",
                            f"  IQR: {iqr:,.2f}",
                            f"  Lower bound: {lower_bound:,.2f}",
                            f"  Upper bound: {upper_bound:,.2f}",
                        ]
                    )
                else:
                    lines.extend(
                        [
                            "",
                            "Z-Score Method:",
                            f"  Lower bound: {lower_bound:,.2f}",
                            f"  Upper bound: {upper_bound:,.2f}",
                        ]
                    )

                lines.extend(
                    [
                        "",
                        "Results:",
                        f"  Outliers found: {outlier_count:,} ({outlier_pct:.2f}%)",
                    ]
                )

                if outlier_examples:
                    lines.append(f"  Example outlier values: {outlier_examples[:10]}")
                else:
                    lines.append("  No outliers detected")

                # Interpretation
                if outlier_pct > 10:
                    lines.extend(
                        [
                            "",
                            "WARNING: High outlier percentage may indicate data quality issues.",
                        ]
                    )
                elif outlier_pct > 5:
                    lines.extend(
                        ["", "Note: Moderate outlier percentage, worth investigating."]
                    )
                else:
                    lines.extend(
                        ["", "OK: Low outlier percentage indicates clean data."]
                    )

                elapsed = round((time.time() - start) * 1000, 2)
                logger.info(
                    "Tool: detect_outliers",
                    extra={
                        **_ctx,
                        "table": table_name,
                        "column": column_name,
                        "outliers": outlier_count,
                        "time_ms": elapsed,
                    },
                )

                return "\n".join(lines)

        except Exception as e:
            logger.error(
                "detect_outliers failed",
                extra={
                    **_ctx,
                    "table": table_name,
                    "column": column_name,
                    "error": str(e),
                },
            )
            return f"Error detecting outliers: {str(e)}"

    return detect_outliers

