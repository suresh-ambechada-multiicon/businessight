import axios from "axios";

const envBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
const inferDefaultBaseUrl = () => {
  const { hostname, protocol, port } = window.location;
  const isTypicalDevPort = port === "5173" || port === "3000" || port === "4173";
  if (isTypicalDevPort) {
    return `${protocol}//${hostname}:8000/api/v1`;
  }
  return "/api/v1";
};
const BASE_URL = (envBaseUrl && envBaseUrl.trim()) || inferDefaultBaseUrl();

/** POST /query/ body — matches backend `AnalyticsRequest` (snake_case). */
export interface AnalyticsQueryPayload {
  query: string;
  model: string;
  api_key: string;
  db_url: string;
  session_id: string;
  direct_sql?: string;
  direct_sqls?: string[];
  executor_model?: string | null;
}

export const api = {
  fetchSessions: async () => {
    const response = await axios.get(`${BASE_URL}/sessions/`);
    return response.data;
  },

  fetchHistory: async (sessionId?: string) => {
    const params = sessionId ? `?session_id=${sessionId}` : "";
    const response = await axios.get(`${BASE_URL}/history/${params}`);
    return response.data;
  },

  deleteSession: async (sessionId: string) => {
    await axios.post(`${BASE_URL}/delete-session/?session_id=${sessionId}`);
  },

  cancelQuery: async (sessionId: string) => {
    await axios.post(`${BASE_URL}/cancel/?session_id=${sessionId}`);
  },

  fetchQueryData: async (queryId: string | number, options?: { signal?: AbortSignal }) => {
    const response = await axios.get(`${BASE_URL}/history/${queryId}/data/`, {
      signal: options?.signal,
    });
    return response.data;
  },

  fetchModels: async () => {
    const response = await axios.get(`${BASE_URL}/models/`);
    return response.data;
  },

  submitQuery: async (payload: AnalyticsQueryPayload) => {
    const response = await fetch(`${BASE_URL}/query/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error("Failed to submit query");
    return response.json(); // returns { task_id: ... }
  },

  streamResults: (taskId: string, signal: AbortSignal) => {
    return fetch(`${BASE_URL}/stream/${taskId}/`, {
      method: "GET",
      signal,
    });
  },

  fetchSavedPrompts: async () => {
    const response = await axios.get(`${BASE_URL}/prompts/`);
    return response.data;
  },

  createSavedPrompt: async (payload: { name: string; query: string; sql_command: string }) => {
    const response = await axios.post(`${BASE_URL}/prompts/`, payload);
    return response.data;
  },

  renameSavedPrompt: async (id: number, name: string) => {
    const response = await axios.put(`${BASE_URL}/prompts/${id}/`, { name });
    return response.data;
  },

  deleteSavedPrompt: async (id: number) => {
    const response = await axios.delete(`${BASE_URL}/prompts/${id}/`);
    return response.data;
  },
};
