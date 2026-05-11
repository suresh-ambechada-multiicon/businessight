# Implementation Report: Genie-Style Analytics Enhancements

This document summarizes backend capabilities added to align the analytics agent with patterns similar to **Databricks Genie**: query-aware retrieval over large catalogs, optional multi-model routing, post-hoc verification of the narrative against data, richer schema context, persisted agent traces, and usage accounting that includes the verifier pass.

---

## 1. API request surface (`AnalyticsRequest`)

Defined in `backend/analytics/schemas.py`.

| Field | Default | Purpose |
|--------|---------|---------|
| `model` | (required) | Primary model identifier for the session / billing context. |
| `executor_model` | `null` → uses `model` | Runs the **main deep agent** (tool use, SQL, report). Lets you use a stronger model for hard queries or a cheaper one for exploration. |
| `verifier_model` | `null` → uses `model` | Runs the **post-hoc verification** LLM call. Often a fast/cheap model is enough. |
| `semantic_table_rank` | `true` | Enables embedding-assisted table ranking when provider and catalog size allow (see §2). |
| `verify_answer` | `true` | Runs verification after the agent finishes (see §3). |

Existing clients that omit these fields keep prior behavior in spirit: same model for executor and verifier, ranking and verification on by default.

---

## 2. Query-aware table retrieval

**Module:** `backend/analytics/services/agent/table_retrieval.py`  
**Entry point:** `rank_tables_for_query(...)`

**Behavior:**

- **Keyword layer (always):** token overlap on table names (and light substring signals) so relevant tables bubble up with zero embedding cost.
- **Semantic layer (optional):** when `semantic_table_rank` is true, the catalog has more than eight tables, an API key is present, and the **primary** `model` string indicates **Google GenAI** or **OpenAI**, the service embeds short “table documents” (name + optional column hints) and scores cosine similarity to the embedded user query.
- **Embeddings cache:** Redis/Django cache key `tblrank:emb:v1:{db_uri_hash}:{catalog_fingerprint}`, TTL **3600** seconds. At most **120** tables are embedded per rank; batch size **32**.
- **Column hints:** `core.py` passes a `column_hint_fn` backed by `get_cached_column_info` so table documents include cached column strings when available.

**Orchestration:** `backend/analytics/services/core.py` calls `rank_tables_for_query` after discovery, then passes the ordered list into `build_schema_context` as `table_rank_order`.

**Provider note:** Anthropic-only primary models fall back to **keyword-only** ranking (no silent cross-provider embedding).

---

## 3. Richer schema context for large catalogs

**Module:** `backend/analytics/services/agent/runner.py` — `build_schema_context(...)`

**Parameters:**

- `table_rank_order` — order used to prioritize which tables get **full column detail** when the catalog is large.
- `skip_full_context_cache` — when `len(usable_tables) > 15`, `core.py` sets this so a **query-specific** ranked context is not served from a single global cached schema string for all questions.

Together, this biases prompt context toward tables likely relevant to the current question while controlling token growth.

---

## 4. Post-hoc answer verification

**Module:** `backend/analytics/services/agent/answer_verifier.py`  
**Function:** `verify_report_against_data(...)`

**Behavior:**

- After the agent produces a report (and SQL / raw rows are available), a **single** tight LLM call checks whether obvious factual/numeric claims in the report are **unsupported** by a JSON sample of result rows (up to **25** rows, truncated payloads).
- Contract: model returns **one line of JSON** `{"consistent": bool, "issues": [...]}` (max five short issue strings).
- LLM settings: when `llm_config` supports `model_copy`, verification uses `max_tokens=1024` and `temperature=0.05`.
- **Non-blocking:** on parse errors or exceptions, the pipeline returns `consistent: true` with empty issues and logs a warning.

**User-visible outcome:** If inconsistent and issues exist, `core.py` appends a **Verification note** bullet list to the markdown report.

**Orchestration:** `core.py` emits an SSE **status** event (“Verifying report…”), calls the verifier when `verify_answer` is true, and appends a `verification` step to `agent_trace` (see §5).

---

## 5. Persisted agent traces

**Storage:** `QueryHistory.agent_trace` — `JSONField(null=True, blank=True)` on the history model (kept in sync in `backend/analytics/models.py` and `backend/analytics/models/query.py`).

**Migration:** `backend/analytics/migrations/0012_queryhistory_agent_trace.py`

**Content:**

- During streaming, `StreamResult.trace` in `runner.py` records tool usage: timestamp, tool name, and for `execute_read_only_sql` a **`sql_preview`** (first **500** characters). Other tools log name only.
- Tool call `args` are normalized when they arrive as JSON strings (robustness fix in the streaming loop).
- After the run, `core.py` copies `stream_data["trace"]` into `agent_trace` and appends a **`verification`** object when verification ran.
- **Simple-query fast path** sets `agent_trace` to `[{"step": "simple_query_fast_path"}]`.
- Direct SQL / mock paths expose an empty trace where applicable so the shape stays consistent.

**API exposure:** `GET` history in `backend/analytics/api/history.py` includes an **`agent_trace`** key on each item when the field is non-empty (audit / replay in the client without a second endpoint).

---

## 6. Token and cost accounting (including verifier)

**Executor segment:** Same basis as before — estimated input from `estimate_query_budget` plus serialized “best” raw tool rows; output from streamed assistant content plus serialized tool arguments. A **1.05** multiplier is applied per segment before aggregation.

**Verifier segment:** `verify_report_against_data` returns `verifier_input_tokens` and `verifier_output_tokens` via `count_tokens(..., verifier_model)`.

**Cost:** `core.py` adds:

- Executor-priced portion using `get_model_config(executor_model or model)`.
- Verifier-priced portion using `get_model_config(verifier_model or model)`.

Totals stored on `QueryHistory` and emitted on the final **`usage`** SSE / result payload.

---

## 7. File map (quick reference)

| Area | Primary files |
|------|----------------|
| Request schema | `backend/analytics/schemas.py` |
| Pipeline orchestration | `backend/analytics/services/core.py` |
| Table ranking | `backend/analytics/services/agent/table_retrieval.py` |
| Schema context + streaming trace | `backend/analytics/services/agent/runner.py` |
| Verification LLM | `backend/analytics/services/agent/answer_verifier.py` |
| History API | `backend/analytics/api/history.py` |
| Persistence | `backend/analytics/models.py`, `backend/analytics/models/query.py`, migration `0012_*` |

---

## 8. Operational checklist

1. **Migrate:** `python manage.py migrate` (apply `0012_queryhistory_agent_trace`).
2. **Cache/Redis:** Table embedding cache uses Django’s cache; ensure production cache is shared appropriately if you run multiple workers.
3. **Frontend (optional):** The new request fields are backend-ready; the web client can pass `executor_model`, `verifier_model`, `semantic_table_rank`, and `verify_answer` when you want UI control. History consumers can read `agent_trace` for tooling / compliance views.

---

## 9. Known limitations (by design)

- Embedding-based ranking requires **Google GenAI** or **OpenAI** primary model naming and key; others use **keyword** ranking only.
- Verification is **sample-based**; small samples or complex multi-query reports may not catch every discrepancy (the prompt instructs the model to prefer `consistent: true` when uncertain).
- `agent_trace` may contain **SQL fragments** (preview only); treat as **sensitive** in the same way as stored `sql_query`.

---

*Document generated to reflect the implemented Genie-style analytics stack; adjust dates and version in your release notes when shipping.*
