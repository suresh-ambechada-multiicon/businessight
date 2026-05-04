import axios from "axios";

const BASE_URL = "http://localhost:8000/api";

export const api = {
  fetchHistory: async () => {
    const response = await axios.get(`${BASE_URL}/history/`);
    return response.data;
  },
  
  deleteSession: async (sessionId: string) => {
    await axios.post(`${BASE_URL}/delete-session/?session_id=${sessionId}`);
  },
  
  cancelQuery: async (sessionId: string) => {
    await axios.post(`${BASE_URL}/cancel/?session_id=${sessionId}`);
  },
  
  fetchQueryData: async (queryId: string | number) => {
    const response = await axios.get(`${BASE_URL}/history/${queryId}/data/`);
    return response.data;
  },
  
  submitQuery: async (payload: any, signal: AbortSignal) => {
    return await fetch(`${BASE_URL}/query/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  }
};
