import axios from "axios";

const HOST = window.location.hostname;
const PROTOCOL = window.location.protocol; // http: or https:
const BASE_URL = `${PROTOCOL}//${HOST}:8000/api/v1`;

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

  submitQuery: async (payload: any) => {
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
