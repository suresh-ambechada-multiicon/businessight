## 📂 Topic: **Architecture Overview**

**Summary:**
...

> [!STRATEGY]
> **Intent:** I am going to synthesize a comprehensive architectural overview of the BusinessDataSight application, explaining the frontend and backend components and the end-to-end data flow.

## Assistant

Here is a comprehensive breakdown of the **BusinessDataSight** architecture and how the system works end-to-end.

### High-Level Architecture

BusinessDataSight is a real-time, AI-powered database analytics agent. It consists of a React frontend and an asynchronous Django + Celery backend. 

```mermaid
graph TB
    subgraph Frontend ["Frontend (React + Vite)"]
        UI[Chat Interface] -->|1. POST /api/query/| API_CLIENT[api.ts]
        API_CLIENT -->|2. GET /api/stream/{task_id}| SSE[SSE Listener]
    end

    subgraph Backend_API ["Backend API (Django Ninja)"]
        API_EP[api.py] -->|3. enqueue| REDIS_BROKER[(Redis Broker)]
        API_EP <-->|7. read| APP_DB[(PostgreSQL App DB)]
        API_EP -->|4. subscribe| REDIS_PUBSUB[(Redis Pub/Sub)]
    end

    subgraph Celery_Workers ["Async Workers (Celery)"]
        WORKER[Process Query Task] --> CORE[core.py]
        CORE --> DB_POOL[db.py (Connection Pool)]
        CORE --> AGENT[agent.py (LangChain)]
        AGENT --> TOOLS[tools.py (SQL Exec, Schema)]
        AGENT -->|5. publish chunk| REDIS_PUBSUB
        CORE -->|6. save final| APP_DB
    end

    subgraph External ["External Services"]
        DB_POOL -->|read-only| USER_DB[(User's Target Database)]
        AGENT -->|LLM API Call| LLM[Google/OpenAI/Anthropic]
    end

    API_CLIENT -.-> API_EP
    SSE -.-> API_EP
```

---

### Step-by-Step Data Flow

When a user types a query like *"Show me the conversion rates of leads across different services"*:

#### 1. Request Initiation & Queuing (Frontend → Django)
- The React frontend sends a `POST /api/v1/query/` request with the user's natural language query, the selected LLM model, the LLM API key, and the target database URL.
- Django receives this request, immediately pushes a background task to **Celery via Redis**, and responds to the frontend with a `task_id`.
- The frontend then immediately opens a **Server-Sent Events (SSE)** connection to `GET /api/v1/stream/{task_id}/`.

#### 2. Database Connection & Schema Discovery (Celery Worker)
- A Celery worker picks up the task (`core.py`).
- It parses the user's `db_url` and connects to the target database. It supports multiple dialects (PostgreSQL, MySQL, SQL Server, SQLite) using `SQLAlchemy`.
- It dynamically inspects the database schema (tables, columns, foreign keys) and caches this structure in Redis to avoid re-querying the schema on every prompt.

#### 3. AI Agent Loop (LangChain + DeepAgents)
- The worker initializes a LangChain agent with the system prompt, the user's question, and the cached database schema.
- The LLM determines it needs data, so it formulates a SQL query and invokes the `execute_read_only_sql` tool.
- **Security Check:** Before executing, `security.py` runs the SQL through `sqlparse` to guarantee it's a `SELECT` statement and blocks any destructive commands (`DROP`, `UPDATE`, `INSERT`).
- The SQL is executed against the user's database. To prevent context overflow, `tools.py` dynamically calculates how many rows it can safely return based on the remaining token budget.

#### 4. Real-time Streaming (Redis Pub/Sub → SSE → Frontend)
- As the LangChain agent executes tools and streams its final analytical report, the Celery worker intercepts these chunks and publishes them to a **Redis Pub/Sub channel** (`task:{task_id}`).
- The Django SSE endpoint, which the frontend is listening to, is subscribed to this same Redis channel. It forwards the chunks directly to the user's browser.
- This creates the live "typing" effect and shows real-time status updates like "Executing SQL..." in the UI.

#### 5. Final Extraction & Storage
- Once the LLM finishes, `extract_final_result` (`agent.py`) parses the output. It extracts the Markdown `report`, the `sql_query`, the `raw_data`, and any generated `chart_config`.
- It aggregates the total execution time and token usage (`input_tokens`, `output_tokens`).
- This final payload is saved to the `QueryHistory` model in the application's main database (e.g., PostgreSQL or SQLite) for persistence across page refreshes.
- A final `done` event is sent through the SSE stream, telling the frontend to close the connection.

---

### Key Architectural Strengths

1. **Non-Blocking Architecture:** By offloading the LLM processing and database querying to Celery workers, the Django web server never blocks. Dozens of users can query massive databases concurrently without freezing the API.
2. **Database Agnostic:** Using `dj-database-url` and SQLAlchemy allows the agent to connect to almost any SQL database dialect seamlessly.
3. **Context / Token Management:** Instead of hardcoding a 500-row limit, the system actively counts tokens using `tiktoken` and calculates a dynamic row budget to ensure it never exceeds the LLM's context window.
4. **Resilience:** If the user closes their browser mid-query, the Celery worker can either gracefully abort (via the `/api/v1/cancel/` endpoint) or finish the job and save it to the history database so the user sees the result when they return.
