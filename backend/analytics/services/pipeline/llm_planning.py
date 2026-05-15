from __future__ import annotations

import json
from typing import Any

from analytics.schemas import AnalyticsResponse
from analytics.services.logger import get_logger
from analytics.services.runware.parsing import (
    analytics_response_from_error,
    coerce_analytics_response,
)
from analytics.services.runware.prompts import analytics_system_prompt
from analytics.services.tokens import count_tokens

logger = get_logger("pipeline")


def invoke_llm_analytics_plan(
    *,
    llm,
    model_config,
    formatted_prompt: str,
    user_query: str,
    repair_context: dict[str, Any] | None = None,
    followup_context: dict[str, Any] | None = None,
    ctx=None,
    phase: str = "analytics_sql",
    **_unused,
) -> dict[str, Any]:
    """Provider-neutral SQL planning pass. Backend executes returned SQL blocks."""
    _ctx = ctx.to_dict() if ctx else {}
    system_prompt = analytics_system_prompt(
        formatted_prompt=formatted_prompt,
        repair_context=repair_context,
        followup_context=followup_context,
    )
    logger.info(
        "LLM analytics planning invoked",
        extra={"data": {**_ctx, "phase": phase}},
    )

    try:
        structured_llm = llm.with_structured_output(AnalyticsResponse)
        planned = structured_llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ]
        )
        result = coerce_analytics_response(planned)
    except Exception as exc:
        recovered = analytics_response_from_error(exc)
        if recovered is None:
            logger.warning(
                "LLM analytics planning parse failed",
                exc_info=True,
                extra={"data": {**_ctx, "phase": phase, "error": str(exc)[:300]}},
            )
            raise RuntimeError(
                "The model returned an invalid analytics plan. Please try again or choose a stronger model."
            ) from exc
        logger.warning(
            "LLM analytics planning recovered malformed output",
            extra={
                "data": {
                    **_ctx,
                    "phase": phase,
                    "block_count": len(recovered.get("result_blocks") or []),
                }
            },
        )
        result = recovered

    usage = estimate_planning_usage(
        system_prompt=system_prompt,
        user_query=user_query,
        result=result,
        model_config=model_config,
    )
    logger.info(
        "LLM analytics plan parsed",
        extra={
            "data": {
                **_ctx,
                "phase": phase,
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
        "_planner_usage": usage,
    }


def estimate_planning_usage(
    *,
    system_prompt: str,
    user_query: str,
    result: dict[str, Any],
    model_config,
) -> dict[str, Any]:
    input_tokens = count_tokens(system_prompt) + count_tokens(user_query)
    output_tokens = count_tokens(json.dumps(result, default=str))
    cost = (input_tokens / 1_000_000) * model_config.cost_per_1m_input + (
        output_tokens / 1_000_000
    ) * model_config.cost_per_1m_output
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": 0,
        "estimated_cost": round(cost, 6),
    }
