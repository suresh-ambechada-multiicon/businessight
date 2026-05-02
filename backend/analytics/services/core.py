"""
Analytics query processing — main orchestrator.

This is the entry point for the /api/query/ endpoint.
It connects to the client database, runs the AI agent, and streams results.
"""

import json
import time

from analytics.services.db import (
    normalize_db_uri,
    build_engine_args,
    detect_active_schema,
    create_database,
    discover_tables,
    detect_dialect,
)
from analytics.services.tools import create_tools
from analytics.services.agent import (
    build_schema_context,
    init_llm,
    restore_api_key,
    build_messages,
    stream_agent,
    extract_final_result,
    auto_generate_chart,
)
from analytics.models import QueryHistory
from analytics.services.prompts import SYSTEM_PROMPT
from analytics.schemas import AnalyticsRequest, AnalyticsResponse

from deepagents import create_deep_agent


def process_analytics_query(payload: AnalyticsRequest):
    """
    Main generator that processes an analytics query.
    Yields SSE data chunks for real-time frontend streaming.
    """
    # Clear any leftover cancellation flags so new queries don't instantly cancel
    from django.core.cache import cache
    cache.delete(f"cancel_{payload.session_id}")

    # ── 1. Database Connection ──────────────────────────────────────────
    db_uri = normalize_db_uri(payload.db_url.strip())
    engine_args = build_engine_args(db_uri)
    db_uri, active_schema = detect_active_schema(db_uri, engine_args)
    db = create_database(db_uri, engine_args, active_schema)

    # ── 2. Table Discovery ──────────────────────────────────────────────
    usable_tables = discover_tables(db, active_schema)

    if not usable_tables:
        yield f"data: {json.dumps({'status': 'Connected to database, but found no business tables yet. Please wait for data migration to finish.'})}\n\n"
    else:
        yield f"data: {json.dumps({'status': f'Connected to database. Discovered {len(usable_tables)} business tables.'})}\n\n"

    # ── 3. Create Tools ─────────────────────────────────────────────────
    tools, tool_state = create_tools(db, usable_tables)

    # ── 4. Build Prompt ─────────────────────────────────────────────────
    schema_context = build_schema_context(usable_tables, active_schema, db)
    db_dialect = detect_dialect(db_uri)
    formatted_prompt = SYSTEM_PROMPT.format(db_schema=schema_context, db_dialect=db_dialect)

    # ── 5. Initialize LLM ──────────────────────────────────────────────
    llm, env_var_name, original_key = init_llm(payload.model, payload.api_key)

    try:
        # ── 6. Create Agent ─────────────────────────────────────────────
        agent = create_deep_agent(
            model=llm,
            tools=tools,
            system_prompt=formatted_prompt,
            response_format=AnalyticsResponse,
        )

        # ── 7. Build Messages ──────────────────────────────────────────
        messages = build_messages(payload.session_id, payload.query)

        # ── 8. Create History Record ───────────────────────────────────
        start_time = time.time()
        history_entry = QueryHistory.objects.create(
            session_id=payload.session_id,
            query=payload.query,
            report="Analyzing...",
            chart_config=None,
            raw_data=None,
            sql_query="",
            execution_time=0.0,
        )

        yield f"data: {json.dumps({'status': 'Initializing AI agent...'})}\n\n"

        # ── 9. Stream Agent Execution ──────────────────────────────────
        stream_data = {}
        for chunk in stream_agent(agent, messages, payload.session_id):
            yield chunk

        # Grab accumulated data from the stream
        stream_data = getattr(stream_agent, '_result', {})

        # Save partial progress if stream was interrupted
        last_report = stream_data.get("last_non_empty_report", "")
        full_content = stream_data.get("full_content", "")
        if not stream_data:
            # Stream was cancelled (GeneratorExit)
            if last_report or full_content:
                history_entry.report = last_report or full_content
                history_entry.save()
            return

        # ── 10. Extract & Finalize Result ──────────────────────────────
        result = extract_final_result(stream_data, tool_state)
        result["chart_config"] = auto_generate_chart(result["chart_config"], result["raw_data"])

        exec_time = time.time() - start_time

        # ── 11. Save to History ────────────────────────────────────────
        history_entry.report = result["report"]
        history_entry.chart_config = result["chart_config"]
        history_entry.raw_data = result["raw_data"]
        history_entry.sql_query = result["sql_query"]
        history_entry.execution_time = exec_time
        history_entry.save()

        # ── 12. Yield Final Result ─────────────────────────────────────
        yield f"data: {json.dumps({
            'report': result['report'],
            'chart_config': result['chart_config'],
            'raw_data': result['raw_data'],
            'sql_query': result['sql_query'],
            'execution_time': exec_time,
            'done': True,
        })}\n\n"

    finally:
        restore_api_key(env_var_name, original_key)
