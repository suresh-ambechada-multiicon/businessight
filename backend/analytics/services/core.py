"""
Analytics query processing — main orchestrator.

This is the entry point for the /api/query/ endpoint.
It connects to the client database, runs the AI agent, and streams results.
Every step is logged with timing and request context.
"""

import json
import os
import time

from deepagents import create_deep_agent

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.services.agent import (
    StreamResult,
    auto_generate_chart,
    build_messages,
    build_schema_context,
    extract_final_result,
    init_llm,
    stream_agent,
)
from analytics.services.db import (
    build_engine_args,
    create_database,
    detect_active_schema,
    detect_dialect,
    discover_tables,
    normalize_db_uri,
)
from analytics.services.llm_config import get_model_config
from analytics.services.logger import RequestContext, get_logger
from analytics.services.prompts import SYSTEM_PROMPT
from analytics.services.tokens import count_tokens, estimate_query_budget
from analytics.services.tools import create_tools

logger = get_logger("pipeline")


def process_analytics_query(payload: AnalyticsRequest, ctx: RequestContext):
    """
    Main generator that processes an analytics query.
    Yields SSE data chunks for real-time frontend streaming.
    """
    logger.info(
        "Request received",
        extra={
            "data": {
                **ctx.to_dict(),
                "query": payload.query,
                "model": payload.model,
            }
        },
    )

    # Clear any leftover cancellation flags so new queries don't instantly cancel
    from django.core.cache import cache

    cache.delete(f"cancel_{payload.session_id}")

    # ── 1. Database Connection ──────────────────────────────────────────
    from sqlalchemy.exc import SQLAlchemyError

    from analytics.services.status import send_status

    send_status(ctx.task_id, "Connecting to database...")
    step_start = time.time()
    db_uri = normalize_db_uri(payload.db_url.strip())
    engine_args = build_engine_args(db_uri)

    try:
        db_uri, active_schema = detect_active_schema(db_uri, engine_args, ctx)
        db = create_database(db_uri, engine_args, active_schema)
        # Test connection explicitly
        with db._engine.connect() as conn:
            pass
    except SQLAlchemyError as e:
        error_msg = (
            f"Database connection failed: {str(e.__cause__) if e.__cause__ else str(e)}"
        )
        logger.error(error_msg, extra={"data": ctx.to_dict()})
        yield {"event": "error", "data": {"error": error_msg}}
        return
    except Exception as e:
        error_msg = f"Unexpected database error: {str(e)}"
        logger.error(error_msg, extra={"data": ctx.to_dict()})
        yield {"event": "error", "data": {"error": error_msg}}
        return

    connect_time = round((time.time() - step_start) * 1000, 2)

    logger.info(
        "Database connected",
        extra={
            "data": {
                **ctx.to_dict(),
                "connect_time_ms": connect_time,
                "dialect": detect_dialect(db_uri),
                "active_schema": active_schema,
            }
        },
    )

    # ── 2. Table Discovery ──────────────────────────────────────────────
    send_status(ctx.task_id, "Discovering database tables...")
    yield {"event": "status", "data": {"message": "Discovering database tables..."}}
    step_start = time.time()
    usable_tables = discover_tables(db, active_schema, ctx)
    discover_time = round((time.time() - step_start) * 1000, 2)

    if not usable_tables:
        yield {
            "event": "status",
            "data": {
                "message": "Connected to database, but found no business tables yet. Please wait for data migration to finish."
            },
        }
    else:
        yield {
            "event": "status",
            "data": {
                "message": f"Connected to database. Discovered {len(usable_tables)} business tables."
            },
        }

    logger.info(
        "Discovery complete",
        extra={
            "data": {
                **ctx.to_dict(),
                "table_count": len(usable_tables),
                "discover_time_ms": discover_time,
            }
        },
    )

    model_config = get_model_config(payload.model)

    # ── 4. Build Prompt & Messages ─────────────────────────────────────────────────
    send_status(ctx.task_id, "Building schema context...")
    schema_context = build_schema_context(usable_tables, active_schema, db, ctx)
    db_dialect = detect_dialect(db_uri)
    formatted_prompt = SYSTEM_PROMPT.format(
        db_schema=schema_context, db_dialect=db_dialect
    )
    messages = build_messages(payload.session_id, payload.query)

    budget = estimate_query_budget(model_config, formatted_prompt, messages)

    # ── 3. Create Tools ─────────────────────────────────────────────────
    tools, tool_state = create_tools(db, usable_tables, ctx, budget)

    # ── 5. Initialize LLM ──────────────────────────────────────────────
    send_status(ctx.task_id, "Initializing AI agent...")
    llm = init_llm(payload.model, payload.api_key, payload.llm_config, ctx)

    try:
        # ── 6. Create Agent ─────────────────────────────────────────────
        agent = create_deep_agent(
            model=llm,
            tools=tools,
            system_prompt=formatted_prompt,
            response_format=AnalyticsResponse,
        )

        # Messages are built before budget calculation, no need to build again
        # messages = build_messages(payload.session_id, payload.query)

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

        send_status(ctx.task_id, "AI is analyzing your query...")
        yield {"event": "status", "data": {"message": "AI is analyzing your query..."}}

        # ── 9. Stream Agent Execution ──────────────────────────────────
        result_holder = StreamResult()
        for chunk in stream_agent(
            agent, messages, payload.session_id, result_holder, ctx
        ):
            yield chunk

        # Check if a fatal error occurred during streaming
        if result_holder.has_error:
            history_entry.report = (
                "Error occurred during analysis. Check logs for details."
            )
            history_entry.save()
            return

        stream_data = result_holder.data
        if not stream_data:
            # Stream was cancelled (GeneratorExit)
            logger.warning(
                "Stream interrupted — no result data", extra={"data": ctx.to_dict()}
            )
            return

        # ── 10. Extract & Finalize Result ──────────────────────────────
        result = extract_final_result(stream_data, tool_state, ctx)
        result["chart_config"] = auto_generate_chart(
            result["chart_config"], result["raw_data"], query=payload.query
        )

        exec_time = time.time() - start_time

        # ── 11. Save to History ────────────────────────────────────────
        history_entry.report = result["report"]
        history_entry.chart_config = result["chart_config"]
        history_entry.raw_data = result["raw_data"]
        history_entry.sql_query = result["sql_query"]
        history_entry.execution_time = exec_time
        history_entry.save()

        # ── 12. Yield Final Result ─────────────────────────────────────
        yield {
            "event": "result",
            "data": {
                "report": result["report"],
                "chart_config": result["chart_config"],
                "raw_data": result["raw_data"],
                "sql_query": result["sql_query"],
                "execution_time": exec_time,
                "done": True,
            },
        }

        # Estimate usage
        out_tokens = count_tokens(result["report"]) + count_tokens(
            str(result.get("chart_config", ""))
        )
        raw_data_str = str(tool_state.get("last_raw_data", ""))
        in_tokens = budget["total_used"] + count_tokens(raw_data_str)
        cost = (in_tokens / 1_000_000 * model_config.cost_per_1m_input) + (
            out_tokens / 1_000_000 * model_config.cost_per_1m_output
        )

        yield {
            "event": "usage",
            "data": {
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "estimated_cost": round(cost, 4),
            },
        }

        # ── Final Log ──────────────────────────────────────────────────
        logger.info(
            "Request completed",
            extra={
                "data": {
                    **ctx.to_dict(),
                    "total_time_ms": round(exec_time * 1000, 2),
                    "report_length": len(result["report"]),
                    "raw_data_rows": len(result["raw_data"])
                    if isinstance(result["raw_data"], list)
                    else 0,
                    "has_chart": result["chart_config"] is not None,
                    "sql_queries_count": len(tool_state.get("all_sql_queries", [])),
                    "connect_time_ms": connect_time,
                    "discover_time_ms": discover_time,
                }
            },
        )

    except Exception as e:
        logger.error(
            "Pipeline error",
            exc_info=True,
            extra={
                "data": {
                    **ctx.to_dict(),
                    "error": str(e),
                    "elapsed_ms": ctx.elapsed_ms(),
                }
            },
        )
        yield {"event": "error", "data": {"message": f"Error: {str(e)}"}}

    finally:
        pass
