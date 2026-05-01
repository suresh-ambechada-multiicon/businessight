from ninja import NinjaAPI

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.services import process_analytics_query

api = NinjaAPI()


@api.get("/history/")
def get_history(request):
    history = QueryHistory.objects.all()
    res = []
    for h in history:
        res.append(
            {
                "session_id": h.session_id,
                "query": h.query,
                "result": {
                    "report": h.report,
                    "chart_config": h.chart_config,
                    "raw_data": h.raw_data,
                    "sql_query": h.sql_query,
                },
            }
        )
    return res


@api.post("/query/", response=AnalyticsResponse)
def query_analytics(request, payload: AnalyticsRequest):
    return process_analytics_query(payload)
