"""
Table Info Tool - Get schema for specified tables.
"""

import time

from langchain.tools import tool
from sqlalchemy import inspect as sa_inspect

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def _strip_sql_ident(s: str) -> str:
    return s.strip().strip('"`[]')


def _split_schema_table(raw: str, default_schema: str | None) -> tuple[str, str | None]:
    """
    Turn 'dbo.booking', '[dbo].[booking]', or 'booking' into (table_name, schema).
    """
    t = _strip_sql_ident(raw)
    if "." in t:
        sch, name = t.rsplit(".", 1)
        return _strip_sql_ident(name), _strip_sql_ident(sch) or default_schema
    return t, default_schema


def create_table_info_tool(db, ctx, _status, _ctx, _quote_ident, _full_table):
    """Factory to create the get_table_info tool."""

    @tool
    def get_table_info(table_names: str) -> str:
        """
        Get the schema for the specified tables.
        Pass a comma-separated list of table names, e.g., 'users, orders'.
        """
        _status(f"Inspecting table: {table_names}...")
        start = time.time()
        
        try:
            # Must inspect the Engine — db._schema is a string (e.g. "dbo"), not inspectable.
            inspector = getattr(db, "_inspector", None) or sa_inspect(db._engine)
            table_list = [t.strip() for t in table_names.split(",") if t.strip()]
            default_schema = getattr(db, "_schema", None)

            output = []
            for table_name in table_list:
                try:
                    tbl, sch = _split_schema_table(table_name, default_schema)
                    columns = inspector.get_columns(tbl, schema=sch)
                    pk_cols = inspector.get_pk_constraints(tbl, schema=sch)
                    pk_names = pk_cols.get("constrained_columns", [])
                    
                    col_info = []
                    for col in columns:
                        col_str = f"  {col['name']}: {col['type']}"
                        if col["name"] in pk_names:
                            col_str += " (PK)"
                        if not col["nullable"]:
                            col_str += " NOT NULL"
                        col_info.append(col_str)
                    
                    output.append(f"{tbl}:\n" + "\n".join(col_info))
                except Exception as e:
                    output.append(f"{table_name}: Error - {str(e)}")
            
            result = "\n\n".join(output) if output else "No tables found."
            
            elapsed = round((time.time() - start) * 1000, 2)
            logger.info(
                "Tool: get_table_info",
                extra={"data": {**_ctx, "tables": table_names, "time_ms": elapsed}},
            )

            _status("Table inspection complete")
            return result
        except Exception as e:
            logger.error(
                "Schema inspection failed",
                extra={"data": {**_ctx, "tables": table_names, "error": str(e)}},
            )
            return f"Error getting table info: {str(e)}"

    return get_table_info