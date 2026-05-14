# BusinessDataSight Backend

Backend is Django Ninja API + Celery worker + Redis streams for long-running data analysis.

## Runtime Flow

1. Frontend submits `POST /api/v1/query/` with question, model, API key, DB URL, session ID, optional direct SQL.
2. API enqueues `process_query_task` and returns Celery `task_id`.
3. Frontend opens `GET /api/v1/stream/{task_id}/`.
4. Celery creates `RequestContext`, sets Redis heartbeat, runs `AnalyticsPipeline`.
5. Pipeline normalizes DB URI, detects active schema, creates pooled SQLAlchemy/LangChain SQL DB, discovers usable tables.
6. Pipeline ranks tables, builds schema context, estimates token budget, creates DB tools.
7. Provider branch runs:
   - Runware: direct HTTP JSON SQL-planning loop, max 6 rounds.
   - Non-Runware: DeepAgents/LangChain tool-calling loop.
8. Backend hydrates result blocks by validating and executing read-only SQL server-side.
9. Runware path streams final evidence-only Markdown answer from executed rows/stats.
10. Pipeline stores final result in `QueryHistory`, streams `usage`, `result`, then Celery writes `done`.

## API Mount

Actual mount is `/api/v1/` from `BusinessSight/urls.py`.

Main endpoints:

- `POST /api/v1/query/` enqueue analysis.
- `GET /api/v1/stream/{task_id}/` Redis-backed SSE stream.
- `POST /api/v1/cancel/?session_id=...` cancel session work.
- `GET /api/v1/sessions/` sidebar sessions.
- `GET /api/v1/history/?session_id=...` session history.
- `GET /api/v1/history/{query_id}/data/` historical raw rows.
- `POST /api/v1/delete-session/?session_id=...` soft delete.
- `GET /api/v1/models/` model registry.
- `GET|POST /api/v1/prompts/`, `PUT|DELETE /api/v1/prompts/{id}/` saved prompts.

## Key Files

- `BusinessSight/settings.py`: Django, CORS, Redis cache, Celery, logging.
- `BusinessSight/celery.py`: Celery app autodiscovery.
- `analytics/api/`: Ninja routers.
- `analytics/tasks.py`: Celery task, Redis stream writer, error/done sentinels.
- `analytics/services/pipeline/orchestrator.py`: high-level lifecycle coordinator.
- `analytics/services/pipeline/runware_loop.py`: Runware multi-round SQL planning loop.
- `analytics/services/pipeline/hydration.py`: result-block hydrator class.
- `analytics/services/pipeline/sql_execution.py`: safe read-only SQL execution helpers.
- `analytics/services/pipeline/lookup_enrichment.py`: ID-to-display lookup enrichment.
- `analytics/services/pipeline/finalization.py`: usage, persistence, final SSE events.
- `analytics/services/runware/`: Runware client, prompts, parsing, usage, task logging.
- `analytics/services/agent/core/runware.py`: compatibility facade for existing imports.
- `analytics/services/agent/core/streaming.py`: DeepAgents stream processing.
- `analytics/services/agent/tools.py`: active LangChain tool set.
- `analytics/services/agent/tool_definitions/core/`: SQL/schema inspection tools.
- `analytics/services/agent/tool_definitions/analytics/aggregation.py`: generic grouped aggregate tool.
- `analytics/services/agent/logic/reporting.py`: evidence extraction + verified answer placement.
- `analytics/services/database/connection.py`: URI normalization, schema detection, table discovery.
- `analytics/services/database/security.py`: read-only SQL validation.
- `analytics/services/cache/redis.py`: Redis schema/result cache + SQLAlchemy engine pool.
- `analytics/models/query.py`: `QueryHistory`, `RunwareTaskLog`.
- `analytics/models/prompt.py`: `SavedPrompt`.

## Evidence Rule

Final user-facing answer must come from backend-executed SQL evidence. LLM may propose SQL and wording, but raw rows/chart data are hydrated server-side.
