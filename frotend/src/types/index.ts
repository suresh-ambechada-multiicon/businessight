export interface Interaction {
  id?: number | string;
  query: string;
  result: InteractionResult | null;
  status?: string;
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
}
