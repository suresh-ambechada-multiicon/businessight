from __future__ import annotations

import json
from typing import Any

from analytics.schemas import VerifiedAnswerResponse
from analytics.services.agent.logic.reporting import _evidence_from_result
from analytics.services.logger import get_logger
from analytics.services.runware.prompts import (
    verified_answer_payload,
    verified_answer_system_prompt,
)
from analytics.services.tokens import count_tokens

logger = get_logger("pipeline")


def generate_verified_answer(
    *,
    llm,
    user_query: str,
    result: dict,
    model_config=None,
    usage_sink: dict[str, Any] | None = None,
    ctx=None,
) -> dict[str, Any]:
    evidence = _evidence_from_result(result)
    if not evidence.get("blocks"):
        return {}

    try:
        system_prompt = verified_answer_system_prompt(json_output=True)
        user_payload = json.dumps(
            verified_answer_payload(user_query=user_query, evidence=evidence),
            default=str,
        )
        structured_llm = llm.with_structured_output(VerifiedAnswerResponse)
        answer = structured_llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ]
        )
        if hasattr(answer, "model_dump"):
            answer_dict = answer.model_dump()
        else:
            answer_dict = answer if isinstance(answer, dict) else {}
        if usage_sink is not None and model_config is not None:
            usage_sink.update(
                estimate_verified_usage(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    answer=answer_dict,
                    model_config=model_config,
                )
            )
        return answer_dict
    except Exception as exc:
        logger.warning(
            "Verified answer pass failed",
            exc_info=True,
            extra={"data": {**(ctx.to_dict() if ctx else {}), "error": str(exc)[:300]}},
        )
        return {}


def estimate_verified_usage(
    *,
    system_prompt: str,
    user_payload: str,
    answer: dict[str, Any],
    model_config,
) -> dict[str, Any]:
    input_tokens = count_tokens(system_prompt) + count_tokens(user_payload)
    output_tokens = count_tokens(json.dumps(answer, default=str))
    thinking_tokens = 0
    cost = (input_tokens / 1_000_000) * model_config.cost_per_1m_input + (
        output_tokens / 1_000_000
    ) * model_config.cost_per_1m_output
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "estimated_cost": round(cost, 6),
    }
