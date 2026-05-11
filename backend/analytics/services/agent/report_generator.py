"""
Simple Query Handler
"""

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
