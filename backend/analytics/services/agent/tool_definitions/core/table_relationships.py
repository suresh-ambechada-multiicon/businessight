"""
Table Relationships Tool - Detect foreign key relationships.
"""

import time

from langchain.tools import tool
from sqlalchemy import inspect

from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_table_relationships_tool(db, tool_state, ctx, _status, _ctx):
    """Factory to create the get_table_relationships tool."""

    @tool
    def get_table_relationships(table_name: str) -> str:
        """
        Detect foreign key relationships for a table.
        Shows which columns reference other tables (outgoing FKs)
        and which other tables reference this table (incoming FKs).
        Use this to understand how tables are connected before writing JOINs.
        """
        table_name = table_name.strip()
        cache_key = ("get_table_relationships", table_name.lower())
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
        counts["get_table_relationships"] = (
            int(counts.get("get_table_relationships") or 0) + 1
        )
        if int(limits.get("get_table_relationships") or 0) and counts[
            "get_table_relationships"
        ] > int(limits["get_table_relationships"]):
            msg = "get_table_relationships call limit reached. Use known relationships and proceed to final SQL."
            cache[cache_key] = msg
            return msg

        _status(f"Detecting relationships for {table_name}...")
        start = time.time()

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

            incoming_lines = []
            table_count = (
                int(tool_state.get("table_count") or 0)
                if isinstance(tool_state, dict)
                else 0
            )
            if table_count <= 80:
                # Incoming FK scan touches every table; only do it for smaller catalogs.
                for other_table in db_inspector.get_table_names(schema=db._schema):
                    if other_table == table_name:
                        continue
                    try:
                        other_fks = db_inspector.get_foreign_keys(
                            other_table, schema=db._schema
                        )
                        for fk in other_fks:
                            if fk["referred_table"] == table_name:
                                from_col = ", ".join(fk["constrained_columns"])
                                to_col = ", ".join(fk["referred_columns"])
                                incoming_lines.append(
                                    f"  {other_table}.{from_col} -> {table_name}.{to_col}"
                                )
                    except Exception:
                        pass
            else:
                incoming_lines.append(
                    f"  Incoming FK scan skipped for large catalog ({table_count} tables)."
                )

            lines.append("")
            if incoming_lines:
                lines.append("Incoming References (other tables -> this table):")
                lines.extend(incoming_lines)
            else:
                lines.append("  No incoming foreign keys found")

            elapsed = round((time.time() - start) * 1000, 2)
            logger.info(
                "Tool: get_table_relationships",
                extra={
                    **_ctx,
                    "table": table_name,
                    "time_ms": elapsed,
                },
            )

            result_text = "\n".join(lines)
            cache[cache_key] = result_text
            return result_text

        except Exception as e:
            logger.error(
                "get_table_relationships failed",
                extra={
                    **_ctx,
                    "table": table_name,
                    "error": str(e),
                },
            )
            result_text = f"Error detecting relationships: {str(e)}"
            cache[cache_key] = result_text
            return result_text

    return get_table_relationships
