"""
Analytics query processing — main orchestrator.

This is the entry point for the /api/query/ endpoint.
It connects to the client database, runs the AI agent, and streams results.
Every step is logged with timing and request context.
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
    StreamResult,
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
from analytics.services.logger import get_logger, RequestContext

from deepagents import create_deep_agent

logger = get_logger("pipeline")


def process_analytics_query(payload: AnalyticsRequest, ctx: RequestContext):
    """
    Main generator that processes an analytics query.
    Yields SSE data chunks for real-time frontend streaming.
    """
    logger.info("Request received", extra={"data": {
        **ctx.to_dict(),
        "query": payload.query,
        "model": payload.model,
    }})

    # Clear any leftover cancellation flags so new queries don't instantly cancel
    from django.core.cache import cache
    cache.delete(f"cancel_{payload.session_id}")

    # ── 1. Database Connection ──────────────────────────────────────────
    step_start = time.time()
    db_uri = normalize_db_uri(payload.db_url.strip())
    engine_args = build_engine_args(db_uri)
    db_uri, active_schema = detect_active_schema(db_uri, engine_args)
    db = create_database(db_uri, engine_args, active_schema)
    connect_time = round((time.time() - step_start) * 1000, 2)

    logger.info("Database connected", extra={"data": {
        **ctx.to_dict(),
        "connect_time_ms": connect_time,
        "dialect": detect_dialect(db_uri),
        "active_schema": active_schema,
    }})

    # ── 2. Table Discovery ──────────────────────────────────────────────
    step_start = time.time()
    usable_tables = discover_tables(db, active_schema, ctx)
    discover_time = round((time.time() - step_start) * 1000, 2)

    if not usable_tables:
        yield f"data: {json.dumps({'status': 'Connected to database, but found no business tables yet. Please wait for data migration to finish.'})}\n\n"
    else:
        yield f"data: {json.dumps({'status': f'Connected to database. Discovered {len(usable_tables)} business tables.'})}\n\n"

    logger.info("Discovery complete", extra={"data": {
        **ctx.to_dict(),
        "table_count": len(usable_tables),
        "discover_time_ms": discover_time,
    }})

    # ── 3. Create Tools ─────────────────────────────────────────────────
    tools, tool_state = create_tools(db, usable_tables, ctx)

    # ── 4. Build Prompt ─────────────────────────────────────────────────
    schema_context = build_schema_context(usable_tables, active_schema, db, ctx)
    db_dialect = detect_dialect(db_uri)
    formatted_prompt = SYSTEM_PROMPT.format(db_schema=schema_context, db_dialect=db_dialect)

    # ── 5. Initialize LLM ──────────────────────────────────────────────
    llm, env_var_name, original_key = init_llm(payload.model, payload.api_key, ctx)

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
        result_holder = StreamResult()
        for chunk in stream_agent(agent, messages, payload.session_id, result_holder, ctx):
            yield chunk

        stream_data = result_holder.data

        # Save partial progress if stream was interrupted
        last_report = stream_data.get("last_non_empty_report", "")
        full_content = stream_data.get("full_content", "")
        if not stream_data:
            # Stream was cancelled (GeneratorExit)
            logger.warning("Stream interrupted — no result data", extra={"data": ctx.to_dict()})
            if last_report or full_content:
                history_entry.report = last_report or full_content
                history_entry.save()
            return

        # ── 10. Extract & Finalize Result ──────────────────────────────
        result = extract_final_result(stream_data, tool_state, ctx)
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

        # ── Final Log ──────────────────────────────────────────────────
        logger.info("Request completed", extra={"data": {
            **ctx.to_dict(),
            "total_time_ms": round(exec_time * 1000, 2),
            "report_length": len(result["report"]),
            "raw_data_rows": len(result["raw_data"]) if isinstance(result["raw_data"], list) else 0,
            "has_chart": result["chart_config"] is not None,
            "sql_queries_count": len(tool_state.get("all_sql_queries", [])),
            "connect_time_ms": connect_time,
            "discover_time_ms": discover_time,
        }})

    except Exception as e:
        logger.error("Pipeline error", exc_info=True, extra={"data": {
            **ctx.to_dict(),
            "error": str(e),
            "elapsed_ms": ctx.elapsed_ms(),
        }})
        yield f"data: {json.dumps({'status': f'Error: {str(e)}'})}\n\n"

    finally:
        restore_api_key(env_var_name, original_key)
