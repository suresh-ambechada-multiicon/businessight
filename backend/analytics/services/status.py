"""
Real-time status reporting via Redis Streams.

Provides a standalone, importable function for sending pipeline status
updates to the frontend. Uses the Celery task_id to ensure messages
reach the correct SSE channel (Redis Stream key).
"""

import json
import threading

import redis
from django.conf import settings

from analytics.services.logger import get_logger

logger = get_logger("status")

# Thread-safe lazy Redis client initialization
_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    """Thread-safe lazy Redis client — only one is ever created."""
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            # Double-check inside lock to prevent race
            if _redis_client is None:
                _redis_client = redis.from_url(settings.CELERY_BROKER_URL)
    return _redis_client


def send_status(task_id: str, message: str):
    """
    Write a status update to the Redis Stream for the given task.
    task_id: The Celery task ID (determines stream key).
    """
    if not task_id:
        return
    try:
        r = _get_redis()
        stream_key = f"stream:{task_id}"
        r.xadd(
            stream_key,
            {"data": json.dumps({"event": "status", "data": {"message": message}})},
            maxlen=500,
        )
        # Refresh heartbeat to signal worker is still alive
        r.setex(f"heartbeat:{task_id}", 60, "alive")
    except Exception as e:
        logger.debug(f"Status stream write failed: {e}")
