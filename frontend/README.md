# BusinessDataSight Frontend

React + Vite + TypeScript chat UI for database analytics.

## Runtime Flow

1. `App.tsx` owns persisted settings: theme, model, API key, DB URL, optional executor model.
2. `useAppLogic.ts` owns sessions, interactions, saved prompts, query submit/cancel, history polling, SSE resume.
3. `api/api.ts` targets `/api/v1` by default, or `VITE_API_BASE_URL` when set.
4. `ChatInputArea.tsx` submits natural-language query or saved prompt direct SQL.
5. `analysisStream.ts` drains backend SSE, maps `query_id`, `status`, `thinking`, `report`, `usage`, `result` events into interaction state.
6. `InteractionItem.tsx` renders user message, live status/thinking, Markdown text, SQL modal, tables, charts, usage.
7. `RawDataTable.tsx` renders virtualized data grid, starts open, supports filter/sort/fullscreen.
8. `ChartDisplay.tsx` renders Recharts visualizations from hydrated chart config.

## Commands

- `bun run dev`: Vite dev server on port `5173`.
- `bun run build`: TypeScript build + Vite production build.
- `bun run lint`: ESLint.
- `bun run preview`: preview production build.

## Environment

- `VITE_API_BASE_URL`: optional API base URL. If missing, dev ports infer `http://<host>:8000/api/v1`; production uses `/api/v1`.
- `VITE_USD_TO_INR`: optional cost conversion rate.
