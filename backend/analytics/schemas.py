from typing import Any, Dict, List

from pydantic import BaseModel, Field


class AnalyticsRequest(BaseModel):
    query: str = Field(description="The natural language question to ask the database.")
    model: str = Field(
        description="The provider and model string (e.g., 'openai:gpt-4o', 'anthropic:claude-3-5-sonnet-latest')."
    )
    api_key: str = Field(description="The API key for the selected provider.")
    db_url: str = Field(
        default="",
        description="The connection string for the database to analyze (e.g. postgres://user:pass@host/db).",
    )
    session_id: str = Field(
        default="default",
        description="The ID of the session this query belongs to.",
    )


class ChartDataset(BaseModel):
    label: str
    data: List[float]


class ChartData(BaseModel):
    labels: List[str]
    datasets: List[ChartDataset]


class ChartConfig(BaseModel):
    type: str = Field(
        description="The type of chart (e.g., 'bar', 'line', 'pie', 'doughnut', 'scatter')."
    )
    data: ChartData = Field(
        description="The data payload for the chart, including labels and datasets."
    )


class AnalyticsResponse(BaseModel):
    report: str = Field(
        description="A comprehensive natural language business report answering the user's query."
    )
    chart_config: ChartConfig | None = Field(
        default=None,
        description="JSON configuration representing the chart data. Omit this (return null) if the user's query does not warrant a chart (e.g., asking for a single metric).",
    )
    raw_data: List[Dict[str, Any]] = Field(
        description="The raw query results from the database."
    )
    sql_query: str = Field(
        default="",
        description="The exact SQL query that was successfully executed to retrieve the raw_data.",
    )
