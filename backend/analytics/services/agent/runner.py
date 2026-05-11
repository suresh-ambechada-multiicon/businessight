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
from analytics.services.logger import RequestContext, get_logger

logger = get_logger("agent")


# ── Thread-safe result container ────────────────────────────────────────


class StreamResult:
    """Mutable container for streaming results. One per request — thread-safe."""

    def __init__(self):
        self.data: dict = {}
        self.has_error: bool = False
        self.trace: list[dict] = []


# ── Schema Context Builder ──────────────────────────────────────────────


def build_schema_context(
    usable_tables: list[str],
    active_schema,
    db,
    ctx=None,
    *,
    table_rank_order: list[str] | None = None,
    skip_full_context_cache: bool = False,
) -> str:
    """
    Build the schema context string that gets injected into the system prompt.
    For small table counts, include full column details.
    For large counts, just list names and let the AI use tools.
    
    Uses Redis caching to avoid re-inspecting columns on every request.
    """
    from analytics.services.cache import (
        get_cached_schema_context, set_cached_schema_context,
        get_cached_column_info, set_cached_column_info,
    )

    db_uri_hash = ctx.db_uri_hash if ctx else ""

    # 1. Try full context cache first (fastest path) — skipped when ranking is query-specific
    if db_uri_hash and not skip_full_context_cache:
        cached = get_cached_schema_context(db_uri_hash)
        if cached is not None:
            logger.info("Schema context from cache", extra={"data": {
                **(ctx.to_dict() if ctx else {}),
                "table_count": len(usable_tables),
                "source": "redis_cache",
            }})
            return cached

    # 2. Build context
    def _get_table_columns(table_name: str) -> str:
        """Get column info for a single table, with per-table caching."""
        # Check per-table cache
        if db_uri_hash:
            cached_cols = get_cached_column_info(db_uri_hash, table_name)
            if cached_cols is not None:
                return cached_cols

        # Try fast MSSQL path
        col_str = ""
        try:
            if hasattr(db, '_engine') and "mssql" in db._engine.url.drivername:
                from sqlalchemy import text
                with db._engine.connect() as conn:
                    full_name = f"{active_schema}.{table_name}" if active_schema else table_name
                    result = conn.execute(text(
                        f"SELECT c.name, t.name as type_name "
                        f"FROM sys.columns c "
                        f"JOIN sys.types t ON c.user_type_id = t.user_type_id "
                        f"WHERE c.object_id = OBJECT_ID('{full_name}')"
                    ))
                    cols = [f"{row[0]} {row[1]}" for row in result]
                    if cols:
                        col_str = f"Table '{table_name}' columns: {', '.join(cols)}"
        except Exception:
            pass

        # Fallback to SQLAlchemy inspector
        if not col_str:
            try:
                from sqlalchemy import inspect as sa_inspect
                db_inspector = sa_inspect(db._engine)
                columns = db_inspector.get_columns(table_name, schema=db._schema)
                cols_str = ", ".join([f"{c['name']} {str(c['type'])}" for c in columns])
                col_str = f"Table '{table_name}' columns: {cols_str}"
            except Exception:
                col_str = f"Table '{table_name}': (schema unavailable)"

        # Cache per-table result
        if db_uri_hash and col_str:
            set_cached_column_info(db_uri_hash, table_name, col_str)

        return col_str

    schema_context = ""
    if active_schema:
        schema_context += f"Active Schema: {active_schema} (Prefix tables with this schema if required by dialect)\n\n"

    rank = table_rank_order or usable_tables
    top_set: set[str] = set()
    if len(usable_tables) > 10 and table_rank_order:
        # Detailed columns for the top-ranked tables first (query-aware)
        top_n = 12 if len(usable_tables) > 50 else 8
        top = [t for t in rank if t in usable_tables][:top_n]
        top_set = set(top)
        if top:
            lines = [_get_table_columns(t) for t in top]
            schema_context += (
                "Prioritized tables (retrieval-ranked for this question; inspect these first):\n"
                + "\n".join(lines)
                + "\n\n"
            )

    if len(usable_tables) <= 10:
        lines = [_get_table_columns(t) for t in usable_tables]
        schema_context += "Detailed Schema:\n" + "\n".join(lines)
    elif len(usable_tables) <= 50:
        rest = [t for t in usable_tables if t not in top_set]
        if top_set:
            schema_context += (
                f"Other tables in this database ({len(rest)}): {', '.join(rest)}\n"
                f"Use `search_schema` or `get_table_info` for columns on those tables."
            )
        else:
            schema_context += (
                f"Tables: {', '.join(usable_tables)}\n"
                f"Use `search_schema` or `get_table_info` to find specific columns."
            )
    else:
        rest = [t for t in usable_tables if t not in top_set]
        tail = ", ".join(rest[:80])
        more = f" ... and {len(rest) - 80} more" if len(rest) > 80 else ""
        schema_context += (
            f"Database contains {len(usable_tables)} business tables.\n"
            f"Other table names (sample): {tail}{more}\n"
            f"Use the `search_schema` tool with concrete keywords; DO NOT guess table names.\n"
        )

    # 3. Cache the full context (skip when query-specific ranking was applied)
    if db_uri_hash and not skip_full_context_cache:
        set_cached_schema_context(db_uri_hash, schema_context)

    _ctx = ctx.to_dict() if ctx else {}
    if table_rank_order and len(usable_tables) > 10:
        mode = "ranked_large" if len(usable_tables) > 50 else "ranked_medium"
    elif len(usable_tables) <= 10:
        mode = "detailed"
    elif len(usable_tables) > 50:
        mode = "summary"
    else:
        mode = "names_only"
    logger.info(
        "Schema context built",
        extra={
            "data": {
                **_ctx,
                "table_count": len(usable_tables),
                "mode": mode,
                "context_length": len(schema_context),
            }
        },
    )

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


def init_llm(model: str, api_key: str, llm_config, ctx=None):
    """
    Initialize the LLM passing the API key and dynamic configs.
    """
    provider = _detect_provider(model)

    _ctx = ctx.to_dict() if ctx else {}
    logger.info(
        "LLM initialized",
        extra={
            "data": {
                **_ctx,
                "provider": provider,
                "model": model,
            }
        },
    )

    model_kwargs = {
        "api_key": api_key,
        "temperature": getattr(llm_config, "temperature", 0.1),
    }

    max_tokens = getattr(llm_config, "max_tokens", None)
    if max_tokens:
        model_kwargs["max_tokens"] = max_tokens

    top_p = getattr(llm_config, "top_p", 1.0)
    if top_p != 1.0:
        model_kwargs["top_p"] = top_p

    # Disable SDK retries so we fail fast on 429 rate limits
    model_kwargs["max_retries"] = 0

    if provider == "google_genai":
        model_kwargs["google_api_key"] = api_key
    elif provider == "anthropic":
        model_kwargs["anthropic_api_key"] = api_key

    llm = init_chat_model(model, **model_kwargs)
    return llm


# ── Message History Builder ─────────────────────────────────────────────


def build_messages(session_id: str, query: str) -> list[dict]:
    """
    Build the message history for the agent, including the last 3 session
    interactions as context. Excludes in-flight queries (report='Analyzing...')
    and failed fallback reports.
    """
    past_interactions = list(
        QueryHistory.objects.filter(session_id=session_id)
        .exclude(report="Analyzing...")  # Exclude current in-flight query
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

    logger.debug(
        "Messages built",
        extra={
            "data": {
                "session_id": session_id,
                "history_count": len(past_interactions),
                "total_messages": len(messages),
            }
        },
    )

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
        for msg, metadata in agent.stream(
            {"messages": messages},
            stream_mode="messages",
            config={"recursion_limit": 100},  # Increased for complex analytical queries
        ):
            # Check for cancellation signal
            if cache.get(f"cancel_{session_id}"):
                logger.info(
                    "Query cancelled by user",
                    extra={
                        "data": {
                            **_ctx,
                            "elapsed_ms": round((time.time() - stream_start) * 1000, 2),
                        }
                    },
                )
                yield {
                    "event": "status",
                    "data": {
                        "message": "Analysis cancelled by user. Stopping backend..."
                    },
                }
                cache.delete(f"cancel_{session_id}")
                break

            if isinstance(msg, AIMessage):
                if msg.content:
                    if isinstance(msg.content, list):
                        for part in msg.content:
                            if isinstance(part, dict) and "text" in part:
                                full_content += part["text"]
                            elif isinstance(part, str):
                                full_content += part
                    else:
                        full_content += msg.content

                # Accumulate tool call chunks (structured output streaming)
                if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
                    for chunk in msg.tool_call_chunks:
                        full_tool_args_str += chunk.get("args", "")
                        try:
                            partial_args = parse_partial_json(full_tool_args_str)
                            if isinstance(partial_args, dict) and partial_args.get(
                                "report"
                            ):
                                last_non_empty_report = partial_args["report"]
                                if last_non_empty_report != last_yielded_report:
                                    last_yielded_report = last_non_empty_report
                                    yield {
                                        "event": "report",
                                        "data": {
                                            "content": last_yielded_report,
                                            "partial": True,
                                        },
                                    }
                        except Exception:
                            pass

                # Fallback for providers that populate tool_calls directly
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        if tc["name"] in ["AnalyticsResponse", "structured_response"]:
                            last_tool_args = tc.get("args", {})
                            if isinstance(last_tool_args, dict) and last_tool_args.get(
                                "report"
                            ):
                                last_non_empty_report = last_tool_args["report"]
                                if last_non_empty_report != last_yielded_report:
                                    last_yielded_report = last_non_empty_report
                                    yield {
                                        "event": "report",
                                        "data": {
                                            "content": last_yielded_report,
                                            "partial": True,
                                        },
                                    }

                try:
                    if full_content:
                        partial_data = parse_partial_json(full_content)
                        if isinstance(partial_data, dict) and partial_data.get(
                            "report"
                        ):
                            last_non_empty_report = partial_data["report"]
                            if last_non_empty_report != last_yielded_report:
                                last_yielded_report = last_non_empty_report
                                yield {
                                    "event": "report",
                                    "data": {
                                        "content": last_yielded_report,
                                        "partial": True,
                                    },
                                }
                except Exception:
                    pass

            # Signal specific tool calls to the frontend
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    raw_args = tc.get("args") or {}
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args) if raw_args.strip() else {}
                        except Exception:
                            args = {}
                    else:
                        args = raw_args if isinstance(raw_args, dict) else {}
                    if tc["name"] == "execute_read_only_sql":
                        sql = args.get("query", "")
                        result_holder.trace.append(
                            {
                                "t": time.time(),
                                "name": tc["name"],
                                "sql_preview": (sql or "")[:500],
                            }
                        )
                        yield {
                            "event": "tool",
                            "data": {"name": tc["name"], "args": {"query": sql}},
                        }
                    elif tc["name"] not in ["AnalyticsResponse", "structured_response"]:
                        tool_name = tc["name"]
                        result_holder.trace.append(
                            {"t": time.time(), "name": tool_name}
                        )
                        yield {"event": "tool", "data": {"name": tool_name}}

    except GeneratorExit:
        logger.info(
            "Stream generator closed (client disconnect)",
            extra={
                "data": {
                    **_ctx,
                    "elapsed_ms": round((time.time() - stream_start) * 1000, 2),
                }
            },
        )
        return
    except Exception as e:
        err_msg = str(e)
        # LangGraph recursion limit hit: gracefully fall through with whatever we have
        if "GraphRecursionError" in type(e).__name__ or "recursion limit" in err_msg.lower():
            logger.warning(
                "Agent hit recursion limit, using accumulated results",
                extra={"data": {**_ctx, "elapsed_ms": round((time.time() - stream_start) * 1000, 2)}},
            )
            # Don't set has_error — we have good data, just too many steps
        else:
            result_holder.has_error = True
            if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                err_msg = "Your requests are exhausted. Please check your plan or try again later."
            
            logger.error(
                "Stream loop error",
                exc_info=True,
                extra={
                    "data": {
                        **_ctx,
                        "error": str(e),
                        "elapsed_ms": round((time.time() - stream_start) * 1000, 2),
                    }
                },
            )
            yield {
                "event": "error",
                "data": {"message": f"Error: {err_msg}"},
            }

    stream_elapsed = round((time.time() - stream_start) * 1000, 2)
    logger.info(
        "Stream completed",
        extra={
            "data": {
                **_ctx,
                "stream_time_ms": stream_elapsed,
                "content_length": len(full_content),
                "tool_args_length": len(full_tool_args_str),
                "has_report": bool(last_non_empty_report),
            }
        },
    )

    # Store accumulated data in the per-request result holder
    result_holder.data = {
        "full_content": full_content,
        "full_tool_args_str": full_tool_args_str,
        "last_tool_args": last_tool_args,
        "last_non_empty_report": last_non_empty_report,
        "trace": list(getattr(result_holder, "trace", []) or []),
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
    # Prefer best_raw_data (largest result set) so aggregation queries don't
    # overwrite the actual list data the user wanted to see
    recovered_raw_data = tool_state.get("best_raw_data") or tool_state.get("last_raw_data")
    recovered_sql_query = tool_state.get("last_sql_query", "")

    # Parse the structured response
    try:
        raw_text = full_tool_args_str or full_content or ""
        if raw_text.strip().startswith("{"):
            final_result = parse_partial_json(raw_text)
        elif last_tool_args:
            final_result = last_tool_args
        else:
            final_result = {
                "report": last_non_empty_report or raw_text or "No output generated."
            }
    except Exception:
        final_result = (
            last_tool_args
            if last_tool_args
            else {
                "report": last_non_empty_report
                or full_content
                or "Error parsing output"
            }
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
            combined_sql += f"-- Query {i + 1} (Execution Time: {q_info['time']:.3f}s)\n{q_info['query']}\n\n"

    # Enrich chart_config with axis labels if missing
    if isinstance(ans, dict):
        chart_config = ans.get("chart_config")
        if chart_config and isinstance(chart_config, dict):
            raw_data = ans.get("raw_data") or recovered_raw_data or []
            if raw_data and not chart_config.get("x_label"):
                keys = [k for k in raw_data[0].keys() if k != "id"]
                chart_config["x_label"] = (
                    keys[0].replace("_", " ").title() if keys else "Items"
                )
            if raw_data and not chart_config.get("y_label"):
                datasets = chart_config.get("data", {}).get("datasets", [])
                chart_config["y_label"] = (
                    datasets[0].get("label") if datasets else "Value"
                )
            ans["chart_config"] = chart_config

    # Extract fields
    if isinstance(ans, dict):
        report = ans.get("report") or last_non_empty_report or ""
        chart_config = ans.get("chart_config")
        
        # Get explicit sql_query from AI if provided, otherwise fallback
        sql_query = ans.get("sql_query") or recovered_sql_query or ""
        
        # Determine the most accurate raw data
        raw_data = ans.get("raw_data")
        if not raw_data:
            normalized_sql = sql_query.strip().lower()
            if normalized_sql and normalized_sql in tool_state.get("query_cache", {}):
                raw_data = tool_state["query_cache"][normalized_sql]
            else:
                raw_data = tool_state.get("last_raw_data") or []
        
        if not sql_query:
            sql_query = combined_sql or "No SQL queries were executed."
    else:
        report = getattr(ans, "report", "") or last_non_empty_report or ""
        chart_config = getattr(ans, "chart_config", None)
        
        sql_query = getattr(ans, "sql_query", "") or recovered_sql_query or ""
        
        raw_data = getattr(ans, "raw_data", [])
        if not raw_data:
            normalized_sql = sql_query.strip().lower()
            if normalized_sql and normalized_sql in tool_state.get("query_cache", {}):
                raw_data = tool_state["query_cache"][normalized_sql]
            else:
                raw_data = tool_state.get("last_raw_data") or []
        
        if not sql_query:
            sql_query = combined_sql or "No SQL queries were executed."

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
        # Generate a basic report from available data
        if raw_data and isinstance(raw_data, list) and len(raw_data) > 0:
            row_count = len(raw_data)
            cols = list(raw_data[0].keys()) if raw_data else []
            
            # Check if data looks aggregated (fewer rows with numeric values)
            is_aggregated = row_count <= 30 and any(isinstance(raw_data[0].get(c), (int, float)) for c in cols)
            
            if is_aggregated:
                report = f"Analysis completed. Found {row_count} data points across columns: {', '.join(cols[:5])}"
                if len(cols) > 5:
                    report += f" and {len(cols) - 5} more"
                
                # Add basic statistics if numeric columns exist
                num_cols = [c for c in cols if isinstance(raw_data[0].get(c), (int, float))]
                if num_cols:
                    report += f"\n\nNumeric columns analyzed: {', '.join(num_cols[:3])}"
            else:
                report = f"Query returned {row_count} records. Data columns: {', '.join(cols[:6])}"
                if len(cols) > 6:
                    report += f" and {len(cols) - 6} more"
        else:
            report = "The analysis was completed, but I couldn't generate a verbal summary. Please check the charts and data below."

    _ctx = ctx.to_dict() if ctx else {}
    logger.info(
        "Result extracted",
        extra={
            "data": {
                **_ctx,
                "report_length": len(report),
                "raw_data_rows": len(raw_data) if isinstance(raw_data, list) else 0,
                "sql_queries_count": len(all_queries),
                "has_chart": chart_config is not None,
            }
        },
    )

    return {
        "report": report,
        "chart_config": chart_config,
        "raw_data": raw_data,
        "sql_query": sql_query,
    }


# ── Auto Chart Generation ──────────────────────────────────────────────

def _is_flag_or_boolean_column(key: str, sample_values: list) -> bool:
    """Check if a column is a boolean flag that shouldn't be charted."""
    flag_prefixes = ("is_", "has_", "can_", "should_", "was_", "did_")
    flag_names = ("active", "blocked", "deleted", "enabled", "archived", "verified", "status")
    key_lower = key.lower()

    if any(key_lower.startswith(p) for p in flag_prefixes):
        return True
    if key_lower in flag_names:
        return True

    # Check if all values are 0/1 or True/False
    unique_vals = set(sample_values)
    if unique_vals <= {0, 1, 0.0, 1.0, True, False, None}:
        return True

    return False


def _is_id_or_key_column(key: str) -> bool:
    """Check if a column is an ID/key that shouldn't be charted."""
    key_lower = key.lower()
    if key_lower == "id" or key_lower.endswith("_id") or key_lower.endswith("_pk"):
        return True
    if key_lower in ("pk", "key", "uuid", "guid"):
        return True
    return False


def _validate_chart_config(chart_config: dict | None, raw_data: list | None) -> dict | None:
    """
    Validate and clean a chart config (AI-generated or auto-generated).
    Removes useless datasets (no variance, boolean flags) and returns None
    if no valid datasets remain.
    """
    if not chart_config or not isinstance(chart_config, dict):
        return chart_config

    data_obj = chart_config.get("data", {})
    if not data_obj:
        return None

    datasets = data_obj.get("datasets", [])
    labels = data_obj.get("labels", [])

    if not datasets or not labels:
        return None

    # Get sample values from raw_data for flag detection
    sample_values_map = {}
    if raw_data and isinstance(raw_data, list) and len(raw_data) > 0:
        for key in raw_data[0]:
            sample_values_map[key] = [row.get(key) for row in raw_data[:50]]

    # Filter out useless datasets
    valid_datasets = []
    for ds in datasets:
        label = ds.get("label", "")
        data_points = ds.get("data", [])

        # Skip if no data
        if not data_points:
            continue

        # Skip if no variance (all same value)
        numeric_points = [p for p in data_points if isinstance(p, (int, float))]
        if numeric_points and len(set(numeric_points)) <= 1:
            continue

        # Skip boolean/flag columns
        original_key = label.lower().replace(" ", "_")
        sample = sample_values_map.get(original_key, numeric_points)
        if _is_flag_or_boolean_column(original_key, sample):
            continue

        # Skip ID columns
        if _is_id_or_key_column(original_key):
            continue

        valid_datasets.append(ds)

    if not valid_datasets:
        return None

    chart_config["data"]["datasets"] = valid_datasets
    return chart_config


def auto_generate_chart(chart_config, raw_data, query="") -> dict | None:
    """
    Fallback chart generation when the AI doesn't produce one.
    
    KEY PRINCIPLE: Only auto-generate charts from AGGREGATED data (few rows 
    with clear categories + numeric values). NEVER chart raw individual records
    (e.g. 1000 agent rows) — that data belongs in the data grid, not a chart.
    
    The AI should generate chart_config itself for analytical queries since
    only the AI understands what the user asked for.
    """
    # First validate any AI-generated chart
    if chart_config and isinstance(chart_config, dict):
        data_obj = chart_config.get("data", {})
        has_content = data_obj.get("labels") and data_obj.get("datasets")
        if has_content:
            # AI generated a chart — validate it (remove flag/boolean datasets)
            return _validate_chart_config(chart_config, raw_data)

    # Check if user explicitly asked for a chart
    is_explicit_request = any(
        word in (query or "").lower()
        for word in ["chart", "graph", "plot", "visualize"]
    )

    if not raw_data or not isinstance(raw_data, list) or len(raw_data) < 2:
        return None

    # Detect if data is aggregated vs individual records
    num_rows = len(raw_data)

    try:
        all_keys = list(raw_data[0].keys())

        # Find label key (first non-ID string column)
        label_key = None
        for k in all_keys:
            if _is_id_or_key_column(k):
                continue
            sample_val = raw_data[0].get(k)
            if isinstance(sample_val, str):
                label_key = k
                break
        if not label_key:
            label_key = next((k for k in all_keys if not _is_id_or_key_column(k)), all_keys[0])

        # Find chartable numeric columns
        value_keys = []
        for k in all_keys:
            if _is_id_or_key_column(k) or k == label_key:
                continue
            sample_val = raw_data[0].get(k)
            if not isinstance(sample_val, (int, float, Decimal)):
                continue
            sample_values = [row.get(k) for row in raw_data[:50]]
            if _is_flag_or_boolean_column(k, sample_values):
                continue
            value_keys.append(k)

        if not value_keys:
            return None

        # Aggregate data: sum numeric values for duplicate labels
        from collections import OrderedDict
        agg: dict[str, dict[str, float]] = OrderedDict()
        for row in raw_data:
            lbl = str(row.get(label_key, ""))
            if lbl not in agg:
                agg[lbl] = {vk: 0.0 for vk in value_keys}
            for vk in value_keys:
                agg[lbl][vk] += float(row.get(vk, 0) or 0)

        labels = list(agg.keys())[:30]
        datasets = []
        for vk in value_keys[:5]:
            data_points = [agg[lbl][vk] for lbl in labels]
            if len(set(data_points)) > 1:
                datasets.append({
                    "label": vk.replace("_", " ").title(),
                    "data": data_points,
                })

        if not datasets:
            return None

        chart_type = (
            "line"
            if any(k.lower() in label_key.lower() for k in ["date", "time", "month", "year"])
            else "bar"
        )
        chart_config = {
            "type": chart_type,
            "x_label": label_key.replace("_", " ").title(),
            "y_label": value_keys[0].replace("_", " ").title() if len(value_keys) == 1 else "Value",
            "data": {"labels": labels, "datasets": datasets},
        }

        logger.info("Auto-generated chart", extra={"data": {
            "chart_type": chart_type, "data_points": len(labels), "datasets": len(datasets),
        }})

    except Exception:
        pass

    # Final cleanup
    if chart_config and isinstance(chart_config, dict) and not chart_config.get("data"):
        chart_config = None

    return chart_config

