"""
AI agent orchestration.

Handles LLM initialization, agent creation, streaming loop,
and response parsing/recovery. All operations are logged with
timing and request context.
"""

import json
import os
import time
import traceback

from decimal import Decimal
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from langchain_core.utils.json import parse_partial_json

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsResponse
from analytics.services.logger import get_logger, RequestContext

logger = get_logger("agent")


# ── Thread-safe result container ────────────────────────────────────────

class StreamResult:
    """Mutable container for streaming results. One per request — thread-safe."""

    def __init__(self):
        self.data: dict = {}


# ── Schema Context Builder ──────────────────────────────────────────────

def build_schema_context(usable_tables: list[str], active_schema, db, ctx=None) -> str:
    """
    Build the schema context string that gets injected into the system prompt.
    For small table counts, include full column details.
    For large counts, just list names and let the AI use tools.
    """
    from sqlalchemy import inspect as sa_inspect

    def _get_table_schema(table_names_str: str) -> str:
        tables = [t.strip() for t in table_names_str.split(",") if t.strip()]
        db_inspector = sa_inspect(db._engine)
        output = []
        for t in tables:
            columns = db_inspector.get_columns(t, schema=db._schema)
            cols_str = ", ".join([f"{c['name']} {str(c['type'])}" for c in columns])
            output.append(f"Table '{t}' columns: {cols_str}")
        return "\n".join(output) if output else "No tables found."

    schema_context = ""
    if active_schema:
        schema_context += f"Active Schema: {active_schema} (Prefix tables with this schema if required by dialect)\n\n"

    if len(usable_tables) <= 10:
        schema_context += "Detailed Schema:\n" + _get_table_schema(", ".join(usable_tables))
    else:
        schema_context += (
            f"Tables: {', '.join(usable_tables)}\n"
            f"Use `search_schema` or `get_table_info` to find specific columns."
        )

    _ctx = ctx.to_dict() if ctx else {}
    logger.info("Schema context built", extra={"data": {
        **_ctx,
        "table_count": len(usable_tables),
        "mode": "detailed" if len(usable_tables) <= 10 else "names_only",
        "context_length": len(schema_context),
    }})

    return schema_context


# ── LLM Initialization ─────────────────────────────────────────────────

def _detect_provider(model: str) -> str:
    """
    Detect the LLM provider from the model string.
    Supports both explicit format (e.g., 'openai:gpt-4o') and
    bare model names (e.g., 'gemini-2.0-flash').
    """
    if ":" in model:
        return model.split(":")[0]

    model_lower = model.lower()
    if any(k in model_lower for k in ("gemini", "gemma", "palm")):
        return "google_genai"
    if any(k in model_lower for k in ("claude", "anthropic")):
        return "anthropic"
    return "openai"


def init_llm(model: str, api_key: str, ctx=None):
    """
    Initialize the LLM and set the appropriate env var for the provider.
    Returns (llm, env_var_name, original_key) for cleanup.
    """
    provider = _detect_provider(model)
    env_key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google_genai": "GOOGLE_API_KEY",
    }
    env_var_name = env_key_map.get(provider)

    original_key = None
    if env_var_name:
        original_key = os.environ.get(env_var_name)
        os.environ[env_var_name] = api_key

    _ctx = ctx.to_dict() if ctx else {}
    logger.info("LLM initialized", extra={"data": {
        **_ctx,
        "provider": provider,
        "model": model,
        "env_var": env_var_name,
    }})

    llm = init_chat_model(model, temperature=0.1)
    return llm, env_var_name, original_key


def restore_api_key(env_var_name, original_key):
    """Restore the original API key after agent execution."""
    if env_var_name:
        if original_key is not None:
            os.environ[env_var_name] = original_key
        else:
            os.environ.pop(env_var_name, None)


# ── Message History Builder ─────────────────────────────────────────────

def build_messages(session_id: str, query: str) -> list[dict]:
    """
    Build the message history for the agent, including the last 3 session
    interactions as context.
    """
    past_interactions = list(
        QueryHistory.objects.filter(session_id=session_id)
        .order_by("-created_at")[:3]
    )
    past_interactions.reverse()

    messages = []
    for interaction in past_interactions:
        # Avoid feeding bad fallback reports back into history
        if "couldn't generate a verbal summary" in (interaction.report or ""):
            continue
        messages.append({"role": "user", "content": interaction.query})
        messages.append({"role": "assistant", "content": interaction.report})

    messages.append({"role": "user", "content": query})

    logger.debug("Messages built", extra={"data": {
        "session_id": session_id,
        "history_count": len(past_interactions),
        "total_messages": len(messages),
    }})

    return messages


# ── Streaming Loop ──────────────────────────────────────────────────────

def stream_agent(agent, messages, session_id, result_holder: StreamResult, ctx=None):
    """
    Generator that streams the agent execution and yields SSE data chunks.
    Stores accumulated state in result_holder for post-processing.

    Yields: SSE data lines (str)
    """
    from django.core.cache import cache

    _ctx = ctx.to_dict() if ctx else {}

    full_content = ""
    full_tool_args_str = ""
    last_tool_args = {}
    last_non_empty_report = ""
    last_yielded_report = ""

    stream_start = time.time()

    try:
        for msg, metadata in agent.stream({"messages": messages}, stream_mode="messages"):
            # Check for cancellation signal
            if cache.get(f"cancel_{session_id}"):
                logger.info("Query cancelled by user", extra={"data": {
                    **_ctx,
                    "elapsed_ms": round((time.time() - stream_start) * 1000, 2),
                }})
                yield f"data: {json.dumps({'status': 'Analysis cancelled by user. Stopping backend...'})}\n\n"
                cache.delete(f"cancel_{session_id}")
                break

            if isinstance(msg, AIMessage):
                if msg.content:
                    full_content += msg.content

                # Accumulate tool call chunks (structured output streaming)
                if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
                    for chunk in msg.tool_call_chunks:
                        full_tool_args_str += chunk.get('args', '')
                        try:
                            partial_args = parse_partial_json(full_tool_args_str)
                            if isinstance(partial_args, dict) and partial_args.get('report'):
                                last_non_empty_report = partial_args['report']
                                if last_non_empty_report != last_yielded_report:
                                    last_yielded_report = last_non_empty_report
                                    yield f"data: {json.dumps({'report': last_yielded_report})}\n\n"
                        except Exception:
                            pass

                # Fallback for providers that populate tool_calls directly
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        if tc['name'] in ['AnalyticsResponse', 'structured_response']:
                            last_tool_args = tc.get('args', {})
                            if isinstance(last_tool_args, dict) and last_tool_args.get('report'):
                                last_non_empty_report = last_tool_args['report']
                                if last_non_empty_report != last_yielded_report:
                                    last_yielded_report = last_non_empty_report
                                    yield f"data: {json.dumps({'report': last_yielded_report})}\n\n"

                try:
                    if full_content:
                        partial_data = parse_partial_json(full_content)
                        if isinstance(partial_data, dict) and partial_data.get("report"):
                            last_non_empty_report = partial_data["report"]
                            if last_non_empty_report != last_yielded_report:
                                last_yielded_report = last_non_empty_report
                                yield f"data: {json.dumps({'report': last_yielded_report})}\n\n"
                except Exception:
                    pass

            # Signal specific tool calls to the frontend
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc['name'] == 'execute_read_only_sql':
                        sql = tc['args'].get('query', '')
                        yield f"data: {json.dumps({'status': f'SQL: {sql}'})}\n\n"
                    elif tc['name'] not in ['AnalyticsResponse', 'structured_response']:
                        tool_name = tc['name']
                        yield f"data: {json.dumps({'status': f'Tool: {tool_name}'})}\n\n"

    except GeneratorExit:
        logger.info("Stream generator closed (client disconnect)", extra={"data": {
            **_ctx,
            "elapsed_ms": round((time.time() - stream_start) * 1000, 2),
        }})
        return
    except Exception as e:
        logger.error("Stream loop error", exc_info=True, extra={"data": {
            **_ctx,
            "error": str(e),
            "elapsed_ms": round((time.time() - stream_start) * 1000, 2),
        }})
        yield f"data: {json.dumps({'status': f'Error in AI execution: {str(e)}'})}\n\n"

    stream_elapsed = round((time.time() - stream_start) * 1000, 2)
    logger.info("Stream completed", extra={"data": {
        **_ctx,
        "stream_time_ms": stream_elapsed,
        "content_length": len(full_content),
        "tool_args_length": len(full_tool_args_str),
        "has_report": bool(last_non_empty_report),
    }})

    # Store accumulated data in the per-request result holder
    result_holder.data = {
        "full_content": full_content,
        "full_tool_args_str": full_tool_args_str,
        "last_tool_args": last_tool_args,
        "last_non_empty_report": last_non_empty_report,
    }


# ── Result Extraction ───────────────────────────────────────────────────

def extract_final_result(stream_data: dict, tool_state: dict, ctx=None) -> dict:
    """
    Parse the accumulated stream data and tool state into the final
    structured response dict with report, chart_config, raw_data, sql_query.
    """
    full_content = stream_data.get("full_content", "")
    full_tool_args_str = stream_data.get("full_tool_args_str", "")
    last_tool_args = stream_data.get("last_tool_args", {})
    last_non_empty_report = stream_data.get("last_non_empty_report", "")

    # Recovery data from tool execution
    recovered_raw_data = tool_state.get("last_raw_data")
    recovered_sql_query = tool_state.get("last_sql_query", "")

    # Parse the structured response
    try:
        raw_text = full_tool_args_str or full_content or ""
        if raw_text.strip().startswith("{"):
            final_result = parse_partial_json(raw_text)
        elif last_tool_args:
            final_result = last_tool_args
        else:
            final_result = {"report": last_non_empty_report or raw_text or "No output generated."}
    except Exception:
        final_result = (
            last_tool_args if last_tool_args
            else {"report": last_non_empty_report or full_content or "Error parsing output"}
        )

    # Unwrap nested response structures
    ans = final_result
    if isinstance(ans, dict):
        if "structured_response" in ans:
            ans = ans["structured_response"]
        elif "output" in ans:
            ans = ans["output"]

    # Combine all executed queries with their timings
    all_queries = tool_state.get("all_sql_queries", [])
    combined_sql = ""
    if all_queries:
        for i, q_info in enumerate(all_queries):
            combined_sql += f"-- Query {i+1} (Execution Time: {q_info['time']:.3f}s)\n{q_info['query']}\n\n"

    # Extract fields
    if isinstance(ans, dict):
        report = ans.get("report") or last_non_empty_report or ""
        chart_config = ans.get("chart_config")
        raw_data = ans.get("raw_data") or recovered_raw_data or []
        sql_query = combined_sql or ans.get("sql_query") or recovered_sql_query or "No SQL queries were executed."
    else:
        report = getattr(ans, "report", "") or last_non_empty_report or ""
        chart_config = getattr(ans, "chart_config", None)
        raw_data = getattr(ans, "raw_data", []) or recovered_raw_data or []
        sql_query = combined_sql or getattr(ans, "sql_query", "") or recovered_sql_query or "No SQL queries were executed."

    # Fallback for empty report
    if (not report or report.strip() == "") and full_content:
        if full_content.strip().startswith("{"):
            try:
                pj = parse_partial_json(full_content)
                report = pj.get("report", "")
            except Exception:
                report = ""
        if not report:
            report = full_content

    if not report or report.strip() == "":
        report = "The analysis was completed, but I couldn't generate a verbal summary. Please check the charts and data below."

    _ctx = ctx.to_dict() if ctx else {}
    logger.info("Result extracted", extra={"data": {
        **_ctx,
        "report_length": len(report),
        "raw_data_rows": len(raw_data) if isinstance(raw_data, list) else 0,
        "sql_queries_count": len(all_queries),
        "has_chart": chart_config is not None,
    }})

    return {
        "report": report,
        "chart_config": chart_config,
        "raw_data": raw_data,
        "sql_query": sql_query,
    }


# ── Auto Chart Generation ──────────────────────────────────────────────

def auto_generate_chart(chart_config, raw_data) -> dict | None:
    """
    Fallback chart generation when the AI doesn't produce one.
    Only generates if the data has numeric columns and >1 row.
    """
    is_empty_chart = False
    if chart_config and isinstance(chart_config, dict):
        data_obj = chart_config.get("data", {})
        if not data_obj.get("labels") or not data_obj.get("datasets"):
            is_empty_chart = True

    if (not chart_config or is_empty_chart) and raw_data and isinstance(raw_data, list) and len(raw_data) > 1:
        try:
            keys = [k for k in raw_data[0].keys() if k != "id"]
            label_key = keys[0]
            value_keys = [k for k in keys if isinstance(raw_data[0][k], (int, float, Decimal))]

            if value_keys:
                labels = [str(row.get(label_key, "")) for row in raw_data]
                datasets = []
                for vk in value_keys[:5]:
                    data_points = [float(row.get(vk, 0)) for row in raw_data]
                    datasets.append({"label": vk.replace("_", " ").title(), "data": data_points[:30]})

                chart_type = (
                    "line" if any(k.lower() in label_key.lower() for k in ["date", "time", "month", "year"])
                    else "bar"
                )
                chart_config = {"type": chart_type, "data": {"labels": labels[:30], "datasets": datasets}}

                logger.info("Auto-generated chart", extra={"data": {
                    "chart_type": chart_type,
                    "data_points": len(labels),
                    "datasets": len(datasets),
                }})
        except Exception:
            pass

    # Final cleanup: None out empty configs
    if chart_config and isinstance(chart_config, dict) and not chart_config.get('data'):
        chart_config = None

    return chart_config
