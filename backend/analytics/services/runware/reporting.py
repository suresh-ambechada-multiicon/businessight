from __future__ import annotations

import json
from collections.abc import Callable, Generator
from typing import Any

from analytics.schemas import VerifiedAnswerResponse
from analytics.services.logger import get_logger
from analytics.services.runware.client import RunwareTextClient
from analytics.services.runware.config import (
    DEFAULT_REPORT_MAX_TOKENS,
    REPORT_THINKING_LEVEL,
)
from analytics.services.runware.parsing import parse_verified_answer
from analytics.services.runware.prompts import verified_answer_payload, verified_answer_system_prompt
from analytics.services.runware.usage import usage_from_runware_item

logger = get_logger("agent")


def stream_runware_verified_report(
    *,
    model: str,
    api_key: str,
    user_query: str,
    evidence: dict[str, Any],
    llm_config,
    usage_sink: dict[str, Any] | None = None,
    cancel_checker: Callable[[], bool] | None = None,
    ctx=None,
    query_history_id: int | None = None,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """Create structured evidence-based answer and yield overview once for live UI."""
    model_name = model.split(":", 1)[1] if ":" in model else model
    _ctx = ctx.to_dict() if ctx else {}
    client = RunwareTextClient(
        model_name=model_name,
        api_key=api_key,
        llm_config=llm_config,
        ctx=ctx,
        query_history_id=query_history_id,
    )
    logger.info(
        "Runware verified answer started",
        extra={"data": {**_ctx, "model": model_name}},
    )
    if cancel_checker and cancel_checker():
        if usage_sink is not None:
            usage_sink["_cancelled"] = True
        return {"overview": "", "block_insights": []}

    item, raw_text = client.invoke_sync(
        system_prompt=verified_answer_system_prompt(json_output=True),
        user_query=json.dumps(
            verified_answer_payload(user_query=user_query, evidence=evidence),
            default=str,
        ),
        json_schema=VerifiedAnswerResponse.model_json_schema(),
        max_tokens=getattr(llm_config, "max_tokens", None) or DEFAULT_REPORT_MAX_TOKENS,
        thinking_level=REPORT_THINKING_LEVEL,
        phase="verified_report",
    )
    usage = usage_from_runware_item(item)
    if usage_sink is not None:
        for key, value in usage.items():
            if value:
                usage_sink[key] = value
    answer = parse_verified_answer(raw_text)
    overview = str(answer.get("overview") or "").strip()
    if overview:
        yield {"report": overview}
    if usage:
        yield {"usage": usage}
    logger.info(
        "Runware verified answer completed",
        extra={
            "data": {
                **_ctx,
                "overview_length": len(overview),
                "block_insights": len(answer.get("block_insights") or []),
            }
        },
    )
    return answer
