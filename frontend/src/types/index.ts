/** Persisted tool / verification steps from the analytics agent (history API). */
export type AgentTraceEntry = Record<string, unknown>;

export interface ResultBlock {
  kind: "text" | "summary" | "chart" | "table";
  title?: string;
  text?: string;
  sql_query?: string;
  row_count?: number;
  total_count?: number;
  truncated?: boolean;
  chart_config?: {
    type: string;
    x_label?: string;
    y_label?: string;
    data: any;
  };
  raw_data?: any[];
}

export interface InteractionUsage {
  input_tokens: number;
  output_tokens: number;
  thinking_tokens?: number;
  estimated_cost?: number;
}

export interface Interaction {
  id?: number | string;
  session_id?: string;
  /** Celery task id — used to reconnect SSE after refresh while analysis still running */
  task_id?: string | null;
  query: string;
  saved_prompt_name?: string;
  result: InteractionResult | null;
  status?: string;
  thinking?: string;
  usage?: InteractionUsage;
  agent_trace?: AgentTraceEntry[] | null;
}

/** Options sent with each analytics query (Settings → Agent). */
export interface AnalyticsAgentOptions {
  executorModel: string;
}

export interface InteractionResult {
  report: string;
  sql_query?: string;
  chart_config?: {
    type: string;
    x_label?: string;
    y_label?: string;
    data: any;
  };
  raw_data?: any[];
  has_data?: boolean;
  execution_time?: number;
  result_blocks?: ResultBlock[];
}

export interface Session {
  id: string;
  title: string;
  count?: number;
  last_activity?: string;
}

export interface SavedPrompt {
  id: number;
  name: string;
  query: string;
  sql_command: string;
  created_at: string;
}
