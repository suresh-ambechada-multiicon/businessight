from __future__ import annotations

from typing import Any


def usage_from_runware_item(item: dict[str, Any]) -> dict[str, Any]:
    usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
    completion_details = usage.get("completionTokensDetails")
    if not isinstance(completion_details, dict):
        completion_details = usage.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}

    cost_breakdown = (
        usage.get("costBreakdown")
        if isinstance(usage.get("costBreakdown"), dict)
        else {}
    )
    token_breakdown = (
        cost_breakdown.get("tokens")
        if isinstance(cost_breakdown.get("tokens"), dict)
        else {}
    )
    completion_breakdown = (
        token_breakdown.get("completion")
        if isinstance(token_breakdown.get("completion"), dict)
        else {}
    )

    prompt_tokens = usage.get("promptTokens") or usage.get("prompt_tokens") or 0
    completion_tokens = (
        usage.get("completionTokens") or usage.get("completion_tokens") or 0
    )
    total_tokens = usage.get("totalTokens") or usage.get("total_tokens") or 0
    thinking_tokens = (
        usage.get("thinkingTokens")
        or usage.get("thinking_tokens")
        or completion_details.get("reasoningTokens")
        or completion_details.get("reasoning_tokens")
        or completion_breakdown.get("reasoningTokens")
        or completion_breakdown.get("reasoning_tokens")
        or 0
    )
    visible_output_tokens = (
        completion_breakdown.get("textTokens")
        or completion_breakdown.get("text_tokens")
        or completion_tokens
    )

    cost = item.get("cost")
    if cost is None:
        cost = usage.get("cost")
    if cost is None and isinstance(cost_breakdown, dict):
        cost = cost_breakdown.get("total")

    return {
        "input_tokens": int(prompt_tokens or 0),
        "output_tokens": int(visible_output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "thinking_tokens": int(thinking_tokens or 0),
        "estimated_cost": float(cost or 0),
    }


def finish_reason_from_item(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("finishReason") or item.get("finish_reason") or "")
