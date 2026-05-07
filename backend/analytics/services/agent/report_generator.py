"""
Professional Report Generator - Creates formatted analytical reports.
"""

from typing import Any


def generate_professional_report(
    query: str,
    raw_data: list[dict],
    sql_query: str,
    chart_config: dict = None,
    analysis_type: str = "general"
) -> str:
    """
    Generate a professional, formatted report from query results.
    
    Args:
        query: The original natural language query
        raw_data: List of dictionaries containing the query results
        sql_query: The SQL that was executed
        chart_config: Optional chart configuration
        analysis_type: Type of analysis - 'general', 'summary', 'comparison', 'trend', 'detailed'
    
    Returns:
        Formatted markdown report string
    """
    if not raw_data:
        return "No data available to generate report."
    
    # Detect analysis type if not specified
    if analysis_type == "general":
        analysis_type = detect_analysis_type(query, raw_data)
    
    # Generate based on analysis type
    if analysis_type == "summary":
        return generate_summary_report(query, raw_data, sql_query)
    elif analysis_type == "trend":
        return generate_trend_report(query, raw_data, sql_query)
    elif analysis_type == "comparison":
        return generate_comparison_report(query, raw_data, sql_query)
    elif analysis_type == "detailed":
        return generate_detailed_report(query, raw_data, sql_query)
    else:
        return generate_general_report(query, raw_data, sql_query)


def detect_analysis_type(query: str, data: list) -> str:
    """Detect the type of analysis from query and data."""
    query_lower = query.lower()
    
    # Check for trend/time-based queries
    if any(w in query_lower for w in ["trend", "over time", "growth", "daily", "monthly", "yearly", "period"]):
        return "trend"
    
    # Check for comparison queries
    if any(w in query_lower for w in ["compare", "versus", "vs", "difference", "between"]):
        return "comparison"
    
    # Check for summary queries
    if any(w in query_lower for w in ["total", "sum", "average", "count", "summary", "overview"]):
        return "summary"
    
    # Check for detailed/list queries
    if len(data) > 20:
        return "detailed"
    
    return "general"


def generate_summary_report(query: str, data: list, sql: str) -> str:
    """Generate a summary report with key statistics."""
    if not data:
        return "No data found."
    
    lines = [
        "# Query Summary Report",
        "",
        f"**Question:** {query}",
        "",
        "## Key Findings",
        "",
    ]
    
    # Calculate statistics for numeric columns
    numeric_cols = [k for k, v in data[0].items() if isinstance(v, (int, float))]
    
    if numeric_cols:
        for col in numeric_cols[:3]:
            values = [row[col] for row in data if row[col] is not None]
            if values:
                total = sum(values)
                avg = total / len(values)
                lines.extend([
                    f"### {col.title()}",
                    f"- **Total:** {total:,.2f}",
                    f"- **Average:** {avg:,.2f}",
                    f"- **Count:** {len(values)} records",
                    "",
                ])
    
    # Count records
    lines.extend([
        f"**Total Records:** {len(data)}",
        "",
    ])
    
    # Add data sample
    lines.extend([
        "## Data Sample",
        "",
        "```",
        str(data[:5]),
        "```",
        "",
        f"*SQL: {sql}*",
    ])
    
    return "\n".join(lines)


def generate_trend_report(query: str, data: list, sql: str) -> str:
    """Generate a trend analysis report."""
    if not data:
        return "No data found."
    
    lines = [
        "# Trend Analysis Report",
        "",
        f"**Question:** {query}",
        "",
        "## Trend Summary",
        "",
    ]
    
    # Try to find date/time column and value column
    date_col = None
    value_col = None
    
    for col in data[0].keys():
        col_lower = col.lower()
        if any(w in col_lower for w in ["date", "time", "period", "month", "year", "day"]):
            date_col = col
        elif isinstance(data[0][col], (int, float)):
            value_col = col
    
    if date_col and value_col:
        # Sort by date
        sorted_data = sorted(data, key=lambda x: x.get(date_col, ""))
        
        # Show trend direction
        if len(sorted_data) >= 2:
            first_val = sorted_data[0].get(value_col, 0) or 0
            last_val = sorted_data[-1].get(value_col, 0) or 0
            
            if last_val > first_val:
                direction = "increasing"
                change = ((last_val - first_val) / first_val * 100) if first_val else 0
            else:
                direction = "decreasing"
                change = ((first_val - last_val) / first_val * 100) if first_val else 0
            
            lines.extend([
                f"**Trend Direction:** {direction.title()}",
                f"**Change:** {change:+.1f}%",
                "",
                "## Period-by-Period Data",
                "",
            ])
            
            for row in sorted_data[-10:]:
                lines.append(f"- {row.get(date_col, 'N/A')}: {row.get(value_col, 0):,.2f}")
    
    lines.extend(["", f"*SQL: {sql}*"])
    
    return "\n".join(lines)


def generate_comparison_report(query: str, data: list, sql: str) -> str:
    """Generate a comparison report."""
    if not data:
        return "No data found."
    
    lines = [
        "# Comparison Report",
        "",
        f"**Question:** {query}",
        "",
        "## Comparison Summary",
        "",
    ]
    
    # Find categorical and numeric columns
    cat_cols = []
    num_cols = []
    
    for col in data[0].keys():
        if isinstance(data[0][col], (int, float)):
            num_cols.append(col)
        elif isinstance(data[0][col], str):
            cat_cols.append(col)
    
    if cat_cols and num_cols:
        group_col = cat_cols[0]
        value_col = num_cols[0]
        
        # Group by and sum
        groups = {}
        for row in data:
            key = row.get(group_col, "Unknown")
            val = row.get(value_col, 0) or 0
            groups[key] = groups.get(key, 0) + val
        
        # Sort by value
        sorted_groups = sorted(groups.items(), key=lambda x: x[1], reverse=True)
        
        lines.append(f"## {group_col.title()} Comparison by {value_col.title()}")
        lines.append("")
        
        for name, total in sorted_groups:
            lines.append(f"- **{name}:** {total:,.2f}")
        
        # Calculate percentages
        total_val = sum(groups.values())
        if total_val > 0:
            lines.append("")
            lines.append("### Percentage Distribution")
            for name, total in sorted_groups:
                pct = (total / total_val) * 100
                lines.append(f"- {name}: {pct:.1f}%")
    
    lines.extend(["", f"*SQL: {sql}*"])
    
    return "\n".join(lines)


def generate_detailed_report(query: str, data: list, sql: str) -> str:
    """Generate a detailed report with all records."""
    if not data:
        return "No data found."
    
    lines = [
        "# Detailed Report",
        "",
        f"**Question:** {query}",
        "",
        f"**Total Records:** {len(data)}",
        "",
    ]
    
    # Get columns
    columns = list(data[0].keys())
    
    # Show summary table
    lines.extend([
        "## Summary Table",
        "",
        "| " + " | ".join(columns[:5]) + " |",
        "| " + " | ".join(["---"] * min(5, len(columns))) + " |",
    ])
    
    for row in data[:20]:
        vals = [str(row.get(c, ""))[:20] for c in columns[:5]]
        lines.append("| " + " | ".join(vals) + " |")
    
    if len(data) > 20:
        lines.extend([
            "",
            f"*... and {len(data) - 20} more records*",
        ])
    
    lines.extend(["", f"*SQL: {sql}*"])
    
    return "\n".join(lines)


def generate_general_report(query: str, data: list, sql: str) -> str:
    """Generate a general analytical report."""
    if not data:
        return "No data found."
    
    lines = [
        "# Analytical Report",
        "",
        f"**Question:** {query}",
        "",
    ]
    
    # Basic count
    lines.extend([
        f"**Records Found:** {len(data)}",
        "",
    ])
    
    # Show columns
    columns = list(data[0].keys())
    lines.append(f"**Fields:** {', '.join(columns[:8])}")
    
    if len(columns) > 8:
        lines.append(f"  ... and {len(columns) - 8} more")
    
    lines.append("")
    
    # Show first few rows
    lines.extend([
        "## Sample Data",
        "",
        "```",
    ])
    
    for row in data[:5]:
        lines.append(str(row))
    
    lines.extend([
        "```",
        "",
        f"*SQL: {sql}*",
    ])
    
    return "\n".join(lines)


# Simple query handler for fast-path execution
def handle_simple_query(db, query: str, usable_tables: list) -> dict:
    """
    Handle simple queries directly without AI agent.
    
    Returns dict with report, data, and sql_query.
    """
    query_lower = query.lower().strip()
    
    from sqlalchemy import text
    
    # Show tables query
    if any(p in query_lower for p in ["show tables", "list tables", "what tables"]):
        tables = usable_tables if usable_tables else []
        
        # Try to get from database
        try:
            from sqlalchemy import inspect
            inspector = inspect(db._engine)
            tables = inspector.get_table_names(schema=db._schema)
        except:
            pass
        
        return {
            "report": f"Found {len(tables)} tables in the database:\n\n" + 
                     "\n".join([f"- {t}" for t in tables]),
            "raw_data": [{"table": t} for t in tables],
            "sql_query": "SELECT table_name FROM information_schema.tables",
        }
    
    # Show columns for a specific table
    if "show columns" in query_lower or "describe" in query_lower:
        # Try to extract table name
        words = query.split()
        table_name = None
        for i, w in enumerate(words):
            if w.lower() in ["describe", "columns", "of"]:
                if i + 1 < len(words):
                    table_name = words[i + 1].strip(';')
                    break
        
        if table_name:
            try:
                from sqlalchemy import inspect
                inspector = inspect(db._engine)
                columns = inspector.get_columns(table_name, schema=db._schema)
                
                col_data = [{"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]} 
                           for c in columns]
                
                report = f"Columns in '{table_name}':\n\n"
                for c in columns:
                    nullable = "NULL" if c["nullable"] else "NOT NULL"
                    report += f"- {c['name']}: {c['type']} ({nullable})\n"
                
                return {
                    "report": report,
                    "raw_data": col_data,
                    "sql_query": f"DESCRIBE {table_name}",
                }
            except Exception as e:
                return {
                    "report": f"Error: {str(e)}",
                    "raw_data": [],
                    "sql_query": "",
                }
    
    return None  # Not a simple query