from __future__ import annotations

from typing import Any

from analytics.schemas import AnalyticsResponse
from analytics.services.logger import get_logger
from analytics.services.runware.client import RunwareTextClient
from analytics.services.runware.config import (
    ANALYTICS_THINKING_LEVEL,
    DEFAULT_ANALYTICS_MAX_TOKENS,
)
from analytics.services.runware.parsing import normalize_runware_analytics_item
from analytics.services.runware.prompts import analytics_system_prompt

logger = get_logger("agent")


def invoke_runware_analytics(
    *,
    model: str,
    api_key: str,
    formatted_prompt: str,
    user_query: str,
    llm_config,
    ctx=None,
    query_history_id: int | None = None,
    repair_context: dict[str, Any] | None = None,
    followup_context: dict[str, Any] | None = None,
    phase: str = "analytics_sql",
) -> dict[str, Any]:
    """Call Runware text model and return normalized AnalyticsResponse dict."""
    model_name = model.split(":", 1)[1] if ":" in model else model
    _ctx = ctx.to_dict() if ctx else {}
    logger.info(
        "Runware analytics model invoked",
        extra={"data": {**_ctx, "model": model_name}},
    )

    client = RunwareTextClient(
        model_name=model_name,
        api_key=api_key,
        llm_config=llm_config,
        ctx=ctx,
        query_history_id=query_history_id,
    )
    item, _raw_text = client.invoke_sync(
        system_prompt=analytics_system_prompt(
            formatted_prompt=formatted_prompt,
            repair_context=repair_context,
            followup_context=followup_context,
        ),
        user_query=user_query,
        json_schema=AnalyticsResponse.model_json_schema(),
        max_tokens=DEFAULT_ANALYTICS_MAX_TOKENS,
        thinking_level=ANALYTICS_THINKING_LEVEL,
        phase=phase,
    )
    result = normalize_runware_analytics_item(item)
    logger.info(
        "Runware analytics response parsed",
        extra={
            "data": {
                **_ctx,
                "report_length": len(str(result.get("report") or "")),
                "block_count": len(result.get("result_blocks") or []),
                "has_sql": bool(result.get("sql_query"))
                or any(
                    isinstance(block, dict) and block.get("sql_query")
                    for block in result.get("result_blocks") or []
                ),
            }
        },
    )
    return {
        "report": result.get("report") or "",
        "chart_config": None,
        "raw_data": [],
        "sql_query": result.get("sql_query") or "",
        "result_blocks": result.get("result_blocks") or [],
        "_runware_usage": result.get("_runware_usage") or {},
    }
