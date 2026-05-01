import os
from deepagents import create_deep_agent
from django.conf import settings
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_community.utilities import SQLDatabase

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.prompts import SYSTEM_PROMPT


def process_analytics_query(payload: AnalyticsRequest) -> AnalyticsResponse:
    # Determine the database URI to use.
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

    formatted_prompt = SYSTEM_PROMPT.format(db_schema=db.get_table_info())

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
            system_prompt=formatted_prompt,
            response_format=AnalyticsResponse,
        )

        # Fetch the last 3 interactions to provide 6 past messages of context
        past_interactions = list(
            QueryHistory.objects.filter(session_id=payload.session_id)
            .order_by("-created_at")[:3]
        )
        past_interactions.reverse()

        messages = []
        for interaction in past_interactions:
            messages.append({"role": "user", "content": interaction.query})
            messages.append({"role": "assistant", "content": interaction.report})
        
        messages.append({"role": "user", "content": payload.query})

        result = agent.invoke({"messages": messages})

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
