from typing import Any, Literal, List

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int | None = Field(
        default=None, description="Override max output tokens"
    )
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)


class AnalyticsRequest(BaseModel):
    query: str = Field(description="The natural language question to ask the database.")
    model: str = Field(
        description="The provider and model string (e.g., 'openai:gpt-4o', 'anthropic:claude-3-5-sonnet-latest')."
    )
    api_key: str = Field(description="The API key for the selected provider.")
    executor_model: str | None = Field(
        default=None,
        description=(
            "Optional model override for the main analysis agent. "
            "Defaults to `model`. Use a stronger model for complex SQL, or a cheaper one for exploration."
        ),
    )
    db_url: str = Field(
        default="",
        description="The connection string for the database to analyze (e.g. postgres://user:pass@host/db).",
    )
    session_id: str = Field(
        default="default",
        description="The ID of the session this query belongs to.",
    )
    direct_sql: str | None = Field(
        default=None,
        description="Pre-defined SQL to execute directly instead of letting AI generate it.",
    )
    llm_config: LLMConfig = Field(default_factory=LLMConfig)


class SavedPromptSchema(BaseModel):
    id: int
    name: str
    query: str
    sql_command: str
    created_at: str


class SavedPromptCreate(BaseModel):
    name: str
    query: str
    sql_command: str


class SavedPromptUpdate(BaseModel):
    name: str


class ChartDataset(BaseModel):
    label: str
    data: List[float]


class ChartData(BaseModel):
    labels: List[str]
    datasets: List[ChartDataset]


class ChartConfig(BaseModel):
    type: str = Field(
        description="The type of chart (e.g., 'bar', 'line', 'area', 'radar', 'scatter')."
    )
    x_label: str = Field(description="Label for the X axis")
    y_label: str = Field(description="Label for the Y axis")
    data: ChartData = Field(
        description="The data payload for the chart, including labels and datasets."
    )


class ChartConfigSkeleton(BaseModel):
    """Chart metadata from the agent only — no `data`; the server builds datasets from SQL rows."""

    type: str = Field(description="e.g. bar, line, area, pie, scatter")
    x_label: str = Field(default="", description="X axis label")
    y_label: str = Field(default="", description="Y axis label")


class AgentResultBlock(BaseModel):
    """One ordered segment of the answer. Table/chart blocks MUST include sql_query; never embed row JSON."""

    kind: Literal["text", "summary", "chart", "table"]
    title: str | None = None
    text: str | None = None
    sql_query: str | None = Field(
        default=None,
        description=(
            "Read-only SELECT for kind `table` or `chart`. Server executes this and fills raw_data / chart data. "
            "For analytical answers, table SQL and chart SQL may be different so each block can use the best shape."
        ),
    )
    chart_config: ChartConfigSkeleton | None = Field(
        default=None,
        description="For kind `chart` only: type and axis labels. Do NOT include `data`.",
    )


class ResultBlock(BaseModel):
    """Persisted / API block after hydration (may include raw_data and full chart_config)."""

    kind: Literal["text", "summary", "chart", "table"]
    title: str | None = None
    text: str | None = None
    sql_query: str | None = None
    row_count: int | None = None
    total_count: int | None = None
    truncated: bool | None = None
    chart_config: ChartConfig | None = None
    raw_data: list[dict[str, Any]] | None = None


class AnalyticsResponse(BaseModel):
    report: str = Field(
        default="",
        description=(
            "Optional short intro if you put the main narrative in `result_blocks` text/summary entries. "
            "Use Markdown. For list/show answers, do not paste all rows here — use a `table` block with `sql_query`."
        ),
    )
    sql_query: str = Field(
        default="",
        description=(
            "Optional single primary SQL for backward compatibility. Prefer putting `sql_query` on each "
            "`table` / `chart` block in `result_blocks`."
        ),
    )
    result_blocks: list[AgentResultBlock] = Field(
        default_factory=list,
        description=(
            "Ordered blocks the UI renders top-to-bottom. Interleave as needed, e.g. "
            "summary → KPI table → trend chart → category chart → supporting table. Each `table` or `chart` block "
            "MUST set `sql_query` (read-only SELECT); never put `raw_data` or chart `data` in the response — "
            "the server fetches rows and builds charts. Chart and table blocks can use different SQL queries."
        ),
    )


class VerifiedReportResponse(BaseModel):
    report: str = Field(
        description=(
            "Final Markdown report written only from the executed SQL evidence supplied by the backend. "
            "Do not mention numbers, totals, rows, charts, or trends that are not present in the evidence."
        )
    )
    overview: str | None = Field(
        default=None,
        description="Optional short executive overview to show before data blocks.",
    )
