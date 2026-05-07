"""
Analytics API endpoints.

Three endpoint groups:
- Query:    POST /api/query/, GET /api/stream/{task_id}/
- History:  GET /api/sessions/, GET /api/history/, GET /api/history/{id}/data/
- Prompts:  CRUD /api/prompts/
- Config:   GET /api/models/
"""

import json

import redis
from celery.result import AsyncResult
from django.conf import settings
from django.core.cache import cache
from django.http import StreamingHttpResponse
from ninja import NinjaAPI

from analytics.models import QueryHistory
from analytics.schemas import (
    AnalyticsRequest,
    AnalyticsResponse,
    SavedPromptCreate,
    SavedPromptUpdate,
)
from analytics.services import process_analytics_query
from analytics.services.cache import get_db_uri_hash
from analytics.services.llm_config import MODEL_REGISTRY
from analytics.services.logger import RequestContext, get_logger
from analytics.tasks import process_query_task

api = NinjaAPI()
logger = get_logger("api")


# ── Helpers ─────────────────────────────────────────────────────────────


def _get_client_ip(request) -> str:
    """Extract client IP from the request, handling proxy headers."""
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _get_redis():
    """Get a Redis client for stream / heartbeat operations."""
    return redis.from_url(settings.CELERY_BROKER_URL)


# ── Config ──────────────────────────────────────────────────────────────


@api.get("/models/")
def list_models(request):
    return [
        {
            "id": model_id,
            "provider": config.provider,
            "name": model_id.split(":")[-1].replace("-", " ").title(),
        }
        for model_id, config in MODEL_REGISTRY.items()
    ]


# ── Query ───────────────────────────────────────────────────────────────


@api.post("/query/")
def query_analytics(request, payload: AnalyticsRequest):
    """Enqueue an analytics task and return the Celery task ID."""
    task = process_query_task.delay(payload.dict(), _get_client_ip(request))
    return {"task_id": task.id}


@api.get("/stream/{task_id}/")
def stream_results(request, task_id: str):
    """SSE endpoint — reads from the Redis Stream written by the Celery worker."""

    def event_stream():
        import time as _time

        redis_client = _get_redis()
        stream_key = f"stream:{task_id}"

        # Pure Redis Stream approach — no Pub/Sub, no race condition.
        # Start from "0" to replay ALL messages already written,
        # then XREAD BLOCK for new ones.
        last_id = "0"
        deadline = _time.time() + 310  # Hard timeout matching Celery time_limit

        while _time.time() < deadline:
            result = redis_client.xread(
                {stream_key: last_id}, block=2000, count=50
            )
            if not result:
                # No new messages — check if worker is still alive
                if last_id != "0" and not redis_client.exists(
                    f"heartbeat:{task_id}"
                ):
                    yield f'data: {json.dumps({"event": "error", "data": {"message": "Analysis process was interrupted."}})}\n\n'
                    return
                continue

            for _key, messages in result:
                for entry_id, fields in messages:
                    last_id = entry_id
                    data_str = fields[b"data"].decode("utf-8")
                    yield f"data: {data_str}\n\n"
                    try:
                        data = json.loads(data_str)
                        if data.get("event") == "done":
                            return  # Stream finished cleanly
                    except Exception:
                        pass

            # Check Celery task status after each read batch
            task_result = AsyncResult(task_id)
            if task_result.ready() and task_result.status in [
                "FAILURE",
                "REVOKED",
            ]:
                yield f'data: {json.dumps({"event": "error", "data": {"message": "Analysis task failed or was cancelled."}})}\n\n'
                return

    return StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )


@api.post("/cancel/")
def cancel_query(request, session_id: str):
    """Signal cancellation for all in-progress queries in a session."""
    cache.set(f"cancel_{session_id}", True, timeout=60)
    logger.info(
        "Cancel requested",
        extra={
            "data": {
                "session_id": session_id,
                "client_ip": _get_client_ip(request),
            }
        },
    )
    return {"status": "Cancellation signal sent"}


# ── Sessions & History ──────────────────────────────────────────────────


@api.get("/sessions/")
def get_sessions(request):
    """Fast endpoint returning only session summaries for sidebar."""
    from django.db.models import Count, Max, Min

    sessions = list(
        QueryHistory.objects.filter(is_deleted=False)
        .values("session_id")
        .annotate(
            count=Count("id"),
            last_activity=Max("created_at"),
            first_query_id=Min("id"),
        )
        .order_by("-last_activity")
    )

    # Bulk fetch first query text per session
    first_ids = [s["first_query_id"] for s in sessions if s["first_query_id"]]
    first_queries = {}
    if first_ids:
        for entry in QueryHistory.objects.filter(id__in=first_ids).values(
            "id", "query", "session_id"
        ):
            first_queries[entry["session_id"]] = entry["query"]

    return [
        {
            "id": s["session_id"],
            "title": first_queries.get(s["session_id"], "New Chat")[:80],
            "count": s["count"],
            "last_activity": s["last_activity"].isoformat()
            if s["last_activity"]
            else "",
        }
        for s in sessions
    ]


@api.get("/history/")
def get_history(request, session_id: str = None, limit: int = 200, offset: int = 0):
    """Return history for a session, with stale-query detection."""
    from datetime import timedelta

    from django.utils import timezone

    qs = QueryHistory.objects.filter(is_deleted=False)
    if session_id:
        qs = qs.filter(session_id=session_id)
    history = list(qs.order_by("-created_at")[offset : offset + limit])

    now = timezone.now()
    stale_threshold = now - timedelta(minutes=2)

    # Batch-check heartbeats for incomplete items to avoid N+1 Redis calls
    redis_client = _get_redis()
    incomplete_items = [
        h
        for h in history
        if (not h.execution_time or h.execution_time == 0) and h.task_id
    ]

    # Pipeline Redis calls for all incomplete items at once
    stale_task_ids = set()
    if incomplete_items:
        pipe = redis_client.pipeline(transaction=False)
        for h in incomplete_items:
            pipe.exists(f"heartbeat:{h.task_id}")
        heartbeat_results = pipe.execute()

        for h, has_heartbeat in zip(incomplete_items, heartbeat_results):
            is_stale = h.created_at < stale_threshold

            if not is_stale and h.created_at < (now - timedelta(seconds=30)):
                if not has_heartbeat:
                    is_stale = True

            if not is_stale:
                # Check Celery task status
                task_result = AsyncResult(h.task_id)
                if task_result.ready() and task_result.status in [
                    "FAILURE",
                    "REVOKED",
                ]:
                    is_stale = True

            if is_stale:
                stale_task_ids.add(h.task_id)

    res = []
    for h in history:
        report = h.report
        exec_time = h.execution_time or 0.0

        if h.task_id and h.task_id in stale_task_ids:
            report = (
                "_Analysis was interrupted (server restart or process killed)._"
            )
            exec_time = -1.0  # Signal to frontend: no longer generating

        res.append(
            {
                "id": h.id,
                "session_id": h.session_id,
                "query": h.query,
                "created_at": h.created_at.isoformat(),
                "result": {
                    "report": report,
                    "chart_config": h.chart_config,
                    "raw_data": [],  # Lazy load via /history/{id}/data/
                    "sql_query": h.sql_query,
                    "execution_time": exec_time,
                    "has_data": bool(h.raw_data and len(h.raw_data) > 0),
                },
                "usage": {
                    "input_tokens": h.input_tokens or 0,
                    "output_tokens": h.output_tokens or 0,
                    "estimated_cost": h.estimated_cost or 0,
                }
                if h.input_tokens
                else None,
            }
        )
    # Reverse so frontend gets oldest-first order (newest at bottom)
    return res[::-1]


@api.get("/history/{query_id}/data/")
def get_query_data(request, query_id: int):
    try:
        h = QueryHistory.objects.get(id=query_id)
        # Limit to 1000 rows for the detail view to prevent browser crash
        return {"raw_data": h.raw_data[:1000] if h.raw_data else []}
    except QueryHistory.DoesNotExist:
        return {"error": "Not found", "raw_data": []}


@api.post("/delete-session/")
def delete_session(request, session_id: str):
    QueryHistory.objects.filter(session_id=session_id).update(is_deleted=True)
    logger.info(
        "Session soft-deleted",
        extra={
            "data": {
                "session_id": session_id,
                "client_ip": _get_client_ip(request),
            }
        },
    )
    return {"status": "Session deleted"}


# ── Saved Prompts CRUD ──────────────────────────────────────────────────


@api.get("/prompts/")
def list_saved_prompts(request):
    from analytics.models import SavedPrompt

    prompts = SavedPrompt.objects.all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "query": p.query,
            "sql_command": p.sql_command,
            "created_at": p.created_at.isoformat(),
        }
        for p in prompts
    ]


@api.post("/prompts/")
def create_saved_prompt(request, payload: SavedPromptCreate):
    from analytics.models import SavedPrompt
    from ninja.errors import HttpError

    # Check duplicates
    if SavedPrompt.objects.filter(sql_command=payload.sql_command).exists():
        raise HttpError(
            400, "A saved prompt with this exact SQL command already exists."
        )
    if SavedPrompt.objects.filter(name=payload.name).exists():
        raise HttpError(
            400,
            "A saved prompt with this name already exists. Please choose a different name.",
        )

    p = SavedPrompt.objects.create(
        name=payload.name,
        query=payload.query,
        sql_command=payload.sql_command,
    )
    return {
        "id": p.id,
        "name": p.name,
        "query": p.query,
        "sql_command": p.sql_command,
        "created_at": p.created_at.isoformat(),
    }


@api.put("/prompts/{prompt_id}/")
def rename_saved_prompt(request, prompt_id: int, payload: SavedPromptUpdate):
    from analytics.models import SavedPrompt
    from django.shortcuts import get_object_or_404

    p = get_object_or_404(SavedPrompt, id=prompt_id)
    p.name = payload.name
    p.save()
    return {"status": "success", "id": p.id, "name": p.name}


@api.delete("/prompts/{prompt_id}/")
def delete_saved_prompt(request, prompt_id: int):
    from analytics.models import SavedPrompt

    SavedPrompt.objects.filter(id=prompt_id).delete()
    return {"status": "deleted"}
