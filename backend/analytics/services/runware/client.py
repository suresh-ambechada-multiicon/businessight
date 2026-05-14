from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Generator
from typing import Any

import httpx

from analytics.services.logger import get_logger
from analytics.services.pipeline.serialization import deep_sanitize
from analytics.services.runware.config import (
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BACKOFF_BASE,
    RUNWARE_API_URL,
    THINKING_FALLBACK_ORDER,
)
from analytics.services.runware.task_logs import RunwareTaskLogger
from analytics.services.runware.usage import (
    finish_reason_from_item,
    usage_from_runware_item,
)

logger = get_logger("agent")


class RunwareTextClient:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        llm_config,
        ctx=None,
        query_history_id: int | None = None,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.llm_config = llm_config
        self.ctx = ctx
        self.query_history_id = query_history_id

    @property
    def _is_gemini(self) -> bool:
        return "gemini" in self.model_name.lower()

    def invoke_sync(
        self,
        *,
        system_prompt: str,
        user_query: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
        thinking_level: str | None,
        phase: str,
    ) -> tuple[dict[str, Any], str]:
        thinking_chain = self._thinking_chain(thinking_level)
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            current_thinking = thinking_chain[min(attempt, len(thinking_chain) - 1)]
            task_uuid = str(uuid.uuid4())
            request_object = self._request_object(
                task_uuid=task_uuid,
                delivery_method="sync",
                system_prompt=system_prompt,
                user_query=user_query,
                max_tokens=max_tokens,
                thinking_level=current_thinking,
                json_schema=json_schema,
            )
            started_at = time.perf_counter()
            task_log = RunwareTaskLogger(
                query_history_id=self.query_history_id,
                ctx=self.ctx,
                task_uuid=task_uuid,
            ).start(
                phase=phase,
                model_name=self.model_name,
                delivery_method="sync",
                request_payload=[request_object],
            )

            try:
                response = httpx.post(
                    RUNWARE_API_URL,
                    headers=self._headers(),
                    json=[request_object],
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPStatusError as exc:
                error_msg, error_body = self._http_error_message(exc)
                RunwareTaskLogger.complete(
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
                if self._should_retry(exc.response.status_code, error_msg, attempt):
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        "Runware request failed, retrying",
                        extra={
                            "data": {
                                "attempt": attempt + 1,
                                "wait_s": wait,
                                "status": exc.response.status_code,
                                "thinking_level": current_thinking,
                                "error": error_msg[:200],
                            }
                        },
                    )
                    last_error = RuntimeError(error_msg)
                    time.sleep(wait)
                    continue
                raise RuntimeError(error_msg) from exc
            except Exception as exc:
                RunwareTaskLogger.complete(
                    task_log,
                    status="error",
                    error_payload={"message": str(exc), "type": exc.__class__.__name__},
                    started_at=started_at,
                )
                raise

            item, raw_text = self._first_response_item(body, task_log, started_at)
            usage = usage_from_runware_item(item)
            RunwareTaskLogger.complete(
                task_log,
                status="success",
                response_payload=deep_sanitize(body),
                usage=usage,
                finish_reason=finish_reason_from_item(item),
                started_at=started_at,
                raw_response_text=raw_text,
            )
            return item, raw_text

        raise last_error or RuntimeError("Runware request failed after retries.")

    def stream(
        self,
        *,
        system_prompt: str,
        user_query: str,
        max_tokens: int,
        thinking_level: str | None,
        usage_sink: dict[str, Any] | None = None,
        cancel_checker: Callable[[], bool] | None = None,
        phase: str = "verified_report",
    ) -> Generator[dict[str, Any], None, str]:
        task_uuid = str(uuid.uuid4())
        request_body = [
            self._request_object(
                task_uuid=task_uuid,
                delivery_method="stream",
                system_prompt=system_prompt,
                user_query=user_query,
                max_tokens=max_tokens,
                thinking_level=None if self._is_gemini else thinking_level,
                json_schema=None,
            )
        ]
        report = ""
        stream_events: list[dict[str, Any]] = []
        final_usage: dict[str, Any] = {}
        finish_reason = ""
        stream_status = "success"
        started_at = time.perf_counter()
        task_log = RunwareTaskLogger(
            query_history_id=self.query_history_id,
            ctx=self.ctx,
            task_uuid=task_uuid,
        ).start(
            phase=phase,
            model_name=self.model_name,
            delivery_method="stream",
            request_payload=request_body,
        )

        try:
            with httpx.stream(
                "POST",
                RUNWARE_API_URL,
                headers=self._headers(),
                json=request_body,
                timeout=None,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if cancel_checker and cancel_checker():
                        if usage_sink is not None:
                            usage_sink["_cancelled"] = True
                        RunwareTaskLogger.complete(
                            task_log,
                            status="cancelled",
                            response_payload={"events": stream_events, "final_text": report},
                            usage=final_usage,
                            finish_reason=finish_reason,
                            started_at=started_at,
                        )
                        stream_status = "cancelled"
                        break
                    if not line or line.startswith(":") or line.strip() == "data: [DONE]":
                        if line and line.strip() == "data: [DONE]":
                            break
                        continue
                    if not line.startswith("data:"):
                        continue

                    item = json.loads(line.removeprefix("data:").strip())
                    stream_events.append(deep_sanitize(item))
                    finish_reason = finish_reason_from_item(item) or finish_reason
                    if item.get("errors"):
                        first = item["errors"][0]
                        raise RuntimeError(first.get("message") or str(first))

                    usage = None
                    if item.get("usage") or item.get("cost"):
                        usage = usage_from_runware_item(item)
                        final_usage = usage
                        if usage_sink is not None:
                            for key, value in usage.items():
                                if value:
                                    usage_sink[key] = value

                    delta = item.get("delta") if isinstance(item.get("delta"), dict) else {}
                    reasoning = delta.get("reasoningContent") or delta.get("reasoning_content") or ""
                    if reasoning:
                        yield {"reasoning": reasoning}

                    text = delta.get("text") or ""
                    if text:
                        report += text
                        yield {"report": report}

                    if usage:
                        yield {"usage": usage}
        except Exception as exc:
            RunwareTaskLogger.complete(
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
                RunwareTaskLogger.complete(
                    task_log,
                    status="success",
                    response_payload={"events": stream_events, "final_text": report},
                    usage=final_usage,
                    finish_reason=finish_reason,
                    started_at=started_at,
                )
        return report.strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _thinking_chain(self, thinking_level: str | None) -> list[str | None]:
        if not self._is_gemini:
            return [thinking_level]
        start_idx = (
            THINKING_FALLBACK_ORDER.index(thinking_level)
            if thinking_level in THINKING_FALLBACK_ORDER
            else 0
        )
        return THINKING_FALLBACK_ORDER[start_idx:]

    def _request_object(
        self,
        *,
        task_uuid: str,
        delivery_method: str,
        system_prompt: str,
        user_query: str,
        max_tokens: int,
        thinking_level: str | None,
        json_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        request_object: dict[str, Any] = {
            "taskType": "textInference",
            "taskUUID": task_uuid,
            "model": self.model_name,
            "deliveryMethod": delivery_method,
            "numberResults": 1,
            "includeCost": True,
            "includeUsage": True,
            "messages": [{"role": "user", "content": user_query}],
            "settings": {
                "systemPrompt": system_prompt,
                "maxTokens": max_tokens,
                "temperature": getattr(self.llm_config, "temperature", 0.1),
                "topP": getattr(self.llm_config, "top_p", 1.0),
            },
        }
        if thinking_level is not None:
            request_object["settings"]["thinkingLevel"] = thinking_level
        if json_schema and not self._is_gemini:
            request_object["jsonSchema"] = json_schema
        return request_object

    def _http_error_message(self, exc: httpx.HTTPStatusError) -> tuple[str, dict[str, Any]]:
        error_body: dict[str, Any] = {}
        try:
            error_body = exc.response.json()
        except Exception:
            pass
        error_msg = f"Runware API HTTP {exc.response.status_code}"
        if isinstance(error_body, dict) and error_body.get("errors"):
            first_err = error_body["errors"][0]
            error_msg = f"{error_msg}: {first_err.get('message', str(first_err))}"
        return error_msg, error_body

    def _should_retry(self, status_code: int, error_msg: str, attempt: int) -> bool:
        if attempt >= MAX_RETRIES - 1:
            return False
        is_retryable = status_code in (429, 503)
        is_gemini_no_content = (
            self._is_gemini
            and status_code == 400
            and ("no content" in error_msg.lower() or "no text" in error_msg.lower())
        )
        return is_retryable or is_gemini_no_content

    @staticmethod
    def _first_response_item(
        body: Any,
        task_log,
        started_at: float,
    ) -> tuple[dict[str, Any], str]:
        if isinstance(body, dict) and body.get("errors"):
            first_err = body["errors"][0]
            error_msg = first_err.get("message") or str(first_err)
            RunwareTaskLogger.complete(
                task_log,
                status="error",
                response_payload=deep_sanitize(body),
                error_payload={"message": error_msg, "code": first_err.get("code")},
                started_at=started_at,
            )
            raise RuntimeError(f"Runware API error: {error_msg}")

        results = body.get("data") if isinstance(body, dict) else body
        if not isinstance(results, list):
            results = [body] if isinstance(body, dict) else []
        if not results:
            error = RuntimeError("Runware returned no text response.")
            RunwareTaskLogger.complete(
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
        return item, raw_text
