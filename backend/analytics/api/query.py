import json

import redis
from celery.result import AsyncResult
from django.conf import settings
from django.core.cache import cache
from django.http import StreamingHttpResponse
from ninja import Router, NinjaAPI

from analytics.schemas import AnalyticsRequest
from analytics.tasks import process_query_task
from analytics.services.logger import get_logger

logger = get_logger("api")


def _get_client_ip(request) -> str:
    """Extract client IP from the request, handling proxy headers."""
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _get_redis():
    """Get a Redis client for stream / heartbeat operations."""
    return redis.from_url(settings.CELERY_BROKER_URL)


router = Router()


@router.post("/query/")
def query_analytics(request, payload: AnalyticsRequest):
    """Enqueue an analytics task and return the Celery task ID."""
    task = process_query_task.delay(payload.dict(), _get_client_ip(request))
    return {"task_id": task.id}


@router.get("/stream/{task_id}/")
def stream_results(request, task_id: str):
    """SSE endpoint — reads from the Redis Stream written by the Celery worker."""

    def event_stream():
        import time as _time

        redis_client = _get_redis()
        stream_key = f"stream:{task_id}"

        last_id = "0"
        deadline = _time.time() + 310

        while _time.time() < deadline:
            result = redis_client.xread(
                {stream_key: last_id}, block=2000, count=50
            )
            if not result:
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
                            return
                    except Exception:
                        pass

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


@router.post("/cancel/")
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