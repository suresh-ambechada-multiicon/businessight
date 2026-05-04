"""
Analytics API endpoints.

Three endpoints:
- POST /api/query/   — Submit an analytics query (SSE stream response)
- POST /api/cancel/  — Cancel an in-progress query
- GET  /api/history/  — Paginated query history
"""

import json

from django.core.cache import cache
from django.http import StreamingHttpResponse
from ninja import NinjaAPI

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.services import process_analytics_query
from analytics.services.cache import get_db_uri_hash
from analytics.services.logger import RequestContext, get_logger

api = NinjaAPI()
logger = get_logger("api")


def _get_client_ip(request) -> str:
    """Extract client IP from the request, handling proxy headers."""
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


import redis
from django.conf import settings
from analytics.tasks import process_query_task
from analytics.services.llm_config import MODEL_REGISTRY

@api.get("/models/")
def list_models(request):
    return [
        {
            "id": model_id,
            "provider": config.provider,
            "name": model_id.split(":")[-1].replace("-", " ").title()
        }
        for model_id, config in MODEL_REGISTRY.items()
    ]

@api.post("/query/")
def query_analytics(request, payload: AnalyticsRequest):
    # Enqueue task and return task_id
    task = process_query_task.delay(payload.dict(), _get_client_ip(request))
    return {"task_id": task.id}

@api.get("/stream/{task_id}/")
def stream_results(request, task_id: str):
    def event_stream():
        redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        pubsub = redis_client.pubsub()
        pubsub.subscribe(f"task:{task_id}")
        for message in pubsub.listen():
            if message["type"] == "message":
                data_str = message["data"].decode("utf-8")
                yield f"data: {data_str}\n\n"
                try:
                    data = json.loads(data_str)
                    if data.get("event") in ("done", "result", "error"):
                        # If done or error, we can stop the stream
                        if data.get("event") == "done" or data.get("event") == "error":
                            pass
                        # Actually, process_analytics_query yields "result" and then we append {"event": "done"} in tasks.py
                        if data.get("event") == "done":
                            break
                except Exception:
                    pass
    return StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )


@api.post("/cancel/")
def cancel_query(request, session_id: str):
    cache.set(f"cancel_{session_id}", True, timeout=60)
    logger.info("Cancel requested", extra={"data": {
        "session_id": session_id,
        "client_ip": _get_client_ip(request),
    }})
    return {"status": "Cancellation signal sent"}


@api.get("/history/")
def get_history(request, limit: int = 2000, offset: int = 0):
    # Fetch most recent history first, with pagination, excluding deleted ones
    history = QueryHistory.objects.filter(is_deleted=False).order_by("-created_at")[offset:offset+limit]
    res = []
    for h in history:
        res.append(
            {
                "id": h.id,
                "session_id": h.session_id,
                "query": h.query,
                "created_at": h.created_at.isoformat(),
                "result": {
                    "report": h.report,
                    "chart_config": h.chart_config,
                    "raw_data": [], # Lazy load this!
                    "sql_query": h.sql_query,
                    "execution_time": h.execution_time,
                    "has_data": bool(h.raw_data and len(h.raw_data) > 0)
                },
            }
        )
    # Reverse the list so the frontend receives them in oldest-first order (newest at the bottom of the chat)
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
    logger.info("Session soft-deleted", extra={"data": {
        "session_id": session_id,
        "client_ip": _get_client_ip(request),
    }})
    return {"status": "Session deleted"}
