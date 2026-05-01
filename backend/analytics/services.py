import os
from deepagents import create_deep_agent
from django.conf import settings
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_community.utilities import SQLDatabase

from analytics.models import QueryHistory
from analytics.schemas import AnalyticsRequest, AnalyticsResponse
from analytics.prompts import SYSTEM_PROMPT


import json

def process_analytics_query(payload: AnalyticsRequest):
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
    # If it's sqlserver/mssql, ensure it uses pymssql driver
    elif db_uri.startswith("sqlserver://") or db_uri.startswith("mssql://") or db_uri.startswith("mssql+pymssql://"):
        if db_uri.startswith("sqlserver://"):
            db_uri = db_uri.replace("sqlserver://", "mssql+pymssql://", 1)
        elif db_uri.startswith("mssql://") and not db_uri.startswith("mssql+pymssql://"):
            db_uri = db_uri.replace("mssql://", "mssql+pymssql://", 1)
        
        # pymssql does not support JDBC-style kwargs like encrypt=true & trustServerCertificate=true
        from urllib.parse import urlparse, urlencode, parse_qs
        parsed = urlparse(db_uri)
        if parsed.query:
            # Parse existing query arguments into a dict
            qs = parse_qs(parsed.query)
            
            # Remove keys safely (lowercase comparison)
            keys_to_remove = [k for k in qs.keys() if k.lower() in ("encrypt", "trustservercertificate")]
            for k in keys_to_remove:
                qs.pop(k, None)
                
            # Re-encode and reconstruct string
            new_query = urlencode(qs, doseq=True)
            db_uri = parsed._replace(query=new_query).geturl()

    engine_args = {
        "pool_pre_ping": True,
    }
    if not db_uri.startswith("sqlite"):
        engine_args.update({
            "pool_size": 5,
            "max_overflow": 10,
        })
    
    if db_uri.startswith("mssql+pymssql://"):
        engine_args["connect_args"] = {"timeout": 15, "login_timeout": 15}

    from sqlalchemy import inspect, create_engine
    # Temporary engine to detect the best schema
    temp_engine = create_engine(db_uri, **engine_args)
    inspector = inspect(temp_engine)
    
    active_schema = None
    # If default schema is empty, try to find one with tables (common in migrated DBs)
    if not inspector.get_table_names():
        for s in inspector.get_schema_names():
            if s not in ['information_schema', 'pg_catalog', 'public']:
                if inspector.get_table_names(schema=s):
                    active_schema = s
                    break
    temp_engine.dispose()
    if active_schema and "postgresql" in db_uri:
        from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
        parsed = urlparse(db_uri)
        qs = parse_qs(parsed.query)
        qs['options'] = [f"-c search_path={active_schema},public"]
        db_uri = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
        # Once search_path is set, we don't need to pass schema to SQLDatabase
        active_schema = None

    # Initialize the database connection dynamically for this request
    db = SQLDatabase.from_uri(
        db_uri,
        engine_args=engine_args,
        schema=active_schema,
        sample_rows_in_table_info=0,
        view_support=False,
        include_tables=[],
    )

    from sqlalchemy import inspect
    from django.core.cache import cache
    import hashlib

    # Cache table names to avoid re-scanning the whole DB on every turn
    db_hash = hashlib.md5(db_uri.encode()).hexdigest()
    cache_key = f"db_tables_{db_hash}"
    usable_tables = cache.get(cache_key)

    if usable_tables is None:
        try:
            usable_tables = db.get_usable_table_names()
            cache.set(cache_key, usable_tables, 3600)
        except Exception:
            usable_tables = []

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

    def _get_table_schema(table_names: str) -> str:
        try:
            tables = [t.strip() for t in table_names.split(",") if t.strip()]
            inspector = inspect(db._engine)
            output = []
            for t in tables:
                columns = inspector.get_columns(t, schema=db._schema)
                cols_str = ", ".join([f"{c['name']} {str(c['type'])}" for c in columns])
                output.append(f"Table '{t}' columns: {cols_str}")
            return "\n".join(output) if output else "No tables found."
        except Exception as e:
            return f"Error getting table info: {str(e)}"

    @tool
    def get_table_info(table_names: str) -> str:
        """
        Get the schema for the specified tables.
        Pass a comma-separated list of table names, e.g., 'users, orders'.
        """
        return _get_table_schema(table_names)

    # If the DB has too many tables, only provide the names to prevent hanging and context overflow
    if len(usable_tables) > 15:
        schema_context = f"Database contains {len(usable_tables)} tables.\nTable names: {', '.join(usable_tables)}\nUse the `get_table_info(table_names)` tool to inspect the exact columns of relevant tables before writing queries."
    else:
        schema_context = _get_table_schema(",".join(usable_tables)) if usable_tables else "No tables available in the database."

    formatted_prompt = SYSTEM_PROMPT.format(db_schema=schema_context)

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
            tools=[execute_read_only_sql, get_table_info],
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

        # Use agent.stream with 'messages' mode to get tokens for real-time streaming
        from langchain_core.utils.json import parse_partial_json
        from langchain_core.messages import AIMessage
        
        yield f"data: {json.dumps({'status': 'Initializing AI agent...'})}\n\n"

        full_content = ""
        last_tool_args = {}
        # We use stream_mode="messages" to get incremental tokens
        for msg, metadata in agent.stream({"messages": messages}, stream_mode="messages"):
            # Accumulate content from AI messages
            if isinstance(msg, AIMessage):
                if msg.content:
                    full_content += msg.content
                
                # If the model uses a tool call for structured output (common in some providers),
                # we need to extract report from the tool arguments
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        if tc['name'] in ['AnalyticsResponse', 'structured_response']:
                            last_tool_args = tc.get('args', {})
                            if isinstance(last_tool_args, dict) and 'report' in last_tool_args:
                                yield f"data: {json.dumps({'report': last_tool_args['report']})}\n\n"

                try:
                    if full_content:
                        # Try to parse the partial JSON to extract the 'report' field
                        partial_data = parse_partial_json(full_content)
                        if isinstance(partial_data, dict) and "report" in partial_data:
                            yield f"data: {json.dumps({'report': partial_data['report']})}\n\n"
                except Exception:
                    pass

            # Signal specific tool calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                 for tc in msg.tool_calls:
                     if tc['name'] == 'execute_read_only_sql':
                         sql = tc['args'].get('query', '')
                         # Truncate SQL for cleaner status UI
                         short_sql = (sql[:60] + '...') if len(sql) > 60 else sql
                         yield f"data: {json.dumps({'status': f'SQL: {short_sql}'})}\n\n"
                     elif tc['name'] not in ['AnalyticsResponse', 'structured_response']:
                         yield f"data: {json.dumps({'status': f'Tool: {tc['name']}'})}\n\n"

        # Final pass to get the full structured response
        try:
            if full_content:
                final_result = parse_partial_json(full_content)
            elif last_tool_args:
                final_result = last_tool_args
            else:
                final_result = {"report": "No output generated."}
        except Exception:
            final_result = last_tool_args if last_tool_args else {"report": full_content}

        # Robust extraction of the structured response (same logic as before)
        ans = final_result
        if isinstance(ans, dict):
            if "structured_response" in ans:
                ans = ans["structured_response"]
            elif "output" in ans:
                ans = ans["output"]
            # ... (rest of extraction logic) ...
        
        # (Re-using the extraction and saving logic from before)
        # To avoid repeating too much, I'll just keep the extraction logic 
        # but yield it as a JSON chunk.

        # ... extraction logic ...
        if isinstance(ans, dict):
            report = ans.get("report", "")
            chart_config = ans.get("chart_config")
            raw_data = ans.get("raw_data")
            sql_query = ans.get("sql_query", "")
        else:
            report = getattr(ans, "report", str(ans))
            chart_config = (
                ans.chart_config.model_dump()
                if hasattr(ans, "chart_config") and hasattr(ans.chart_config, "model_dump") and ans.chart_config
                else getattr(ans, "chart_config", None)
            )
            raw_data = getattr(ans, "raw_data", None)
            sql_query = getattr(ans, "sql_query", "")

        QueryHistory.objects.create(
            session_id=payload.session_id,
            query=payload.query,
            report=report,
            chart_config=chart_config,
            raw_data=raw_data,
            sql_query=sql_query,
        )

        # Yield final complete result
        yield f"data: {json.dumps({
            'report': report,
            'chart_config': chart_config,
            'raw_data': raw_data,
            'sql_query': sql_query,
            'done': True
        })}\n\n"

    finally:
        if env_var_name:
            if original_key is not None:
                os.environ[env_var_name] = original_key
            else:
                del os.environ[env_var_name]
