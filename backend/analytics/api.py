from ninja import NinjaAPI

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.services import process_analytics_query

api = NinjaAPI()


@api.get("/history/")
def get_history(request, limit: int = 50, offset: int = 0):
    # Fetch most recent history first, with pagination
    history = QueryHistory.objects.order_by("-created_at")[offset:offset+limit]
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


from django.http import StreamingHttpResponse
import json

from django.core.cache import cache

@api.post("/cancel/")
def cancel_query(request, session_id: str):
    cache.set(f"cancel_{session_id}", True, timeout=60)
    return {"status": "Cancellation signal sent"}

@api.post("/query/")
def query_analytics(request, payload: AnalyticsRequest):
    return StreamingHttpResponse(
        process_analytics_query(payload),
        content_type="text/event-stream"
    )
