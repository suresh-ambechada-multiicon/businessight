"""
Correlation Detection Tool - Find correlations between numeric columns.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_correlation_tool(db, ctx, _status, _ctx, _full_table, _quote_ident):
    """Factory to create the find_correlations tool."""

    @tool
    def find_correlations(table_name: str, sample_size: int = 1000) -> str:
        """
        Find correlations between numeric columns in a table.

        Parameters:
        - table_name: The table to analyze
        - sample_size: Number of rows to sample for analysis (default 1000)

        Returns correlation matrix and identified strong correlations.
        """
        _status(f"Finding correlations: {table_name}...")
        start = time.time()
        table_name = table_name.strip()
        sample_size = min(sample_size, 10000)

        try:
            full_table = _full_table(table_name)

            with db._engine.connect() as conn:
                # Get numeric columns
                numeric_result = conn.execute(
                    text(f"""
                    SELECT column_name, data_type
                    FROM information_schema.columns 
                    WHERE table_name = :table 
                    AND table_schema = :schema
                    AND data_type IN ('integer', 'bigint', 'smallint', 'decimal', 'numeric', 'real', 'double precision')
                """),
                    {"table": table_name, "schema": db._schema or "public"},
                )

                numeric_cols = [r[0] for r in numeric_result.fetchall()]

                if len(numeric_cols) < 2:
                    return (
                        f"Need at least 2 numeric columns. Found: {len(numeric_cols)}"
                    )

                # Sample data for correlation
                sample_sql = f"""
                    SELECT {", ".join([_quote_ident(c) for c in numeric_cols])}
                    FROM {full_table}
                    WHERE {" AND ".join([f"{_quote_ident(c)} IS NOT NULL" for c in numeric_cols])}
                    LIMIT {sample_size}
                """

                sample_result = conn.execute(text(sample_sql))
                sample_data = sample_result.fetchall()

                if len(sample_data) < 10:
                    return f"Not enough data for correlation analysis. Sample size: {len(sample_data)}"

                # Calculate correlation matrix manually
                n = len(sample_data)
                means = {}
                for i, col in enumerate(numeric_cols):
                    values = [row[i] for row in sample_data if row[i] is not None]
                    means[col] = sum(values) / len(values) if values else 0

                # Calculate Pearson correlation
                correlations = []
                for i, col1 in enumerate(numeric_cols):
                    for j, col2 in enumerate(numeric_cols):
                        if i >= j:
                            continue

                        # Get paired values
                        pairs = [
                            (row[i], row[j])
                            for row in sample_data
                            if row[i] is not None and row[j] is not None
                        ]

                        if len(pairs) < 10:
                            continue

                        # Calculate correlation
                        mean1 = means[col1]
                        mean2 = means[col2]

                        numerator = sum((p[0] - mean1) * (p[1] - mean2) for p in pairs)
                        denom1 = sum((p[0] - mean1) ** 2 for p in pairs) ** 0.5
                        denom2 = sum((p[1] - mean2) ** 2 for p in pairs) ** 0.5

                        if denom1 > 0 and denom2 > 0:
                            corr = numerator / (denom1 * denom2)
                            correlations.append((col1, col2, corr, len(pairs)))

                # Sort by absolute correlation
                correlations.sort(key=lambda x: abs(x[2]), reverse=True)

                # Build output
                lines = [
                    f"Correlation Analysis: {table_name}",
                    f"Columns analyzed: {len(numeric_cols)}",
                    f"Sample size: {len(sample_data)} rows",
                    "",
                    "Correlation Matrix (top pairs):",
                ]

                # Strong correlations
                strong = [
                    (c1, c2, corr, n)
                    for c1, c2, corr, n in correlations
                    if abs(corr) > 0.5
                ]
                moderate = [
                    (c1, c2, corr, n)
                    for c1, c2, corr, n in correlations
                    if 0.3 < abs(corr) <= 0.5
                ]

                if strong:
                    lines.extend(["", "Strong Correlations (|r| > 0.5):"])
                    for c1, c2, corr, n in strong[:10]:
                        strength = "positive" if corr > 0 else "negative"
                        lines.append(
                            f"  {c1} <-> {c2}: {corr:+.3f} ({strength}, {n} pairs)"
                        )

                if moderate:
                    lines.extend(["", "Moderate Correlations (0.3 < |r| <= 0.5):"])
                    for c1, c2, corr, n in moderate[:10]:
                        strength = "positive" if corr > 0 else "negative"
                        lines.append(
                            f"  {c1} <-> {c2}: {corr:+.3f} ({strength}, {n} pairs)"
                        )

                if not strong and not moderate:
                    lines.extend(["", "No significant correlations found."])

                # Show all correlations as matrix
                lines.extend(["", "All Correlations:"])
                for c1, c2, corr, n in correlations[:15]:
                    lines.append(f"  {c1} vs {c2}: {corr:+.4f}")

                elapsed = round((time.time() - start) * 1000, 2)
                logger.info(
                    "Tool: find_correlations",
                    extra={
                        **_ctx,
                        "table": table_name,
                        "pairs": len(correlations),
                        "time_ms": elapsed,
                    },
                )

                return "\n".join(lines)

        except Exception as e:
            logger.error(
                "find_correlations failed",
                extra={**_ctx, "table": table_name, "error": str(e)},
            )
            return f"Error finding correlations: {str(e)}"

    return find_correlations

