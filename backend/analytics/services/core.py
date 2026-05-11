"""
Analytics query processing — main orchestrator.

This is the entry point for the /api/query/ endpoint.
It connects to the client database, runs the AI agent, and streams results.
Every step is logged with timing and request context.
"""

import json
import os
import time
from decimal import Decimal

from deepagents import create_deep_agent

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.services.agent.runner import (
    StreamResult,
    build_messages,
    build_schema_context,
    extract_final_result,
    init_llm,
    stream_agent,
)
from analytics.services.database.connection import (
    build_engine_args,
    create_database,
    detect_active_schema,
    detect_dialect,
    discover_tables,
    normalize_db_uri,
)
from analytics.services.llm import get_model_config
from analytics.services.logger import RequestContext, get_logger
from analytics.services.prompts import SYSTEM_PROMPT
from analytics.services.tokens import count_tokens, estimate_query_budget
from analytics.services.agent.tools import create_tools
from analytics.services.agent.table_retrieval import rank_tables_for_query
from analytics.services.agent.answer_verifier import verify_report_against_data

logger = get_logger("pipeline")


def _needs_report_recovery(report: str) -> bool:
    text = (report or "").strip().lower()
    if not text:
        return True
    fallback_markers = [
        "no readable summary was produced",
        "did not produce a readable summary",
        "no output generated",
    ]
    return any(marker in text for marker in fallback_markers)


def _recover_report_from_data(llm, query: str, sql_query: str, raw_data: list) -> str:
    """Generate a compact fallback report when agent output is missing/unreadable."""
    from langchain_core.messages import HumanMessage

    def _safe_json(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if isinstance(obj, (bytes, memoryview)):
            return "(binary data)"
        if isinstance(obj, dict):
            return {str(k): _safe_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_safe_json(i) for i in obj]
        return str(obj)

    rows = raw_data if isinstance(raw_data, list) else []
    sample = _safe_json(rows[:20])
    prompt = (
        "You are a senior business analyst. The main agent could not produce a final readable report.\n"
        "Generate a concise markdown report with sections: Overview, Key Findings, Notes.\n"
        "Rules:\n"
        "- Use only the provided SQL result sample.\n"
        "- Do not invent values.\n"
        "- Mention if sample is small or partial.\n\n"
        f"User query: {query}\n"
        f"SQL used: {sql_query}\n"
        f"Rows returned: {len(rows)}\n"
        f"Result sample JSON: {json.dumps(sample)}\n"
    )
    try:
        recovered = llm.invoke([HumanMessage(content=prompt)])
        content = getattr(recovered, "content", "")
        if isinstance(content, list):
            content = "".join(
                c.get("text", "") if isinstance(c, dict) else str(c) for c in content
            )
        text = (content or "").strip()
        if text:
            return text
    except Exception:
        logger.warning("Fallback report recovery failed", exc_info=True)
    return ""


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

    start_time = time.time()
    history_entry = QueryHistory.objects.create(
        session_id=payload.session_id,
        query=payload.query,
        report="Analyzing...",
        chart_config=None,
        raw_data=None,
        sql_query="",
        execution_time=0.0,
        has_data=False,
        task_id=ctx.task_id,
    )

    send_status(ctx.task_id, "AI is analyzing your query...")
    yield {"event": "query_id", "data": {"id": history_entry.id}}
    yield {"event": "status", "data": {"message": "AI is analyzing your query..."}}

    exec_model = payload.executor_model or payload.model
    model_config = get_model_config(exec_model)

    ranked_tables = rank_tables_for_query(
        usable_tables=usable_tables,
        user_query=payload.query,
        db_uri_hash=ctx.db_uri_hash or "",
    )
    skip_schema_cache = len(usable_tables) > 15

    # ── 4. Build Prompt & Messages ─────────────────────────────────────────────────
    send_status(ctx.task_id, "Building schema context...")
    schema_context = build_schema_context(
        usable_tables,
        active_schema,
        db,
        ctx,
        table_rank_order=ranked_tables,
        skip_full_context_cache=skip_schema_cache,
    )
    db_dialect = detect_dialect(db_uri)
    # Use .replace() so schema text cannot break templating if it contains "{" / "}".
    formatted_prompt = (
        SYSTEM_PROMPT.replace("{db_dialect}", str(db_dialect)).replace(
            "{db_schema}", schema_context
        )
    )
    messages = build_messages(payload.session_id, payload.query)

    budget = estimate_query_budget(model_config, formatted_prompt, messages)

    # ── 3. Create Tools ─────────────────────────────────────────────────
    tools, tool_state = create_tools(db, usable_tables, ctx, budget)

    # ── 5. Initialize LLM ──────────────────────────────────────────────
    send_status(ctx.task_id, "Initializing AI agent...")
    llm = init_llm(exec_model, payload.api_key, payload.llm_config, ctx)

    try:
        # ── 6. Create Agent ─────────────────────────────────────────────
        logger.info("Creating deep agent...", extra={"data": ctx.to_dict()})
        try:
            agent = create_deep_agent(
                model=llm,
                tools=tools,
                system_prompt=formatted_prompt,
                response_format=AnalyticsResponse,
            )
        except Exception as agent_err:
            logger.error(f"Agent creation failed: {agent_err}", exc_info=True)
            raise
        
        logger.info("Agent created successfully", extra={"data": ctx.to_dict()})

        # ── 8. Create History Record ───────────────────────────────────
        start_time = time.time()
        # ── 9. Stream Agent Execution ──────────────────────────────────
        result_holder = StreamResult()
        
        # Check for simple query fast-path
        from analytics.services.agent.tools import is_simple_query
        from analytics.services.agent.report_generator import handle_simple_query
        
        if is_simple_query(payload.query):
            send_status(ctx.task_id, "Processing simple query...")
            yield {"event": "status", "data": {"message": "Processing simple query..."}}
            
            simple_result = handle_simple_query(db, payload.query, usable_tables)
            if simple_result:
                history_entry.report = simple_result["report"]
                history_entry.raw_data = simple_result["raw_data"]
                history_entry.sql_query = simple_result.get("sql_query", "")
                history_entry.has_data = bool(simple_result.get("raw_data"))
                history_entry.agent_trace = [{"step": "simple_query_fast_path"}]
                history_entry.save()
                
                yield {"event": "result", "data": {
                    "report": simple_result["report"],
                    "chart_config": None,
                    "raw_data": simple_result["raw_data"],
                    "sql_query": simple_result.get("sql_query", ""),
                    "done": True,
                }}
                return
        
        if getattr(payload, "direct_sql", None):
            # Fast-path for Saved Prompts: execute SQL directly and summarize
            from langchain_core.messages import HumanMessage
            
            send_status(ctx.task_id, "Executing saved SQL query...")
            yield {"event": "status", "data": {"message": "Executing saved SQL query..."}}
            
            # Find the SQL execution tool
            sql_tool = next((t for t in tools if t.name == "execute_read_only_sql"), None)
            if not sql_tool:
                yield {"event": "status", "data": {"message": "Error: SQL tool not found."}}
                return
                
            # Execute SQL using LangChain tool interface
            sql_result_str = sql_tool.invoke({"query": payload.direct_sql})
            raw_data = tool_state.get("best_raw_data") or tool_state.get("last_raw_data") or []
            
            send_status(ctx.task_id, "Generating fast report...")
            yield {"event": "status", "data": {"message": "Generating fast report..."}}
            
            fast_prompt = f"""
            You are a senior business data analyst. The user asked: "{payload.query}"
            I have already executed the database query for this.
            
            SQL Executed: {payload.direct_sql}
            Result Row Count: {len(raw_data)}
            Result Sample: {json.dumps(raw_data[:20])}
            
            Provide a professional, structured analytical report in Markdown.
            - Use clear headers (e.g., ### Overview, ### Key Metrics)
            - Analyze the data provided in the sample
            - Mention trends, distributions, or notable items
            - Be concise but thorough (at least 3-4 paragraphs)
            - MUST use professional formatting (bolding, lists, headers)
            - DO NOT include the SQL code block again
            """
            
            try:
                response = llm.stream([HumanMessage(content=fast_prompt)])
                
                full_report = ""
                for chunk in response:
                    content = getattr(chunk, "content", chunk)
                    if isinstance(content, list):
                        content = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in content])
                    
                    if content and isinstance(content, str):
                        full_report += content
                        yield {
                            "event": "delta",
                            "data": {"content": content, "timestamp": time.time()},
                        }
            except Exception as e:
                logger.error("Fast report failed", exc_info=True)
                err_msg = f"Fast report generation failed: {str(e)}"
                full_report = err_msg
                yield {"event": "delta", "data": {"content": err_msg, "timestamp": time.time()}}
                
            # Mock the stream_data to look like agent output
            # By providing `raw_data`, the frontend extractor will know data exists
            result_holder.data = {
                "full_content": full_report,
                "last_non_empty_report": full_report,
                "tool_calls": [],
                "raw_data": raw_data,
                "sql_query": payload.direct_sql,
                "trace": [],
            }
            # Also populate tool_state for proper extraction
            tool_state["last_sql_query"] = payload.direct_sql
            tool_state["last_raw_data"] = raw_data
            tool_state["best_raw_data"] = raw_data
            tool_state["all_sql_queries"] = [{"query": payload.direct_sql, "time": 0, "rows": len(raw_data) if raw_data else 0}]
            
        else:
            # Normal deep-agent loop
            for chunk in stream_agent(
                agent, messages, payload.session_id, result_holder, ctx
            ):
                yield chunk

        # Check if a fatal error occurred during streaming
        if result_holder.has_error:
            history_entry.report = (
                "Error occurred during analysis. Check logs for details."
            )
            history_entry.execution_time = 0.1
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

        # Final fallback: ensure we still provide a readable narrative if
        # the model exhausted tool/call budget and returned only partial structure.
        if _needs_report_recovery(result.get("report", "")) and result.get("raw_data"):
            send_status(ctx.task_id, "Finalizing narrative from query results...")
            yield {
                "event": "status",
                "data": {"message": "Finalizing narrative from query results..."},
            }
            recovered_report = _recover_report_from_data(
                llm=llm,
                query=payload.query,
                sql_query=result.get("sql_query") or "",
                raw_data=result.get("raw_data") or [],
            )
            if recovered_report:
                result["report"] = recovered_report

        # ── 11. Final Telemetry Calculation ────────────────────────────
        exec_time = time.time() - ctx.start_time

        # Sanitize raw_data to ensure JSON-serializability
        def _sanitize_row(row):
            from decimal import Decimal
            if not isinstance(row, dict):
                return row
            clean = {}
            for k, v in row.items():
                if isinstance(v, (bytes, memoryview)):
                    clean[k] = "(binary data)"
                elif isinstance(v, Decimal):
                    clean[k] = float(v)
                elif hasattr(v, "isoformat"):
                    clean[k] = v.isoformat()
                elif isinstance(v, (str, int, float, bool)) or v is None:
                    clean[k] = v
                else:
                    clean[k] = str(v)
            return clean

        if isinstance(result["raw_data"], list):
            result["raw_data"] = [_sanitize_row(r) for r in result["raw_data"]]

        agent_trace = list(stream_data.get("trace") or [])
        verifier_token_in = 0
        verifier_token_out = 0
        if payload.verify_answer and ctx.elapsed_ms() < 180_000:
            verdict = verify_report_against_data(
                report=result.get("report") or "",
                sql_query=result.get("sql_query") or "",
                raw_data_sample=result.get("raw_data") or [],
                verifier_model=payload.verifier_model or payload.model,
                api_key=payload.api_key,
                llm_config=payload.llm_config,
                ctx=ctx,
            )
            verifier_token_in = int(verdict.get("verifier_input_tokens") or 0)
            verifier_token_out = int(verdict.get("verifier_output_tokens") or 0)
            agent_trace.append(
                {
                    "step": "verification",
                    "consistent": verdict.get("ok"),
                    "issues": verdict.get("issues") or [],
                }
            )
            # Do not inject verifier notes into the user-facing report.
            # Keep verdict in trace/logs; report should stay clean and consistent.
        elif payload.verify_answer:
            logger.warning(
                "Verification skipped due to elapsed time budget",
                extra={"data": {**ctx.to_dict(), "elapsed_ms": ctx.elapsed_ms()}},
            )

        # Token Usage Calculation
        # Output tokens: reasoning + tool calls + final report
        base_out_tokens = count_tokens(stream_data.get("full_content", "")) + count_tokens(
            stream_data.get("full_tool_args_str", "")
        )

        # Input tokens: initial context + all tool outputs - serialize with proper handling
        raw_data_for_tokens = tool_state.get("best_raw_data") or []
        # Convert datetime objects to strings for JSON serialization
        import datetime
        from decimal import Decimal
        def _token_sanitize(obj):
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return obj
            if isinstance(obj, Decimal):
                return float(obj)
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: _token_sanitize(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_token_sanitize(i) for i in obj]
            return str(obj)
        
        tool_output_str = json.dumps(_token_sanitize(raw_data_for_tokens))
        base_in_tokens = budget["total_used"] + count_tokens(tool_output_str)

        padded_base_in = base_in_tokens * 1.05
        padded_base_out = base_out_tokens * 1.05
        padded_v_in = verifier_token_in * 1.05
        padded_v_out = verifier_token_out * 1.05

        in_tokens = int(padded_base_in + padded_v_in)
        out_tokens = int(padded_base_out + padded_v_out)

        verifier_cfg = get_model_config(payload.verifier_model or payload.model)
        cost = (
            (padded_base_in / 1_000_000) * model_config.cost_per_1m_input
            + (padded_base_out / 1_000_000) * model_config.cost_per_1m_output
            + (padded_v_in / 1_000_000) * verifier_cfg.cost_per_1m_input
            + (padded_v_out / 1_000_000) * verifier_cfg.cost_per_1m_output
        )

        # ── 12. Final Save to History ──────────────────────────────────
        history_entry.report = result["report"]
        history_entry.chart_config = result["chart_config"]
        history_entry.raw_data = result["raw_data"]
        history_entry.sql_query = result["sql_query"]
        history_entry.agent_trace = agent_trace
        history_entry.execution_time = exec_time
        history_entry.has_data = bool(result["raw_data"] and len(result["raw_data"]) > 0)
        history_entry.input_tokens = in_tokens
        history_entry.output_tokens = out_tokens
        history_entry.estimated_cost = round(cost, 4)
        history_entry.save()

        # ── 13. Yield Final Results ─────────────────────────────────────
        # Send usage event first
        yield {
            "event": "usage",
            "data": {
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "estimated_cost": round(cost, 4),
            },
        }

        # Send final result (includes everything)
        yield {
            "event": "result",
            "data": {
                "report": result["report"],
                "chart_config": result["chart_config"],
                "raw_data": result["raw_data"],
                "sql_query": result["sql_query"],
                "result_blocks": result.get("result_blocks") or [],
                "execution_time": exec_time,
                "usage": {
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "estimated_cost": round(cost, 4),
                },
                "done": True,
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
                    "has_chart": bool(result.get("chart_config")),
                    "sql_queries_count": len(tool_state.get("all_sql_queries", [])),
                    "connect_time_ms": connect_time,
                    "discover_time_ms": discover_time,
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                }
            },
        )

    except Exception as e:
        import traceback
        err_msg = str(e)
        full_trace = traceback.format_exc()
        
        logger.error(
            "Pipeline error",
            exc_info=True,
            extra={
                "data": {
                    **ctx.to_dict(),
                    "error": err_msg[:500],  # Limit error length
                    "error_type": type(e).__name__,
                    "elapsed_ms": ctx.elapsed_ms(),
                    "traceback": full_trace[:1000],  # Limit traceback
                }
            },
        )
        # Update history record with the error if it was created
        if history_entry:
            history_entry.report = f"Error: {err_msg}"
            # Use a small non-zero execution time to signal completion to the frontend
            history_entry.execution_time = history_entry.execution_time or 0.1
            history_entry.save()
            
        yield {"event": "error", "data": {"message": f"Error: {err_msg}"}}

    finally:
        pass
