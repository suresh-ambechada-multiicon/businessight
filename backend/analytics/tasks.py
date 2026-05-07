"""
Celery task for processing analytics queries.

Wraps the core pipeline generator, writes each chunk to a Redis Stream
for SSE consumption, and handles errors gracefully so the frontend
never hangs indefinitely.
"""

import json
import logging
import traceback

import redis
from celery import shared_task
from django.conf import settings

try:
    from celery.exceptions import SoftTimeLimitExceeded
except ImportError:
    SoftTimeLimitExceeded = Exception

from analytics.schemas import AnalyticsRequest
from analytics.services.core import process_analytics_query
from analytics.services.cache import get_db_uri_hash
from analytics.services.logger import RequestContext

logger = logging.getLogger("analytics.tasks")


@shared_task(bind=True, max_retries=0, time_limit=300, soft_time_limit=240)
def process_query_task(self, payload_dict: dict, client_ip: str):
    """
    Main Celery task — streams analytics results to a Redis Stream.

    Error handling ensures:
    - An error event + done event are always written on failure
    - The heartbeat is always cleaned up
    - The QueryHistory record is marked failed if the pipeline crashes
    """
    payload = AnalyticsRequest(**payload_dict)
    ctx = RequestContext(
        session_id=payload.session_id,
        client_ip=client_ip,
        model=payload.model,
        query=payload.query,
        db_uri_hash=get_db_uri_hash(payload.db_url) if payload.db_url else "",
        task_id=self.request.id,
    )

    redis_client = redis.from_url(settings.CELERY_BROKER_URL)
    stream_key = f"stream:{self.request.id}"
    heartbeat_key = f"heartbeat:{self.request.id}"

    # Signal liveness immediately
    redis_client.setex(heartbeat_key, 60, "alive")

    try:
        for chunk in process_analytics_query(payload, ctx):
            # Refresh heartbeat on every chunk
            redis_client.setex(heartbeat_key, 60, "alive")
            # Write to Redis Stream — use maxlen 500 to avoid dropping early events
            redis_client.xadd(stream_key, {"data": json.dumps(chunk)}, maxlen=500)

        # Pipeline completed normally — write done sentinel
        _write_done(redis_client, stream_key, self.request.id)

    except SoftTimeLimitExceeded:
        logger.warning("Task hit soft time limit", extra={"data": ctx.to_dict()})
        _write_error(redis_client, stream_key, "Analysis timed out (exceeded 4 minutes).")
        _write_done(redis_client, stream_key, self.request.id)
        _mark_history_failed(ctx.task_id, "Analysis timed out.")

    except Exception as e:
        logger.error(
            "Task crashed",
            exc_info=True,
            extra={"data": {**ctx.to_dict(), "error": str(e)}},
        )
        _write_error(redis_client, stream_key, f"Analysis failed: {str(e)}")
        _write_done(redis_client, stream_key, self.request.id)
        _mark_history_failed(ctx.task_id, f"Error: {str(e)}")

    finally:
        # Expire heartbeat and stream after cleanup
        redis_client.delete(heartbeat_key)
        redis_client.expire(stream_key, 600)  # Keep stream for 10 min replay


# ── Helpers ─────────────────────────────────────────────────────────────

def _write_error(redis_client, stream_key: str, message: str):
    """Write an error event to the Redis Stream."""
    try:
        data = json.dumps({"event": "error", "data": {"message": message}})
        redis_client.xadd(stream_key, {"data": data}, maxlen=500)
    except Exception:
        pass


def _write_done(redis_client, stream_key: str, task_id: str):
    """Write the done sentinel to the Redis Stream."""
    try:
        data = json.dumps({"event": "done", "data": {"task_id": task_id}})
        redis_client.xadd(stream_key, {"data": data}, maxlen=500)
    except Exception:
        pass


def _mark_history_failed(task_id: str, error_msg: str):
    """Mark the QueryHistory record as failed so the UI doesn't hang."""
    try:
        from analytics.models import QueryHistory

        QueryHistory.objects.filter(
            task_id=task_id, execution_time__in=[0, 0.0, None]
        ).update(
            report=f"_{error_msg}_",
            execution_time=0.1,  # Non-zero signals completion to frontend
        )
    except Exception:
        pass



