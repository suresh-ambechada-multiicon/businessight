from typing import List

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, description="Override max output tokens")
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
    verifier_model: str | None = Field(
        default=None,
        description=(
            "Optional model for post-hoc report vs. data verification. "
            "Defaults to `model`. A fast/cheap model is usually enough."
        ),
    )
    semantic_table_rank: bool = Field(
        default=True,
        description=(
            "When true and the catalog is large, rank tables with keyword overlap plus "
            "embeddings (Google/OpenAI only) to surface query-relevant tables in schema context."
        ),
    )
    verify_answer: bool = Field(
        default=True,
        description="When true, run a short LLM pass to flag unsupported claims in the report vs. result data.",
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
        description="Pre-defined SQL to execute directly instead of letting AI generate it."
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


class AnalyticsResponse(BaseModel):
    report: str = Field(
        description=(
            "A natural language summary of the query results. Use Markdown (headers, bold, lists). MUST NOT BE EMPTY. "
            "For LIST/SHOW queries: state the total count (e.g. 'Found 150 dormant agents'), then highlight key patterns, "
            "distributions, or notable entries. Do NOT dump all rows — the raw data grid handles that. "
            "For ANALYTICAL queries: provide deep insights, trends, comparisons, and percentages. "
            "For DETAIL queries: format the entity details with bullet points and bold labels."
        )
    )
    chart_config: ChartConfig | None = Field(
        description="Chart JSON. Mandatory for trends/multiple values."
    )
    sql_query: str = Field(
        default="",
        description="The exact SQL query that generated the data used for this report."
    )
