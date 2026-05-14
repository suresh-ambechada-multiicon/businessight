from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.utils.json import parse_partial_json

from analytics.schemas import AnalyticsResponse, VerifiedAnswerResponse
from analytics.services.runware.usage import usage_from_runware_item


def strip_fenced_json(text: str) -> str:
    raw = (text or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return raw


def parse_analytics_response(text: str) -> dict[str, Any]:
    raw = strip_fenced_json(text)
    parsed = parse_partial_json(raw)
    if not isinstance(parsed, dict):
        parsed = json.loads(raw)
    return AnalyticsResponse.model_validate(parsed).model_dump()


def normalize_runware_analytics_item(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or item.get("content") or "")
    if not text:
        raise RuntimeError(
            f"Runware response did not include generated text. Keys: {sorted(item.keys())}"
        )
    result = parse_analytics_response(text)
    result["_runware_usage"] = usage_from_runware_item(item)
    return result


def parse_verified_answer(text: str) -> dict[str, Any]:
    raw = strip_fenced_json(text)
    parsed = parse_partial_json(raw)
    if not isinstance(parsed, dict):
        parsed = json.loads(raw)
    return VerifiedAnswerResponse.model_validate(parsed).model_dump()
