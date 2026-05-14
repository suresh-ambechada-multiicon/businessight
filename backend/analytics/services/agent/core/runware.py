"""Runware text model integration for schema-to-SQL analytics."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from typing import Any, Generator

import httpx
from django.utils import timezone
from langchain_core.utils.json import parse_partial_json

from analytics.models import RunwareTaskLog
from analytics.schemas import AnalyticsResponse, VerifiedReportResponse
from analytics.services.logger import get_logger
from analytics.services.pipeline.serialization import deep_sanitize

logger = get_logger("agent")

RUNWARE_API_URL = "https://api.runware.ai/v1"
_DEFAULT_ANALYTICS_MAX_TOKENS = 16384
_DEFAULT_REPORT_MAX_TOKENS = 4096
_ANALYTICS_THINKING_LEVEL = "high"
_REPORT_THINKING_LEVEL = "medium"
_REQUEST_TIMEOUT_SECONDS = 180


def _strip_fenced_json(text: str) -> str:
    raw = (text or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return raw


def _parse_analytics_response(text: str) -> dict[str, Any]:
    raw = _strip_fenced_json(text)
    parsed = parse_partial_json(raw)
    if not isinstance(parsed, dict):
        parsed = json.loads(raw)
    return AnalyticsResponse.model_validate(parsed).model_dump()


def _normalize_runware_item(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or item.get("content") or "")
    if not text:
        raise RuntimeError(f"Runware response did not include generated text. Keys: {sorted(item.keys())}")
    result = _parse_analytics_response(text)
    result["_runware_usage"] = _usage_from_runware_item(item)
    return result


def _usage_from_runware_item(item: dict[str, Any]) -> dict[str, Any]:
    usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
    completion_details = usage.get("completionTokensDetails")
    if not isinstance(completion_details, dict):
        completion_details = usage.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}
    cost_breakdown = (
        usage.get("costBreakdown") if isinstance(usage.get("costBreakdown"), dict) else {}
    )
    token_breakdown = (
        cost_breakdown.get("tokens")
        if isinstance(cost_breakdown.get("tokens"), dict)
        else {}
    )
    completion_breakdown = (
        token_breakdown.get("completion")
        if isinstance(token_breakdown.get("completion"), dict)
        else {}
    )
    prompt_tokens = usage.get("promptTokens") or usage.get("prompt_tokens") or 0
    completion_tokens = (
        usage.get("completionTokens") or usage.get("completion_tokens") or 0
    )
    total_tokens = usage.get("totalTokens") or usage.get("total_tokens") or 0
    thinking_tokens = (
        usage.get("thinkingTokens")
        or usage.get("thinking_tokens")
        or completion_details.get("reasoningTokens")
        or completion_details.get("reasoning_tokens")
        or completion_breakdown.get("reasoningTokens")
        or completion_breakdown.get("reasoning_tokens")
        or 0
    )
    visible_output_tokens = (
        completion_breakdown.get("textTokens")
        or completion_breakdown.get("text_tokens")
        or completion_tokens
    )
    
    # Cost can be at top level or inside usage
    cost = item.get("cost")
    if cost is None:
        cost = usage.get("cost")
    if cost is None and isinstance(cost_breakdown, dict):
        cost = cost_breakdown.get("total")

    return {
        "input_tokens": int(prompt_tokens or 0),
        "output_tokens": int(visible_output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "thinking_tokens": int(thinking_tokens or 0),
        "estimated_cost": float(cost or 0),
    }


def _finish_reason_from_item(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("finishReason") or item.get("finish_reason") or "")


def _create_runware_log(
    *,
    query_history_id: int | None,
    ctx,
    task_uuid: str,
    phase: str,
    model_name: str,
    delivery_method: str,
    request_payload: Any,
) -> RunwareTaskLog | None:
    try:
        ctx_data = ctx.to_dict() if ctx else {}
        return RunwareTaskLog.objects.create(
            query_history_id=query_history_id,
            session_id=str(ctx_data.get("session_id") or ""),
            celery_task_id=str(ctx_data.get("task_id") or ""),
            runware_task_uuid=task_uuid,
            task_type="textInference",
            phase=phase,
            model=model_name,
            delivery_method=delivery_method,
            status="started",
            request_payload=deep_sanitize(request_payload),
        )
    except Exception:
        logger.warning("Could not create Runware task log", exc_info=True)
        return None


def _complete_runware_log(
    log: RunwareTaskLog | None,
    *,
    status: str,
    response_payload: Any | None = None,
    error_payload: Any | None = None,
    usage: dict[str, Any] | None = None,
    finish_reason: str = "",
    started_at: float | None = None,
    raw_response_text: str | None = None,
):
    if log is None:
        return
    try:
        usage = usage or {}
        log.status = status
        log.finish_reason = finish_reason or log.finish_reason
        log.response_payload = deep_sanitize(response_payload)
        log.error_payload = deep_sanitize(error_payload)
        log.usage = deep_sanitize(usage) if usage else None
        log.cost = float(usage.get("estimated_cost") or 0) if usage else None
        log.input_tokens = int(usage.get("input_tokens") or 0) if usage else None
        log.output_tokens = int(usage.get("output_tokens") or 0) if usage else None
        log.thinking_tokens = int(usage.get("thinking_tokens") or 0) if usage else None
        if raw_response_text is not None:
            log.raw_response_text = raw_response_text
        log.completed_at = timezone.now()
        if started_at is not None:
            log.duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log.save()
    except Exception:
        logger.warning("Could not update Runware task log", exc_info=True)


def _parse_verified_report(text: str) -> str:
    raw = _strip_fenced_json(text)
    try:
        parsed = parse_partial_json(raw)
        if not isinstance(parsed, dict):
            parsed = json.loads(raw)
        return str(VerifiedReportResponse.model_validate(parsed).report or "").strip()
    except Exception:
        return (text or "").strip()


# None = omit thinkingLevel entirely (last-resort fallback for Gemini)
_THINKING_FALLBACK_ORDER = ["medium", "low", None]
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2  # seconds


def _invoke_runware_http(
    *,
    model_name: str,
    api_key: str,
    system_prompt: str,
    user_query: str,
    llm_config,
    json_schema: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    thinking_level: str = _ANALYTICS_THINKING_LEVEL,
    query_history_id: int | None = None,
    ctx=None,
    phase: str = "analytics_sql",
) -> tuple[dict[str, Any], str]:
    """
    Call Runware text inference via HTTP REST API (sync delivery).

    Uses settings.systemPrompt per Runware docs instead of stuffing
    instructions into messages. Returns (response_item_dict, raw_text).

    Retries up to 3 times with exponential backoff. For Gemini "no content"
    errors, progressively lowers thinkingLevel (medium → low → omit).
    """
    resolved_max_tokens = (
        max_tokens
        or getattr(llm_config, "max_tokens", None)
        or _DEFAULT_ANALYTICS_MAX_TOKENS
    )
    temperature = getattr(llm_config, "temperature", 0.1)
    top_p = getattr(llm_config, "top_p", 1.0)
    is_gemini = "gemini" in model_name.lower()

    # Build thinking-level fallback chain starting from requested level
    if is_gemini:
        start_idx = (
            _THINKING_FALLBACK_ORDER.index(thinking_level)
            if thinking_level in _THINKING_FALLBACK_ORDER
            else 0
        )
        thinking_chain = _THINKING_FALLBACK_ORDER[start_idx:]
    else:
        thinking_chain = [thinking_level]

    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        # Pick thinking level: fall back progressively on Gemini "no content" retries
        current_thinking = thinking_chain[min(attempt, len(thinking_chain) - 1)]

        task_uuid = str(uuid.uuid4())
        request_object: dict[str, Any] = {
            "taskType": "textInference",
            "taskUUID": task_uuid,
            "model": model_name,
            "deliveryMethod": "sync",
            "numberResults": 1,
            "includeCost": True,
            "includeUsage": True,
            "messages": [
                {"role": "user", "content": user_query},
            ],
            "settings": {
                "systemPrompt": system_prompt,
                "maxTokens": resolved_max_tokens,
                "temperature": temperature,
                "topP": top_p,
            },
        }
        # Only include thinkingLevel when explicitly set (None = omit for fallback)
        if current_thinking is not None:
            request_object["settings"]["thinkingLevel"] = current_thinking
        if json_schema and not is_gemini:
            request_object["jsonSchema"] = json_schema

        started_at = time.perf_counter()
        task_log = _create_runware_log(
            query_history_id=query_history_id,
            ctx=ctx,
            task_uuid=task_uuid,
            phase=phase,
            model_name=model_name,
            delivery_method="sync",
            request_payload=[request_object],
        )

        try:
            response = httpx.post(
                RUNWARE_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=[request_object],
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            error_body = {}
            try:
                error_body = exc.response.json()
            except Exception:
                pass
            error_msg = f"Runware API HTTP {exc.response.status_code}"
            if isinstance(error_body, dict) and error_body.get("errors"):
                first_err = error_body["errors"][0]
                error_msg = f"{error_msg}: {first_err.get('message', str(first_err))}"

            _complete_runware_log(
                task_log,
                status="error",
                error_payload={
                    "message": error_msg,
                    "type": "HTTPStatusError",
                    "status_code": exc.response.status_code,
                    "body": deep_sanitize(error_body),
                },
                started_at=started_at,
            )

            # Retryable: 429 rate-limit, 503 overloaded, or Gemini "no content"
            is_retryable = exc.response.status_code in (429, 503)
            is_gemini_no_content = (
                is_gemini
                and exc.response.status_code == 400
                and ("no content" in error_msg.lower() or "no text" in error_msg.lower())
            )

            if (is_retryable or is_gemini_no_content) and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Runware request failed, retrying",
                    extra={"data": {
                        "attempt": attempt + 1,
                        "wait_s": wait,
                        "status": exc.response.status_code,
                        "thinking_level": current_thinking,
                        "error": error_msg[:200],
                    }},
                )
                last_error = RuntimeError(error_msg)
                time.sleep(wait)
                continue

            raise RuntimeError(error_msg) from exc
        except Exception as exc:
            _complete_runware_log(
                task_log,
                status="error",
                error_payload={"message": str(exc), "type": exc.__class__.__name__},
                started_at=started_at,
            )
            raise

        # Handle API-level errors in the response body
        if isinstance(body, dict) and body.get("errors"):
            first_err = body["errors"][0]
            error_msg = first_err.get("message") or str(first_err)
            _complete_runware_log(
                task_log,
                status="error",
                response_payload=deep_sanitize(body),
                error_payload={"message": error_msg, "code": first_err.get("code")},
                started_at=started_at,
            )
            raise RuntimeError(f"Runware API error: {error_msg}")

        # Parse response: {"data": [...]} or bare list
        results = body.get("data") if isinstance(body, dict) else body
        if not isinstance(results, list):
            results = [body] if isinstance(body, dict) else []

        if not results:
            error = RuntimeError("Runware returned no text response.")
            _complete_runware_log(
                task_log,
                status="error",
                response_payload=deep_sanitize(body),
                error_payload={"message": str(error), "type": error.__class__.__name__},
                started_at=started_at,
            )
            raise error

        item = results[0]
        if not isinstance(item, dict):
            item = {"text": str(item)}

        raw_text = str(item.get("text") or item.get("content") or "")
        usage = _usage_from_runware_item(item)

        _complete_runware_log(
            task_log,
            status="success",
            response_payload=deep_sanitize(body),
            usage=usage,
            finish_reason=_finish_reason_from_item(item),
            started_at=started_at,
            raw_response_text=raw_text,
        )
        return item, raw_text

    # Should not reach here, but safety net
    raise last_error or RuntimeError("Runware request failed after retries.")


def invoke_runware_analytics(
    *,
    model: str,
    api_key: str,
    formatted_prompt: str,
    user_query: str,
    llm_config,
    ctx=None,
    query_history_id: int | None = None,
    repair_context: dict[str, Any] | None = None,
    followup_context: dict[str, Any] | None = None,
    phase: str = "analytics_sql",
) -> dict[str, Any]:
    """Call a Runware text model and return a normalized AnalyticsResponse dict."""
    model_name = model.split(":", 1)[1] if ":" in model else model
    _ctx = ctx.to_dict() if ctx else {}

    logger.info(
        "Runware analytics model invoked",
        extra={"data": {**_ctx, "model": model_name}},
    )

    json_contract = AnalyticsResponse.model_json_schema()

    # Build system prompt: schema context + output instructions
    system_prompt = (
        formatted_prompt
        + "\n\nReturn ONLY valid JSON matching this schema. Do not wrap it in markdown. "
        "Every table or chart block must include a read-only SELECT sql_query. "
        "Do not include raw rows or chart data; the backend will execute SQL. "
        "Use the schema context exactly: it includes the active schema, column types, "
        "and Value Hints with sample distinct names/codes/statuses/categories. Match "
        "user terms to those values before choosing filters or joins. "
        "Avoid ID-only output: when selecting or grouping by a *_id column, also join "
        "the matching lookup/master table and include a readable name/code column if "
        "the schema provides one. "
        "For analytical or time-window questions, use multiple result_blocks when useful: "
        "overview summary, KPI/detail table blocks, raw-table explanation, useful chart "
        "blocks, and chart explanation. Tables and charts are optional; include only "
        "blocks that add evidence. Chart SQL and table SQL can be different; make chart "
        "SQL aggregated and visualization-friendly instead of reusing a raw/detail table. "
        "If a join key, category value, service value, or amount column is uncertain, "
        "bundle multiple candidate SQL table blocks in this same response rather than "
        "making one fragile guess. Use clear candidate titles and vary the join/filter "
        "strategy so the backend can execute all candidates locally and keep the one "
        "that returns evidence. "
        "Do not use canned domain wording. Titles, summaries, and SQL must come from "
        "the user's exact question and the database schema. Never mention an example "
        "domain unless it is present in the user question, schema, SQL, or executed "
        "evidence. The report structure can vary; choose only sections that fit the "
        "evidence.\n\n"
        f"JSON schema:\n{json.dumps(json_contract, separators=(',', ':'))}"
    )
    if repair_context:
        system_prompt += (
            "\n\nPrevious SQL attempt did not produce a satisfactory executable result. "
            "Review the failure/empty evidence below and return a corrected structured response. "
            "Use different joins, date/status filters, grouping columns, or amount columns when the "
            "previous query was too restrictive or selected the wrong table. Do not repeat the same SQL.\n"
            f"Repair context:\n{json.dumps(repair_context, default=str)}"
        )
    if followup_context:
        system_prompt += (
            "\n\nThe backend has executed previous SQL blocks for this same user query. "
            "Review the executed evidence below and decide whether more SQL evidence is needed "
            "for a complete, detailed answer. If the evidence is already sufficient, return valid "
            "JSON with an empty `result_blocks` array and a short report saying the evidence is sufficient. "
            "If more detail is needed, return ONLY additional `table` or `chart` result_blocks with new "
            "read-only SELECT SQL. Do not repeat any SQL already listed in `executed_sql_keys`. "
            "Do not invent raw rows or chart data.\n"
            f"Executed evidence context:\n{json.dumps(followup_context, default=str)}"
        )

    item, raw_text = _invoke_runware_http(
        model_name=model_name,
        api_key=api_key,
        system_prompt=system_prompt,
        user_query=user_query,
        llm_config=llm_config,
        json_schema=json_contract,
        max_tokens=_DEFAULT_ANALYTICS_MAX_TOKENS,
        thinking_level=_ANALYTICS_THINKING_LEVEL,
        query_history_id=query_history_id,
        ctx=ctx,
        phase=phase,
    )

    result = _normalize_runware_item(item)

    logger.info(
        "Runware analytics response parsed",
        extra={
            "data": {
                **_ctx,
                "report_length": len(str(result.get("report") or "")),
                "block_count": len(result.get("result_blocks") or []),
                "has_sql": bool(result.get("sql_query"))
                or any(
                    isinstance(block, dict) and block.get("sql_query")
                    for block in result.get("result_blocks") or []
                ),
            }
        },
    )
    return {
        "report": result.get("report") or "",
        "chart_config": None,
        "raw_data": [],
        "sql_query": result.get("sql_query") or "",
        "result_blocks": result.get("result_blocks") or [],
        "_runware_usage": result.get("_runware_usage") or {},
    }


def invoke_runware_verified_report(
    *,
    model: str,
    api_key: str,
    user_query: str,
    evidence: dict[str, Any],
    llm_config,
    ctx=None,
    query_history_id: int | None = None,
) -> str:
    """Call Runware to write a verified answer from executed SQL evidence."""
    model_name = model.split(":", 1)[1] if ":" in model else model
    _ctx = ctx.to_dict() if ctx else {}

    system_prompt = (
        "You are a senior data analyst writing the final user-facing answer. "
        "Use only the provided executed SQL evidence. Do not invent numbers. "
        "Return only JSON with a `report` markdown string. Write natural Markdown "
        "that fits the user's question and the evidence; do not use a fixed template, "
        "do not add generic headings, and do not call the output a report. "
        "Write deeper analysis when multiple evidence blocks are present: compare peaks "
        "and lows, totals, averages, period-over-period movement, concentration, and "
        "notable gaps when those facts are visible in the evidence. "
        "Keep the answer brief and explanatory. It will be shown with chart/table "
        "blocks, so describe what the displayed data says without introducing the answer. "
        "Only include sections such as key findings, ranking, trends, concentration, "
        "outliers, or limitations when they are directly supported and useful. "
        "If the user asks for a longer window but the evidence contains fewer populated "
        "periods, say the requested window and the observed populated period count clearly. "
        "If `truncated` is true and `total_count` is null, the total matching record "
        "count is unknown. Never present `loaded_sample_rows` as the total dataset size; "
        "say only that the UI shows a capped sample. "
        "When some candidate SQL blocks are empty but others return rows, ignore the empty "
        "candidates in the findings. Do not conclude that data is unavailable if any "
        "executed evidence block has rows. "
        "Do not mention domains, filters, entities, or metrics that are not present "
        "in the user question, executed SQL, or result columns."
    )
    payload = {
        "question": user_query,
        "executed_evidence": evidence,
        "response_schema": VerifiedReportResponse.model_json_schema(),
    }

    try:
        item, raw_text = _invoke_runware_http(
            model_name=model_name,
            api_key=api_key,
            system_prompt=system_prompt,
            user_query=json.dumps(payload, default=str),
            llm_config=llm_config,
            json_schema=VerifiedReportResponse.model_json_schema(),
            max_tokens=_DEFAULT_REPORT_MAX_TOKENS,
            thinking_level=_REPORT_THINKING_LEVEL,
            query_history_id=query_history_id,
            ctx=ctx,
            phase="verified_report",
        )
        report = _parse_verified_report(raw_text)
        logger.info(
            "Runware verified report written",
            extra={"data": {**_ctx, "report_length": len(report)}},
        )
        return report
    except Exception as exc:
        logger.warning(
            "Runware verified report failed",
            exc_info=True,
            extra={"data": {**_ctx, "error": str(exc)[:300]}},
        )
        return ""


def stream_runware_verified_report(
    *,
    model: str,
    api_key: str,
    user_query: str,
    evidence: dict[str, Any],
    llm_config,
    usage_sink: dict[str, Any] | None = None,
    cancel_checker: Callable[[], bool] | None = None,
    ctx=None,
    query_history_id: int | None = None,
) -> Generator[dict[str, Any], None, str]:
    """
    Stream the final evidence-based answer via Runware's HTTP SSE API.

    Yields chunks containing 'report', 'reasoning', or 'usage'.
    Returns the final full report string.
    """
    model_name = model.split(":", 1)[1] if ":" in model else model
    _ctx = ctx.to_dict() if ctx else {}
    max_tokens = getattr(llm_config, "max_tokens", None) or _DEFAULT_REPORT_MAX_TOKENS
    temperature = getattr(llm_config, "temperature", 0.1)
    top_p = getattr(llm_config, "top_p", 1.0)

    task_uuid = str(uuid.uuid4())
    system_prompt = (
        "You are a senior data analyst writing the final user-facing answer. "
        "Use only the provided executed SQL evidence. Do not invent numbers, "
        "totals, fields, labels, or trends. Write polished Markdown only. "
        "Adapt the answer to the user's question and available evidence; "
        "do not use a fixed template, do not add generic headings, and do not call "
        "the output a report. Write deeper analysis when multiple evidence "
        "blocks are present: compare peaks and lows, totals, averages, period-over-period "
        "movement, concentration, and notable gaps when those facts are visible. "
        "Keep the answer brief and explanatory. It will be shown with chart/table "
        "blocks, so describe what the displayed data says without introducing the answer. "
        "Include only sections that fit the result, such as findings, ranking, trends, "
        "comparisons, or limitations. If the user asks for a longer window but the "
        "evidence contains fewer populated periods, say the requested window and the "
        "observed populated period count clearly. "
        "If `truncated` is true and `total_count` is null, the total matching record "
        "count is unknown. Never present `loaded_sample_rows` as the total dataset size; "
        "say only that the UI shows a capped sample. "
        "When some candidate SQL blocks are empty but others return rows, ignore the empty "
        "candidates in the findings. Do not conclude that data is unavailable if any "
        "executed evidence block has rows. "
        "Do not mention domains, filters, entities, or metrics that are not present "
        "in the user question, executed SQL, or result columns. Do not include raw SQL."
    )
    payload = {
        "question": user_query,
        "executed_evidence": evidence,
    }
    stream_settings: dict[str, Any] = {
                "systemPrompt": system_prompt,
                "maxTokens": max_tokens,
                "temperature": temperature,
                "topP": top_p,
            }
    if "gemini" not in model_name.lower():
        stream_settings["thinkingLevel"] = _REPORT_THINKING_LEVEL

    request_body = [
        {
            "taskType": "textInference",
            "taskUUID": task_uuid,
            "model": model_name,
            "deliveryMethod": "stream",
            "numberResults": 1,
            "includeCost": True,
            "includeUsage": True,
            "messages": [
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
            "settings": stream_settings,
        }
    ]

    report = ""
    stream_events: list[dict[str, Any]] = []
    final_usage: dict[str, Any] = {}
    finish_reason = ""
    stream_status = "success"
    started_at = time.perf_counter()
    task_log = _create_runware_log(
        query_history_id=query_history_id,
        ctx=ctx,
        task_uuid=task_uuid,
        phase="verified_report",
        model_name=model_name,
        delivery_method="stream",
        request_payload=request_body,
    )
    logger.info(
        "Runware verified report stream started",
        extra={"data": {**_ctx, "model": model_name}},
    )
    try:
        with httpx.stream(
            "POST",
            RUNWARE_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=None,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel_checker and cancel_checker():
                    if usage_sink is not None:
                        usage_sink["_cancelled"] = True
                    logger.info(
                        "Runware verified report stream cancelled",
                        extra={"data": {**_ctx, "task_uuid": task_uuid}},
                    )
                    _complete_runware_log(
                        task_log,
                        status="cancelled",
                        response_payload={
                            "events": stream_events,
                            "final_text": report,
                        },
                        usage=final_usage,
                        finish_reason=finish_reason,
                        started_at=started_at,
                    )
                    stream_status = "cancelled"
                    break
                if not line:
                    continue
                if line.startswith(":"):
                    continue
                if line.strip() == "data: [DONE]":
                    break
                if not line.startswith("data:"):
                    continue

                item = json.loads(line.removeprefix("data:").strip())
                stream_events.append(deep_sanitize(item))
                finish_reason = _finish_reason_from_item(item) or finish_reason
                if item.get("errors"):
                    first = item["errors"][0]
                    raise RuntimeError(first.get("message") or str(first))

                usage = None
                if item.get("usage") or item.get("cost"):
                    usage = _usage_from_runware_item(item)
                    final_usage = usage
                    if usage_sink is not None:
                        # Update only non-zero values to avoid overwriting cumulative cost with zero
                        for k, v in usage.items():
                            if v:
                                usage_sink[k] = v

                delta = item.get("delta") if isinstance(item.get("delta"), dict) else {}

                # Reasoning content (thinking steps)
                reasoning = delta.get("reasoningContent") or delta.get("reasoning_content") or ""
                if reasoning:
                    yield {"reasoning": reasoning}

                # Actual report text
                text = delta.get("text") or ""
                if text:
                    report += text
                    yield {"report": report}

                if usage:
                    yield {"usage": usage}
    except Exception as exc:
        _complete_runware_log(
            task_log,
            status="error",
            response_payload={"events": stream_events, "final_text": report},
            error_payload={"message": str(exc), "type": exc.__class__.__name__},
            usage=final_usage,
            finish_reason=finish_reason,
            started_at=started_at,
        )
        raise
    else:
        if stream_status != "cancelled":
            _complete_runware_log(
                task_log,
                status="success",
                response_payload={"events": stream_events, "final_text": report},
                usage=final_usage,
                finish_reason=finish_reason,
                started_at=started_at,
            )

    logger.info(
        "Runware verified report stream completed",
        extra={"data": {**_ctx, "report_length": len(report)}},
    )
    return report.strip()
