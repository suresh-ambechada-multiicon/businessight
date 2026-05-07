"""
AI agent tools for database analytics.

This module creates LangChain tools that the AI agent uses to interact with
the client database: execute SQL, inspect schemas, and search tables.

Each tool is defined in its own module under tools/ directory.
"""

from analytics.services.agent.tool_definitions import (
    create_sql_executor,
    create_table_info_tool,
    create_schema_search_tool,
    create_table_stats_tool,
    create_column_values_tool,
    create_table_relationships_tool,
)
from analytics.services.logger import get_logger
from analytics.services.status import send_status

logger = get_logger("tools")


def create_tools(db, usable_tables: list[str], ctx=None, token_budget=None):
    """
    Factory that creates the analytics tools bound to a specific
    database connection and table list.

    Returns (tools_list, tool_state_dict).
    tool_state tracks executed queries and their timings.
    """

    # ── Dialect-aware helpers ────────────────────────────────────────
    def _is_mssql() -> bool:
        return "mssql" in db._engine.url.drivername

    def _quote_ident(name: str) -> str:
        """Quote a SQL identifier to prevent injection. Uses [] for MSSQL, \"\" for others."""
        name = name.strip('"').strip('[]').strip('`')
        if _is_mssql():
            return f"[{name}]"
        return f'"{name}"'

    def _full_table(table_name: str) -> str:
        """Build a fully-qualified, quoted table reference."""
        schema = db._schema
        if schema:
            return f"{_quote_ident(schema)}.{_quote_ident(table_name)}"
        return _quote_ident(table_name)

    def _select_top(columns: str, table: str, n: int, extra: str = "") -> str:
        """Build a dialect-aware SELECT with row limit."""
        if _is_mssql():
            return f"SELECT TOP {n} {columns} FROM {table} {extra}".strip()
        return f"SELECT {columns} FROM {table} {extra} LIMIT {n}".strip()

    tool_state = {
        "last_sql_query": "",
        "last_raw_data": None,
        "best_raw_data": None,
        "all_sql_queries": [],
    }

    # Dynamic row limit calculation based on budget
    max_rows = 1000
    if token_budget:
        available = token_budget.get("available_for_tools", 100000)
        tokens_per_row = 150
        usable_budget = int(available * 0.7)
        max_rows = max(20, min(1000, usable_budget // tokens_per_row))

    _ctx = ctx.to_dict() if ctx else {}
    _task_id = ctx.task_id if ctx else ""
    _db_uri_hash = ctx.db_uri_hash if ctx else ""

    def _status(msg: str):
        send_status(_task_id, msg)

    # Create each tool using factory functions
    tools = [
        create_sql_executor(db, tool_state, ctx, _status, _ctx, _quote_ident, _full_table, _select_top, max_rows),
        create_table_info_tool(db, ctx, _status, _ctx, _quote_ident, _full_table),
        create_schema_search_tool(db, usable_tables, ctx, _status, _ctx),
        create_table_stats_tool(db, ctx, _status, _ctx, _full_table, _quote_ident),
        create_column_values_tool(db, ctx, _status, _ctx, _full_table, _quote_ident, _select_top),
        create_table_relationships_tool(db, ctx, _status, _ctx),
    ]

    return tools, tool_state