"""
Aggregation Tool - Perform GROUP BY analytics.
"""

import time

from langchain.tools import tool
from sqlalchemy import text

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_aggregation_tool(db, ctx, _status, _ctx, _full_table, _quote_ident, _select_top):
    """Factory to create the aggregate_data tool."""

    @tool
    def aggregate_data(table_name: str, group_by: str, 
                       metrics: str = "count", limit: int = 20) -> str:
        """
        Perform aggregation queries on a table.
        
        Parameters:
        - table_name: The table to aggregate
        - group_by: Comma-separated columns to group by (e.g., 'category, status')
        - metrics: Comma-separated metrics to calculate:
          - count, sum, avg, min, max, stddev, variance
        - limit: Maximum number of groups to return (default 20)
        
        Returns aggregated data with counts, sums, averages, etc.
        """
        _status(f"Aggregating: {table_name} by {group_by}...")
        start = time.time()
        table_name = table_name.strip()
        group_by = group_by.strip()
        limit = min(limit, 100)

        try:
            full_table = _full_table(table_name)
            group_cols = [c.strip() for c in group_by.split(",")]
            
            with db._engine.connect() as conn:
                # Validate columns exist
                cols_result = conn.execute(text(f"""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = :table AND table_schema = :schema
                """), {"table": table_name, "schema": db._schema or "public"})
                valid_cols = {r[0] for r in cols_result.fetchall()}
                
                invalid_cols = [c for c in group_cols if c not in valid_cols]
                if invalid_cols:
                    return f"Invalid columns: {', '.join(invalid_cols)}. Valid: {', '.join(valid_cols)}"
                
                quoted_groups = [_quote_ident(c) for c in group_cols]
                group_sql = ", ".join(quoted_groups)
                
                # Parse metrics
                metric_funcs = []
                for m in metrics.split(","):
                    m = m.strip().lower()
                    if m == "count":
                        metric_funcs.append(("count", "COUNT(*)"))
                    elif m == "sum":
                        metric_funcs.append(("sum", "SUM({col})"))
                    elif m in ("avg", "average"):
                        metric_funcs.append(("avg", "AVG({col})"))
                    elif m == "min":
                        metric_funcs.append(("min", "MIN({col})"))
                    elif m == "max":
                        metric_funcs.append(("max", "MAX({col})"))
                    elif m == "stddev":
                        metric_funcs.append(("stddev", "STDDEV_POP({col})"))
                    elif m == "variance":
                        metric_funcs.append(("variance", "VAR_POP({col})"))
                
                if not metric_funcs:
                    return f"Invalid metrics: {metrics}. Use: count, sum, avg, min, max, stddev, variance"
                
                # Get first numeric column
                numeric_result = conn.execute(text(f"""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = :table AND table_schema = :schema
                    AND data_type IN ('integer', 'bigint', 'smallint', 'decimal', 'numeric', 'real', 'double precision')
                """), {"table": table_name, "schema": db._schema or "public"})
                numeric_cols = [r[0] for r in numeric_result.fetchall()]
                
                metric_sql_parts = []
                for name, template in metric_funcs:
                    if name == "count":
                        metric_sql_parts.append(f"COUNT(*) as {name}")
                    elif numeric_cols:
                        col = numeric_cols[0]
                        metric_sql_parts.append(template.format(col=_quote_ident(col)) + f" as {name}")
                    else:
                        metric_sql_parts.append(f"COUNT(*) as {name}")
                
                metric_sql = ", ".join(metric_sql_parts)
                
                sql = f"""
                    SELECT {group_sql}, {metric_sql}
                    FROM {full_table}
                    GROUP BY {group_sql}
                    ORDER BY COUNT(*) DESC
                    LIMIT {limit}
                """
                
                result = conn.execute(text(sql))
                rows = result.fetchall()
                
                if not rows:
                    return f"No aggregation results for {group_by}"
                
                cols = result.keys()
                
                lines = [
                    f"Aggregation Results: {table_name}",
                    f"Grouped by: {group_by}",
                    f"Metrics: {metrics}",
                    f"Results: {len(rows)} groups",
                    "",
                ]
                
                header = " | ".join([f"{c:>15}" for c in cols])
                lines.append(header)
                lines.append("-" * len(header))
                
                for row in rows:
                    row_str = " | ".join([f"{str(v):>15}" for v in row])
                    lines.append(row_str)
                
                if "count" in [m[0] for m in metric_funcs]:
                    counts = [r[cols.index("count")] for r in rows]
                    lines.extend(["", f"Total groups: {len(rows)}", f"Total count: {sum(counts):,}"])
                
                elapsed = round((time.time() - start) * 1000, 2)
                logger.info("Tool: aggregate_data", extra={**_ctx, "table": table_name, "groups": len(rows), "time_ms": elapsed})
                
                return "\n".join(lines)

        except Exception as e:
            logger.error("aggregate_data failed", extra={**_ctx, "table": table_name, "error": str(e)})
            return f"Error aggregating data: {str(e)}"

    return aggregate_data