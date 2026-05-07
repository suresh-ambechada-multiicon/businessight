export interface Interaction {
  id?: number | string;
  session_id?: string;
  query: string;
  saved_prompt_name?: string;
  result: InteractionResult | null;
  status?: string;
  usage?: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost: number;
  };
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
