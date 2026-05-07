from datetime import timedelta

from celery.result import AsyncResult
from django.utils import timezone
from ninja import Router

from analytics.models import QueryHistory
from analytics.services.logger import get_logger

logger = get_logger("api")

from analytics.api.query import _get_client_ip, _get_redis


router = Router()


@router.get("/sessions/")
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


@router.get("/history/")
def get_history(request, session_id: str = None, limit: int = 200, offset: int = 0):
    """Return history for a session, with stale-query detection."""
    qs = QueryHistory.objects.filter(is_deleted=False)
    if session_id is not None:
        qs = qs.filter(session_id=session_id)
    history = list(qs.order_by("-created_at")[offset : offset + limit])

    now = timezone.now()
    stale_threshold = now - timedelta(minutes=2)

    redis_client = _get_redis()
    incomplete_items = [
        h
        for h in history
        if (not h.execution_time or h.execution_time == 0) and h.task_id
    ]

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
            report = "_Analysis was interrupted (server restart or process killed)._"
            exec_time = -1.0

        res.append(
            {
                "id": h.id,
                "session_id": h.session_id,
                "query": h.query,
                "created_at": h.created_at.isoformat(),
                "result": {
                    "report": report,
                    "chart_config": h.chart_config,
                    "raw_data": [],
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
    return res[::-1]


@router.get("/history/{query_id}/data/")
def get_query_data(request, query_id: int):
    try:
        h = QueryHistory.objects.get(id=query_id)
        return {"raw_data": h.raw_data[:1000] if h.raw_data else []}
    except QueryHistory.DoesNotExist:
        return {"error": "Not found", "raw_data": []}


@router.post("/delete-session/")
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