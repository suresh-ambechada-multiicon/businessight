from __future__ import annotations

import json
from typing import Any

from analytics.schemas import AnalyticsResponse, VerifiedAnswerResponse


CHART_PLANNING_RULES = """Chart planning rules:
- Return a `chart` block only when you intentionally want a visualization; backend will not invent chart blocks from tables.
- Chart SQL must be aggregated/chart-ready, not raw detail rows: one label/time column plus one or more numeric metric columns, or period + category + numeric metric for multi-series charts.
- Use readable aliases for label and metrics (`month`, `category_name`, `total_sales`, `order_count`). Avoid ID-only labels, booleans, flags, UUIDs, and raw row identifiers as chart metrics.
- Use `line` for ordered time series (day/week/month/year + metric). Use `area` for cumulative or volume-over-time emphasis.
- Use `bar` for category breakdowns, rankings, top/bottom lists, and comparisons across discrete groups.
- Use `stacked-bar` or `stacked-area` for composition by category across periods or groups (period + category + metric, or multiple numeric series per label).
- Use `pie` only for part-to-whole composition with 2-8 categories and one positive metric; otherwise prefer bar.
- Use `composed` when the same x-axis needs different metric types together, such as count + amount.
- Use `scatter` only for relationship/correlation between two numeric measures.
- Limit chart rows to a readable set: usually top 10-20 categories or 12-36 periods. Put full detail/ranking rows in a separate table block.
- In `chart_config`, set only `type`, `x_label`, and `y_label`; never include chart `data`.
"""


def runware_sql_planning_prompt(*, db_dialect: str, schema_context: str) -> str:
    return f"""You are a senior data analyst. Produce a SQL evidence plan; backend executes SQL and writes final answer.

Database dialect: {db_dialect}

Schema context:
{schema_context}

Rules:
- Return only structured JSON; no markdown wrapper.
- Use only read-only SELECT/CTE SQL. Never mutate data.
- Every table/chart block needs one `sql_query`. Do not include raw rows or chart data.
- Never return a chart block without `sql_query`. Never repeat the same chart/table block.
- Return at most 8 result_blocks total; 2-5 is preferred for non-trivial analytics.
- Use exact table/column names from schema. Never use SELECT *.
- User terms may be row values, not table/column names. Use value hints and backend `value_search` context when present.
- Prefer readable joined names/codes/titles beside IDs when schema supports lookup/master tables.
- Do not add filters the user did not ask for. If a value/join/amount/date is uncertain, include candidate SQL blocks instead of one fragile guess.
- Simple count/list/show: one focused SQL is enough.
- If user asks for chart/graph/plot/visual/visualize, include at least one `chart` block unless no numeric/time/category evidence exists.
- For chartable questions (analysis, trend, breakdown, comparison, distribution, ranking/top/highest/lowest, grouped/by/wise/per), include at least one `chart` block plus one inspectable `table` block when data supports it.
- Analysis/detail/trend/breakdown/ranking/grouped/by/wise: return 2-5 different SQL blocks in this first response: compact KPI/summary, useful chart-ready trend/breakdown, and supporting detail/ranking rows when available.
- Avoid duplicate or near-duplicate SQL/result blocks.

{CHART_PLANNING_RULES}
"""


def analytics_system_prompt(
    *,
    formatted_prompt: str,
    repair_context: dict[str, Any] | None = None,
    followup_context: dict[str, Any] | None = None,
) -> str:
    json_contract = AnalyticsResponse.model_json_schema()
    system_prompt = (
        formatted_prompt
        + "\n\nReturn ONLY valid JSON matching this schema. Do not wrap it in markdown. "
        "Every table or chart block must include a read-only SELECT sql_query. "
        "Never return a chart block without sql_query. Never return duplicate chart/table blocks. "
        "Return at most 8 result_blocks total; prefer 2-5 for non-trivial analytics. "
        "Do not include raw rows or chart data; the backend will execute SQL. "
        "If the user supplied multiple exact SQL queries, return one separate table "
        "result_block per SQL query and preserve the supplied order. "
        "For database analysis, do not return only one SQL and expect later calls to add context. "
        "Plan the full evidence pack in this same response. For non-trivial questions "
        "(analysis, detail, trend, comparison, breakdown, ranking, grouped/by/wise), return "
        "2-5 separate table/chart result_blocks with different SQL queries: compact KPI/summary, "
        "useful breakdown or trend, and supporting detail/ranking rows when available. "
        "If the user asks for chart/graph/plot/visual/visualize, include at least one `chart` block "
        "unless no numeric/time/category evidence exists. For chartable analysis, trend, breakdown, "
        "comparison, distribution, ranking/top/highest/lowest, grouped/by/wise/per questions, include "
        "at least one `chart` block plus one inspectable `table` block when data supports it. "
        "For each chart block, choose the chart type from the chart planning rules already given: "
        "line/area for time, bar for category/ranking, stacked variants for composition over periods, "
        "pie only for small part-to-whole, composed for mixed metrics, scatter for two numeric measures. "
        "Use one SQL block only for simple count/list/show questions. "
        "Use the schema context exactly: it includes the active schema, column types, "
        "and Value Hints with sample distinct names/codes/statuses/categories. Match "
        "user terms to those values before choosing filters or joins. "
        "Avoid ID-only output: when selecting or grouping by a *_id column, also join "
        "the matching lookup/master table and include a readable name/code column if "
        "the schema provides one. "
        "For analytical or time-window questions, order result_blocks as: top full analytics "
        "summary, then each table/chart block immediately followed by a concise text/summary "
        "explaining what that raw table or chart should help inspect. Charts are required when the user asks "
        "for a visual or when the answer has a useful trend/category/ranking metric. Chart SQL and table SQL can be different; make chart "
        "SQL aggregated and visualization-friendly instead of reusing a raw/detail table. "
        "If a join key, category value, service value, or amount column is uncertain, "
        "bundle multiple candidate SQL table blocks in this same response rather than "
        "making one fragile guess. Use clear candidate titles and vary the join/filter "
        "strategy so the backend can execute all candidates locally and keep the one "
        "that returns evidence. "
        "Do not use canned domain wording. Titles, summaries, and SQL must come from "
        "the user's exact question and the database schema. Never mention an example "
        "domain unless it is present in the user question, schema, SQL, or executed "
        "evidence. The report structure can vary; choose only sections that fit the "
        "evidence.\n\n"
        f"JSON schema:\n{json.dumps(json_contract, separators=(',', ':'))}"
    )
    if repair_context:
        system_prompt += (
            "\n\nPrevious SQL attempt did not produce a satisfactory executable result. "
            "Review the failure/empty evidence below and return a corrected structured response. "
            "Use different joins, date/status filters, grouping columns, or amount columns when the "
            "previous query was too restrictive or selected the wrong table. Do not repeat the same SQL.\n"
            f"Repair context:\n{json.dumps(repair_context, default=str)}"
        )
    if followup_context:
        system_prompt += (
            "\n\nAdditional backend context for this same user query is below. "
            "It may include executed SQL evidence from earlier rounds and/or value_search matches. "
            "Important: user terms may be stored as row values, not table or column names. "
            "If value_search found table/column/value matches, prioritize those locations. "
            "If executed evidence is already sufficient, return valid JSON with an empty `result_blocks` array. "
            "If more detail is needed, return ONLY additional `table` or `chart` result_blocks with new "
            "read-only SELECT SQL. Do not repeat SQL in `executed_sql_keys`. Do not invent raw rows or chart data.\n"
            f"Backend context:\n{json.dumps(followup_context, default=str)}"
        )
    return system_prompt


def verified_answer_system_prompt(*, json_output: bool) -> str:
    prefix = (
        "You are a senior data analyst writing the final user-facing answer. "
        "Use only the provided executed SQL evidence. Do not invent numbers, "
        "totals, fields, labels, or trends. "
    )
    if json_output:
        prefix += (
            "Return only JSON matching the provided schema: `overview` plus `block_insights`. "
            "Write natural Markdown "
        )
    else:
        prefix += "Write polished Markdown only. "

    return (
        prefix
        + "that fits the user's question and available evidence; do not use a fixed template, "
        "do not call the output a report. Use proper Markdown, not paragraph-only text. "
        "Use meaningful headings, bullet lists, and numbered lists when multiple facts exist. "
        "The `overview` must be detailed: prefer 2-5 short Markdown sections or bullet groups "
        "when evidence supports it. Include key facts, counts, rankings, relationships between blocks, "
        "caveats, and what the data means for the user's question. "
        "Write deeper analysis when multiple evidence blocks are present: compare peaks "
        "and lows, totals, averages, period-over-period movement, concentration, and "
        "notable gaps when those facts are visible. "
        "Keep block-specific explanations concise, but still use Markdown bullets for multiple observations. "
        "The overview will be shown before chart/table blocks, so synthesize across all displayed data. "
        "Include only sections that fit the result, such as findings, ranking, trends, "
        "comparisons, or limitations. If the user asks for a longer window but the "
        "evidence contains fewer populated periods, say the requested window and the "
        "observed populated period count clearly. "
        "If `truncated` is true and `total_count` is null, the total matching record "
        "count is unknown. Never present `loaded_sample_rows` as the total dataset size; "
        "say only that the UI shows a capped sample. "
        "When some candidate SQL blocks are empty but others return rows, ignore the empty "
        "candidates in the findings. Do not conclude that data is unavailable if any "
        "executed evidence block has rows. "
        "Do not create duplicate table/chart insights for near-identical blocks. If two evidence "
        "blocks have same columns and similar rows, explain only the stronger/first one and do not "
        "use words like refined, previous block, or same criteria. "
        "Do not mention domains, filters, entities, or metrics that are not present "
        "in the user question, executed SQL, or result columns. Do not include raw SQL. "
        "For every non-empty table/chart evidence block, write one `block_insights` item "
        "using that block's `index`. Put detailed explanation and analytics there so UI can "
        "show it immediately after the raw table or chart. Use Markdown bullets if there are multiple observations."
    )


def verified_answer_payload(*, user_query: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": user_query,
        "executed_evidence": evidence,
        "response_schema": VerifiedAnswerResponse.model_json_schema(),
        "output_layout": {
            "overview": "Detailed main analysis shown at the top before raw tables/charts. Use Markdown headings and bullet lists. Prefer 2-5 short sections or bullet groups when data supports it.",
            "block_insights": "Short local explanation shown immediately after each matching table/chart. Use bullets or numbered lists for multiple observations.",
            "dedupe": "If evidence blocks are duplicates or near-duplicates, write insight only for the first useful block. Do not say refined or previous block.",
        },
    }
