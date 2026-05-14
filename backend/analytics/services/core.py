"""
Analytics query processing — main orchestrator facade.

This module provides the process_analytics_query entry point, which now
delegates to the AnalyticsPipeline for better modularity and testability.
"""

from typing import Generator

from analytics.schemas import AnalyticsRequest
from analytics.services.logger import RequestContext
from analytics.services.pipeline.orchestrator import AnalyticsPipeline


def process_analytics_query(payload: AnalyticsRequest, ctx: RequestContext) -> Generator[dict, None, None]:
    """
    Entry point for the analytics query pipeline.
    
    Creates a pipeline instance and yields events (SSE chunks) as it executes.
    Used by both the API (via Celery) and potentially direct tests.
    """
    pipeline = AnalyticsPipeline(payload, ctx)
    yield from pipeline.run()
