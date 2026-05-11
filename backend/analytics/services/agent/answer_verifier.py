"""
Post-hoc LLM verification: check that the narrative report is broadly consistent
with executed SQL and a sample of result rows (Genie-style verification pass).
"""

from __future__ import annotations

import json
from langchain_core.messages import HumanMessage

from analytics.services.agent.runner import init_llm
from analytics.services.logger import get_logger
from analytics.services.tokens import count_tokens

logger = get_logger("agent")


def verify_report_against_data(
    *,
    report: str,
    sql_query: str,
    raw_data_sample: list,
    verifier_model: str,
    api_key: str,
    llm_config,
    ctx,
) -> dict:
    """
    Returns ``{"ok": bool, "issues": list[str], "summary": str,
    "verifier_input_tokens": int, "verifier_output_tokens": int}``.
    On any failure, returns ``ok: True`` with empty issues (non-blocking).
    """
    out = {
        "ok": True,
        "issues": [],
        "summary": "",
        "verifier_input_tokens": 0,
        "verifier_output_tokens": 0,
    }
    if not report or not report.strip():
        return out

    sample = raw_data_sample[:25] if isinstance(raw_data_sample, list) else []
    sample_json = json.dumps(sample, default=str)[:12000]
    sql_short = (sql_query or "")[:8000]

    prompt = f"""You verify analytics reports against query evidence.

SQL executed (may contain multiple statements):
```
{sql_short}
```

First rows of result data (JSON):
```json
{sample_json}
```

Report to audit:
---
{report[:12000]}
---

Task: Find factual or numeric claims in the report that are **not supported** by the SQL result sample
(e.g. wrong totals, invented categories, percentages that cannot be derived from the sample).

Respond with **only one line** of JSON (no markdown, no prose):
{{"consistent": true or false, "issues": ["short issue 1", ...]}}
Use at most 5 issue strings. If unsure or sample too small to decide, set consistent to true and issues to [].
"""

    try:
        if hasattr(llm_config, "model_copy"):
            vcfg = llm_config.model_copy(
                update={"max_tokens": 1024, "temperature": 0.05}
            )
        else:
            vcfg = llm_config
        llm = init_llm(verifier_model, api_key, vcfg, ctx)
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = getattr(resp, "content", "") or ""
        if isinstance(text, list):
            text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in text
            )
        start = text.find("{")
        end = text.rfind("}")
        blob = text[start : end + 1] if start != -1 and end > start else text.strip()
        data = json.loads(blob)
        issues = data.get("issues") or []
        if not isinstance(issues, list):
            issues = []
        issues = [str(x)[:500] for x in issues[:5]]
        ok = bool(data.get("consistent", True))
        v_in = count_tokens(prompt, verifier_model)
        v_out = count_tokens(text, verifier_model)
        out = {
            "ok": ok,
            "issues": issues,
            "summary": "; ".join(issues) if issues else "",
            "verifier_input_tokens": v_in,
            "verifier_output_tokens": v_out,
        }
        logger.info(
            "Answer verification",
            extra={
                "data": {
                    **(ctx.to_dict() if ctx else {}),
                    "verifier_model": verifier_model,
                    "consistent": ok,
                    "issue_count": len(issues),
                }
            },
        )
    except Exception as e:
        logger.warning(
            "Answer verification skipped",
            extra={"data": {**(ctx.to_dict() if ctx else {}), "error": str(e)[:400]}},
        )
    return out
