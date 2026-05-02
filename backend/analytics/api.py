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


@api.post("/query/")
def query_analytics(request, payload: AnalyticsRequest):
    ctx = RequestContext(
        session_id=payload.session_id,
        client_ip=_get_client_ip(request),
        model=payload.model,
        query=payload.query,
        db_uri_hash=get_db_uri_hash(payload.db_url) if payload.db_url else "",
    )
    return StreamingHttpResponse(
        process_analytics_query(payload, ctx),
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
                    # Omit raw_data to prevent massive payload sizes and serialization delays
                    "raw_data": [],
                    "sql_query": h.sql_query,
                    "execution_time": h.execution_time,
                },
            }
        )
    # Reverse the list so the frontend receives them in oldest-first order (newest at the bottom of the chat)
    return res[::-1]


@api.post("/delete-session/")
def delete_session(request, session_id: str):
    QueryHistory.objects.filter(session_id=session_id).update(is_deleted=True)
    logger.info("Session soft-deleted", extra={"data": {
        "session_id": session_id,
        "client_ip": _get_client_ip(request),
    }})
    return {"status": "Session deleted"}
