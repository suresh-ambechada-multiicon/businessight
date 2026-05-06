export interface Interaction {
  id?: number | string;
  query: string;
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
