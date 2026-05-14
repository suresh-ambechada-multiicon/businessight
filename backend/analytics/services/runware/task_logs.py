from __future__ import annotations

import time
from typing import Any

from django.utils import timezone

from analytics.models import RunwareTaskLog
from analytics.services.logger import get_logger
from analytics.services.pipeline.serialization import deep_sanitize

logger = get_logger("agent")


class RunwareTaskLogger:
    def __init__(self, *, query_history_id: int | None, ctx, task_uuid: str):
        self.query_history_id = query_history_id
        self.ctx = ctx
        self.task_uuid = task_uuid

    def start(
        self,
        *,
        phase: str,
        model_name: str,
        delivery_method: str,
        request_payload: Any,
    ) -> RunwareTaskLog | None:
        try:
            ctx_data = self.ctx.to_dict() if self.ctx else {}
            return RunwareTaskLog.objects.create(
                query_history_id=self.query_history_id,
                session_id=str(ctx_data.get("session_id") or ""),
                celery_task_id=str(ctx_data.get("task_id") or ""),
                runware_task_uuid=self.task_uuid,
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

    @staticmethod
    def complete(
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
