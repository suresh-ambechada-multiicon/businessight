"""
Real-time status reporting via Redis Pub/Sub.

Provides a standalone, importable function for sending pipeline status
updates to the frontend. Uses the Celery task_id to ensure messages
reach the correct SSE channel.
"""

import json
import redis
from django.conf import settings
from analytics.services.logger import get_logger

logger = get_logger("status")

# Module-level Redis client — reused across calls within the same worker
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.CELERY_BROKER_URL)
    return _redis_client


def send_status(task_id: str, message: str):
    """
    Publish a status update to the frontend via Redis.
    task_id: The Celery task ID (must match the channel the frontend subscribes to).
    """
    if not task_id:
        return
    try:
        r = _get_redis()
        r.publish(
            f"task:{task_id}",
            json.dumps({"event": "status", "data": {"message": message}})
        )
    except Exception as e:
        logger.debug(f"Status publish failed: {e}")
