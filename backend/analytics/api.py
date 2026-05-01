import os

from deepagents import create_deep_agent
from django.conf import settings
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_community.utilities import SQLDatabase
from ninja import NinjaAPI

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse

api = NinjaAPI()


@api.get("/history/")
def get_history(request):
    history = QueryHistory.objects.all()
    res = []
    for h in history:
        res.append(
            {
                "session_id": h.session_id,
                "query": h.query,
                "result": {
                    "report": h.report,
                    "chart_config": h.chart_config,
                    "raw_data": h.raw_data,
                    "sql_query": h.sql_query,
                },
            }
        )
    return res


@api.post("/query/", response=AnalyticsResponse)
def query_analytics(request, payload: AnalyticsRequest):
    # Determine the database URI to use.
    # Use the payload's db_url if provided, otherwise fallback to the environment or local sqlite.
    db_uri = payload.db_url.strip()
    if not db_uri:
        db_uri = os.environ.get(
            "DATABASE_URL", f"sqlite:///{settings.BASE_DIR}/db.sqlite3"
        )

    # LangChain uses SQLAlchemy under the hood. If it's postgres, ensure it uses psycopg2
    if db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql+psycopg2://", 1)
    elif db_uri.startswith("postgresql://") and not db_uri.startswith(
        "postgresql+psycopg2://"
    ):
        db_uri = db_uri.replace("postgresql://", "postgresql+psycopg2://", 1)
    # If it's mysql, ensure it uses pymysql driver
    elif db_uri.startswith("mysql://") and not db_uri.startswith("mysql+pymysql://"):
        db_uri = db_uri.replace("mysql://", "mysql+pymysql://", 1)

    # Initialize the database connection dynamically for this request
    db = SQLDatabase.from_uri(db_uri)

    @tool
    def execute_read_only_sql(query: str) -> str:
        """
        Executes a read-only SQL SELECT query against the connected database.
        Use this tool to fetch data to answer the user's analytical questions.
        """
        if not query.strip().upper().startswith("SELECT"):
            return "Error: Only SELECT queries are allowed."
        try:
            return db.run(query)
        except Exception as e:
            return f"Error executing query: {str(e)}"

    SYSTEM_PROMPT = f"""You are a senior business data analyst. Your goal is to answer the user's question by analyzing the database.
You have access to an `execute_read_only_sql` tool to run SQL SELECT queries.

Database Schema:
{db.get_table_info()}

Instructions:
1. Understand the user's question.
2. Generate a valid SQL SELECT query to retrieve the necessary data.
3. Call the `execute_read_only_sql` tool with your query.
4. If the query fails, analyze the error, fix the SQL, and try again.
5. Once you have the data, synthesize a comprehensive business report.
6. Design an appropriate chart (choose exactly one: 'bar', 'line', 'pie', 'area', 'radar') to visualize the findings. Use 'line' or 'area' for time-series/trends, 'bar' for categorical comparisons, 'pie' for proportions, and 'radar' for multivariate comparisons. ONLY generate a chart if the data contains multiple data points that benefit from visualization. If the user asks for a single number (e.g. "What is the total revenue?"), a definition, or a simple text answer, omit the chart_config (return null/None).
7. Include the exact SQL query you successfully executed to fetch the data in the final structured response matching the requested format.
"""

    # Dynamically initialize the LLM using the provided key and model
    provider = payload.model.split(":")[0] if ":" in payload.model else "openai"
    env_key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google_genai": "GOOGLE_API_KEY",
    }
    env_var_name = env_key_map.get(provider)

    original_key = None
    if env_var_name:
        original_key = os.environ.get(env_var_name)
        os.environ[env_var_name] = payload.api_key

    try:
        llm = init_chat_model(payload.model)

        agent = create_deep_agent(
            model=llm,
            tools=[execute_read_only_sql],
            system_prompt=SYSTEM_PROMPT,
            response_format=AnalyticsResponse,
        )

        result = agent.invoke(
            {"messages": [{"role": "user", "content": payload.query}]}
        )

        ans = result["structured_response"]

        # Determine how to extract fields depending on whether ans is a Pydantic model or dict
        if isinstance(ans, dict):
            report = ans.get("report", "")
            chart_config = ans.get("chart_config")
            raw_data = ans.get("raw_data")
            sql_query = ans.get("sql_query", "")
        else:
            report = ans.report
            # Handle Pydantic model serialization if needed
            chart_config = (
                ans.chart_config.model_dump()
                if hasattr(ans.chart_config, "model_dump") and ans.chart_config
                else (
                    getattr(ans.chart_config, "dict", lambda: ans.chart_config)()
                    if ans.chart_config
                    else None
                )
            )
            raw_data = ans.raw_data
            sql_query = getattr(ans, "sql_query", "")

        QueryHistory.objects.create(
            session_id=payload.session_id,
            query=payload.query,
            report=report,
            chart_config=chart_config,
            raw_data=raw_data,
            sql_query=sql_query,
        )

        return ans

    finally:
        if env_var_name:
            if original_key is not None:
                os.environ[env_var_name] = original_key
            else:
                del os.environ[env_var_name]
