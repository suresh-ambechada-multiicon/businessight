"""Fallback report recovery helpers."""

from __future__ import annotations

import json
from decimal import Decimal

from analytics.services.logger import get_logger

logger = get_logger("pipeline")


def needs_report_recovery(report: str) -> bool:
    text = (report or "").strip().lower()
    if not text:
        return True
    fallback_markers = [
        "no readable summary was produced",
        "did not produce a readable summary",
        "no output generated",
    ]
    return any(marker in text for marker in fallback_markers)


def _safe_json(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (bytes, memoryview)):
        return "(binary data)"
    if isinstance(obj, dict):
        return {str(k): _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json(i) for i in obj]
    return str(obj)


def recover_report_from_data(llm, query: str, sql_query: str, raw_data: list) -> str:
    """Generate a compact fallback report when agent output is missing/unreadable."""
    from langchain_core.messages import HumanMessage

    rows = raw_data if isinstance(raw_data, list) else []
    sample = _safe_json(rows[:20])
    prompt = (
        "You are a senior business analyst. The main agent could not produce a final readable report.\n"
        "Generate a concise markdown report with sections: Overview, Key Findings, Notes.\n"
        "Rules:\n"
        "- Use only the provided SQL result sample.\n"
        "- Do not invent values.\n"
        "- Mention if sample is small or partial.\n\n"
        f"User query: {query}\n"
        f"SQL used: {sql_query}\n"
        f"Rows returned: {len(rows)}\n"
        f"Result sample JSON: {json.dumps(sample)}\n"
    )
    try:
        recovered = llm.invoke([HumanMessage(content=prompt)])
        content = getattr(recovered, "content", "")
        if isinstance(content, list):
            content = "".join(
                c.get("text", "") if isinstance(c, dict) else str(c) for c in content
            )
        text = (content or "").strip()
        if text:
            return text
    except Exception:
        logger.warning("Fallback report recovery failed", exc_info=True)
    return ""

