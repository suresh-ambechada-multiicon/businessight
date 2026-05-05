import json
import redis
from celery import shared_task
from django.conf import settings

from analytics.services.core import process_analytics_query
from analytics.schemas import AnalyticsRequest
from analytics.services.logger import RequestContext

from analytics.services.db import get_db_uri_hash

@shared_task(bind=True, max_retries=1, time_limit=300)
def process_query_task(self, payload_dict: dict, client_ip: str):
    payload = AnalyticsRequest(**payload_dict)
    ctx = RequestContext(
        session_id=payload.session_id,
        client_ip=client_ip,
        model=payload.model,
        query=payload.query,
        db_uri_hash=get_db_uri_hash(payload.db_url) if payload.db_url else "",
        task_id=self.request.id,  # Pass Celery task ID for status channel
    )
    
    redis_client = redis.from_url(settings.CELERY_BROKER_URL)
    channel = f"task:{self.request.id}"
    
    for chunk in process_analytics_query(payload, ctx):
        redis_client.publish(channel, json.dumps(chunk))
        
    redis_client.publish(channel, json.dumps({"event": "done", "data": {"task_id": self.request.id}}))
