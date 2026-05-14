from ninja import Router

from analytics.models import QueryHistory
from analytics.services.logger import get_logger

logger = get_logger("api")

from analytics.api.query import _get_client_ip


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
def get_history(request, session_id: str = "", limit: int = 200, offset: int = 0):
    """Return history for a session."""
    qs = QueryHistory.objects.filter(is_deleted=False)
    if session_id != "":
        qs = qs.filter(session_id=session_id)
    history = list(qs.order_by("-created_at")[offset : offset + limit])

    res = []
    for h in history:
        stored_blocks = h.result_blocks if isinstance(h.result_blocks, list) else []
        if stored_blocks:
            sanitized_blocks = []
            for block in stored_blocks:
                sb = {"kind": block.get("kind", "text")}
                if block.get("title"):
                    sb["title"] = block["title"]
                if block.get("text"):
                    sb["text"] = block["text"]
                if block.get("sql_query"):
                    sb["sql_query"] = block["sql_query"]
                if block.get("chart_config"):
                    sb["chart_config"] = block["chart_config"]
                if isinstance(block.get("raw_data"), list):
                    sb["raw_data"] = block["raw_data"][:1000]
                sanitized_blocks.append(sb)
            result_blocks = sanitized_blocks
        else:
            result_blocks = [
                *(
                    [
                        {
                            "kind": "text",
                            "text": h.report,
                        }
                    ]
                    if h.report
                    else []
                ),
                *(
                    [
                        {
                            "kind": "chart",
                            "chart_config": h.chart_config,
                        }
                    ]
                    if h.chart_config
                    else []
                ),
                *(
                    [
                        {
                            "kind": "table",
                            "raw_data": h.raw_data[:1000] if h.raw_data else [],
                        }
                    ]
                    if h.raw_data
                    else []
                ),
            ]
        item = {
            "id": h.id,
            "session_id": h.session_id,
            "query": h.query,
            "created_at": h.created_at.isoformat(),
            "task_id": h.task_id,
            "result": {
                "report": h.report,
                "chart_config": h.chart_config,
                "raw_data": h.raw_data[:1000] if h.raw_data else [],
                "sql_query": h.sql_query,
                "execution_time": h.execution_time or 0.0,
                "has_data": bool(h.raw_data and len(h.raw_data) > 0),
                "result_blocks": result_blocks,
            },
            "usage": {
                "input_tokens": h.input_tokens or 0,
                "output_tokens": h.output_tokens or 0,
                "thinking_tokens": h.thinking_tokens or 0,
                "estimated_cost": h.estimated_cost or 0,
            }
            if h.input_tokens
            else None,
        }
        if h.thinking_steps:
            item["thinking_steps"] = h.thinking_steps
        if getattr(h, "agent_trace", None):
            item["agent_trace"] = h.agent_trace
        res.append(item)
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
