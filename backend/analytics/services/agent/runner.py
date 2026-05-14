"""Compatibility facade for analytics agent helpers.

The implementation is split across focused modules:
- core/state.py: stream result container
- logic/schema_context.py: schema prompt context
- core/llm.py: LLM initialization and history messages
- core/streaming.py: deep-agent stream loop
- logic/extraction.py: result extraction and SQL repair
- logic/reporting.py: verified final report generation
- logic/charts.py: chart validation/generation
"""

from deepagents import create_deep_agent

from analytics.services.agent.logic.charts import auto_generate_chart
from analytics.services.agent.logic.extraction import (
    extract_final_result,
    repair_missing_sql_result,
)
from analytics.services.agent.core.llm import build_messages, init_llm
from analytics.services.agent.logic.reporting import (
    apply_verified_report,
    has_executed_evidence,
    write_verified_report,
)
from analytics.services.agent.logic.schema_context import build_schema_context
from analytics.services.agent.core.state import StreamResult
from analytics.services.agent.core.streaming import stream_agent

__all__ = [
    "StreamResult",
    "auto_generate_chart",
    "build_messages",
    "build_schema_context",
    "create_deep_agent",
    "extract_final_result",
    "init_llm",
    "repair_missing_sql_result",
    "stream_agent",
    "apply_verified_report",
    "has_executed_evidence",
    "write_verified_report",
]
