from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.utils.json import parse_partial_json

from analytics.schemas import AnalyticsResponse, VerifiedAnswerResponse
from analytics.services.runware.usage import usage_from_runware_item
from analytics.services.sql_utils import normalize_sql_key


MAX_PLANNED_RESULT_BLOCKS = 8
_VALID_BLOCK_KINDS = {"text", "summary", "table", "chart"}
_VALID_CHART_TYPES = {
    "bar",
    "line",
    "area",
    "stacked-bar",
    "stacked-area",
    "pie",
    "composed",
    "scatter",
    "radar",
}


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
    return coerce_analytics_response(parsed)


def coerce_analytics_response(payload: Any) -> dict[str, Any]:
    """Normalize unreliable model output before strict AnalyticsResponse validation."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if isinstance(payload, str):
        raw = strip_fenced_json(payload)
        payload = parse_partial_json(raw)
        if not isinstance(payload, dict):
            payload = json.loads(raw)
    if not isinstance(payload, dict):
        payload = {}
    sanitized = sanitize_analytics_payload(payload)
    return AnalyticsResponse.model_validate(sanitized).model_dump()


def sanitize_analytics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop malformed/duplicate evidence blocks while preserving valid SQL plans."""
    report = str(payload.get("report") or "").strip()
    sql_query = str(payload.get("sql_query") or "").strip()
    blocks: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    for raw_block in payload.get("result_blocks") or []:
        block = _sanitize_result_block(raw_block)
        if not block:
            continue
        signature = _planned_block_signature(block)
        if signature in seen:
            continue
        seen.add(signature)
        blocks.append(block)
        if len(blocks) >= MAX_PLANNED_RESULT_BLOCKS:
            break

    return {
        "report": report,
        "sql_query": sql_query,
        "result_blocks": blocks,
    }


def analytics_response_from_error(error: Exception) -> dict[str, Any] | None:
    """Recover provider JSON embedded in LangChain/Pydantic parser exceptions."""
    text = str(error or "")
    if not text:
        return None
    starts = [
        match.start()
        for match in re.finditer(r'\{\s*"(?:report|result_blocks|sql_query)"', text)
    ]
    if not starts and "completion" in text:
        start = text.find("{", text.find("completion"))
        if start >= 0:
            starts.append(start)
    if not starts:
        start = text.find("{")
        if start >= 0:
            starts.append(start)

    for start in dict.fromkeys(starts):
        candidate = text[start:]
        candidate = _extract_json_object(candidate) or candidate
        for separator in (". Got:", "\nGot:", "\nFor further", "\nFor troubleshooting"):
            if separator in candidate:
                candidate = candidate.split(separator, 1)[0]
        try:
            return coerce_analytics_response(candidate)
        except Exception:
            continue
    return None


def _extract_json_object(text: str) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for idx, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[: idx + 1]
    return None


def _sanitize_result_block(raw_block: Any) -> dict[str, Any] | None:
    if hasattr(raw_block, "model_dump"):
        raw_block = raw_block.model_dump()
    if not isinstance(raw_block, dict):
        return None

    kind = str(raw_block.get("kind") or "").strip().lower()
    if kind not in _VALID_BLOCK_KINDS:
        return None

    title = _clean_text(raw_block.get("title"))
    if kind in {"text", "summary"}:
        text = _clean_text(raw_block.get("text") or raw_block.get("report"))
        if not text:
            return None
        block = {"kind": kind, "text": text}
        if title:
            block["title"] = title
        return block

    sql_query = str(raw_block.get("sql_query") or "").strip()
    if not sql_query:
        return None

    block = {"kind": kind, "sql_query": sql_query}
    if title:
        block["title"] = title
    if kind == "chart":
        block["chart_config"] = _sanitize_chart_config(raw_block.get("chart_config"))
    return block


def _sanitize_chart_config(raw_config: Any) -> dict[str, str]:
    config = raw_config if isinstance(raw_config, dict) else {}
    chart_type = str(config.get("type") or "bar").strip().lower()
    if chart_type not in _VALID_CHART_TYPES:
        chart_type = "bar"
    return {
        "type": chart_type,
        "x_label": _clean_text(config.get("x_label")) or "",
        "y_label": _clean_text(config.get("y_label")) or "",
    }


def _planned_block_signature(block: dict[str, Any]) -> tuple:
    kind = block.get("kind")
    sql_key = normalize_sql_key(str(block.get("sql_query") or ""))
    if sql_key:
        return kind, sql_key
    return (
        kind,
        str(block.get("title") or "").strip().lower(),
        str(block.get("text") or "").strip()[:500],
    )


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


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
