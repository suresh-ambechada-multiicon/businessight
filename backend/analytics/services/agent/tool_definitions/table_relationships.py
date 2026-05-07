"""
Table Relationships Tool - Detect foreign key relationships.
"""

import time

from langchain.tools import tool
from sqlalchemy import inspect

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_table_relationships_tool(db, ctx, _status, _ctx):
    """Factory to create the get_table_relationships tool."""

    @tool
    def get_table_relationships(table_name: str) -> str:
        """
        Detect foreign key relationships for a table.
        Shows which columns reference other tables (outgoing FKs)
        and which other tables reference this table (incoming FKs).
        Use this to understand how tables are connected before writing JOINs.
        """
        _status(f"Detecting relationships for {table_name}...")
        start = time.time()
        table_name = table_name.strip()

        try:
            db_inspector = inspect(db._engine)

            # Outgoing foreign keys (this table references others)
            fks = db_inspector.get_foreign_keys(table_name, schema=db._schema)
            lines = [f"Relationships for table: {table_name}", ""]

            if fks:
                lines.append("Outgoing References (this table -> other tables):")
                for fk in fks:
                    from_col = ", ".join(fk["constrained_columns"])
                    to_table = fk["referred_table"]
                    to_col = ", ".join(fk["referred_columns"])
                    lines.append(f"  {from_col} -> {to_table}.{to_col}")
            else:
                lines.append("  No outgoing foreign keys")

            # Incoming foreign keys (other tables referencing this)
            # Check all tables for FKs pointing to this table
            incoming_lines = []
            for other_table in db_inspector.get_table_names(schema=db._schema):
                if other_table == table_name:
                    continue
                try:
                    other_fks = db_inspector.get_foreign_keys(other_table, schema=db._schema)
                    for fk in other_fks:
                        if fk["referred_table"] == table_name:
                            from_col = ", ".join(fk["constrained_columns"])
                            to_col = ", ".join(fk["referred_columns"])
                            incoming_lines.append(f"  {other_table}.{from_col} -> {table_name}.{to_col}")
                except:
                    pass

            lines.append("")
            if incoming_lines:
                lines.append("Incoming References (other tables -> this table):")
                lines.extend(incoming_lines)
            else:
                lines.append("  No incoming foreign keys found")

            elapsed = round((time.time() - start) * 1000, 2)
            logger.info("Tool: get_table_relationships", extra={
                **_ctx, "table": table_name, "time_ms": elapsed,
            })
            
            return "\n".join(lines)

        except Exception as e:
            logger.error("get_table_relationships failed", extra={
                **_ctx, "table": table_name, "error": str(e),
            })
            return f"Error detecting relationships: {str(e)}"

    return get_table_relationships