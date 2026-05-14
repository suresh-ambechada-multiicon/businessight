"""
AI agent tools for database analytics.

This module creates LangChain tools that the AI agent uses to interact with
the client database: execute SQL, inspect schemas, search, and perform analytics.

Each tool is defined in its own module under tool_definitions/ directory.
"""

from analytics.services.agent.tool_definitions import (
    # Core database tools
    create_sql_executor,
    create_table_info_tool,
    create_schema_search_tool,
    create_column_values_tool,
    create_table_relationships_tool,
    create_aggregation_tool,
)
from analytics.services.status import send_status


def sql_max_rows_from_budget(token_budget: dict | None) -> int:
    """Same row cap as SQL executor tools — reuse for post-process hydration."""
    max_rows = 2000
    if token_budget:
        available = token_budget.get("available_for_tools", 100000)
        tokens_per_row = 150
        usable_budget = int(available * 0.7)
        max_rows = max(20, min(2000, usable_budget // tokens_per_row))
    return max_rows


def create_tools(db, usable_tables: list[str], ctx=None, token_budget=None):
    """
    Factory that creates the analytics tools bound to a specific
    database connection and table list.

    Returns (tools_list, tool_state_dict).
    tool_state tracks executed queries and their timings.
    """

    # Dialect-aware helpers
    def _is_mssql() -> bool:
        return "mssql" in db._engine.url.drivername

    def _quote_ident(name: str) -> str:
        name = name.strip('"').strip("[]").strip("`")
        if _is_mssql():
            return f"[{name}]"
        return f'"{name}"'

    def _full_table(table_name: str) -> str:
        schema = db._schema
        if schema:
            return f"{_quote_ident(schema)}.{_quote_ident(table_name)}"
        return _quote_ident(table_name)

    def _select_top(columns: str, table: str, n: int, extra: str = "") -> str:
        if _is_mssql():
            return f"SELECT TOP {n} {columns} FROM {table} {extra}".strip()
        return f"SELECT {columns} FROM {table} {extra} LIMIT {n}".strip()

    table_count = len(usable_tables or [])
    if table_count > 150:
        sql_call_limit = 12
    elif table_count > 50:
        sql_call_limit = 10
    else:
        sql_call_limit = 8

    tool_state = {
        "last_sql_query": "",
        "last_raw_data": None,
        "best_raw_data": None,
        "all_sql_queries": [],
        # Hard cap to prevent the agent from thrashing on SQL calls
        # and exceeding Celery soft time limits.
        "sql_call_count": 0,
        "sql_call_limit": sql_call_limit,
        # Final dataset contract (used by extraction to avoid picking wrong query output)
        "final_sql_query": "",
        "final_raw_data": None,
        "final_query_reason": "",
        "table_count": table_count,
        # Non-SQL tool caching + budgets (to avoid redundant LLM loops)
        "tool_cache": {},  # (tool_name, normalized_args) -> result string
        "tool_call_counts": {},  # tool_name -> int
        "tool_call_limits": {
            "search_schema": 2,
            "get_table_info": 3,
            "get_column_values": 3,
            "get_table_relationships": 1,
            "aggregate_data": 2,
        },
    }

    max_rows = sql_max_rows_from_budget(token_budget)

    _ctx = ctx.to_dict() if ctx else {}
    _task_id = ctx.task_id if ctx else ""

    def _status(msg: str):
        send_status(_task_id, msg)

    # Create all tools
    sql_tools = create_sql_executor(
        db,
        tool_state,
        ctx,
        _status,
        _ctx,
        _quote_ident,
        _full_table,
        _select_top,
        max_rows,
    )
    if not isinstance(sql_tools, list):
        sql_tools = [sql_tools]

    tools = [
        # Core database tools
        *sql_tools,
        create_table_info_tool(
            db, tool_state, ctx, _status, _ctx, _quote_ident, _full_table
        ),
        create_schema_search_tool(db, usable_tables, tool_state, ctx, _status, _ctx),
        create_column_values_tool(
            db, tool_state, ctx, _status, _ctx, _full_table, _quote_ident, _select_top
        ),
        create_table_relationships_tool(db, tool_state, ctx, _status, _ctx),
        # Generic grouped summaries without exposing many specialized tools.
        create_aggregation_tool(
            db, tool_state, ctx, _status, _ctx, _full_table, _quote_ident, _select_top
        ),
    ]

    return tools, tool_state
