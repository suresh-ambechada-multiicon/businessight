import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "../api/api";
import type { Interaction, Session } from "../types";

export const useAppLogic = () => {
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    return localStorage.getItem("currentSessionId") || Date.now().toString();
  });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const loadedSessionsRef = useRef<Set<string>>(new Set());

  // Sync session to localStorage
  useEffect(() => {
    localStorage.setItem("currentSessionId", currentSessionId);
  }, [currentSessionId]);

  // Fetch session list on mount (fast — no heavy data)
  useEffect(() => {
    const fetchSessions = async () => {
      try {
        const data = await api.fetchSessions();
        const mapped: Session[] = data.map((s: any) => ({
          id: String(s.id),
          title: s.title || "New Chat",
          count: s.count || 0,
          last_activity: s.last_activity || "",
        }));
        setSessions(mapped);

        // Select persisted session or most recent
        const persistedSid = localStorage.getItem("currentSessionId");
        const sessionExists = mapped.some((s) => s.id === persistedSid);

        if (persistedSid && sessionExists) {
          setCurrentSessionId(persistedSid);
        } else if (mapped.length > 0) {
          setCurrentSessionId(mapped[0].id);
        }
      } catch (error) {
        console.error("Failed to fetch sessions", error);
      }
    };
    fetchSessions();
  }, []);

  // Load history for current session (lazy — only when session changes)
  const loadSessionHistory = useCallback(async (sessionId: string) => {
    if (loadedSessionsRef.current.has(sessionId)) return;

    try {
      const data = await api.fetchHistory(sessionId);
      const mappedData = data.map((item: any, idx: number) => ({
        ...item,
        id: item.id || `hist-${idx}-${Date.now()}`,
        session_id: String(item.session_id || "default"),
      }));

      loadedSessionsRef.current.add(sessionId);

      setInteractions((prev) => {
        const existingIds = new Set(prev.map((i) => i.id));
        const newItems = mappedData.filter(
          (i: any) => !existingIds.has(i.id),
        );
        return [...prev, ...newItems];
      });
    } catch (error) {
      console.error("Failed to fetch session history", error);
    }
  }, []);

  // Trigger history load when session changes
  useEffect(() => {
    if (currentSessionId) {
      loadSessionHistory(currentSessionId);
    }
  }, [currentSessionId, loadSessionHistory]);

  const handleNewChat = () => {
    const newId = Date.now().toString();
    setCurrentSessionId(newId);
    setSessions((prev) => [
      { id: newId, title: "New Chat...", count: 0, last_activity: "" },
      ...prev,
    ]);
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      setInteractions((prev) =>
        prev.filter((i) => (i as any).session_id !== sessionId),
      );
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      loadedSessionsRef.current.delete(sessionId);
      if (currentSessionId === sessionId) {
        handleNewChat();
      }
    } catch (error) {
      console.error("Failed to delete session", error);
      alert("Failed to delete session.");
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    api
      .cancelQuery(currentSessionId)
      .catch((err) =>
        console.error("Failed to signal backend cancellation", err),
      );
    setIsLoading(false);

    setInteractions((prev) => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1];
      if (!last.result) {
        return prev.map((i, idx) =>
          idx === prev.length - 1
            ? {
                ...i,
                status: "Analysis stopped.",
                result: { report: "_Analysis cancelled by user._" },
              }
            : i,
        );
      }
      return prev;
    });
  };

  const handleQuery = async (
    query: string,
    model: string,
    apiKey: string,
    dbUrl: string,
  ) => {
    const newInteractionId = Date.now();
    setInteractions((prev) => [
      ...prev,
      {
        id: newInteractionId,
        session_id: currentSessionId,
        query,
        result: null,
      } as any,
    ]);
    setIsLoading(true);

    // Update session title if this is the first query
    setSessions((prev) => {
      const idx = prev.findIndex((s) => s.id === currentSessionId);
      if (idx !== -1 && (prev[idx].title === "New Chat..." || prev[idx].title === "New Chat")) {
        const updated = [...prev];
        updated[idx] = { ...updated[idx], title: query.slice(0, 80) };
        return updated;
      }
      return prev;
    });

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await api.submitQuery({
        query,
        model,
        api_key: apiKey,
        db_url: dbUrl,
        session_id: currentSessionId,
      });

      const taskId = response.task_id;
      const streamResponse = await api.streamResults(taskId, controller.signal);

      if (!streamResponse.ok)
        throw new Error(`HTTP error! status: ${streamResponse.status}`);

      const reader = streamResponse.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmedLine = line.trim();
            if (!trimmedLine || !trimmedLine.startsWith("data: ")) continue;

            try {
              const payload = JSON.parse(trimmedLine.slice(6));
              const eventType = payload.event;
              const eventData = payload.data || {};

              setInteractions((prev) =>
                prev.map((i) => {
                  if (i.id !== newInteractionId) return i;
                  const updatedInteraction = { ...i };

                  if (eventType === "status") {
                    updatedInteraction.status = eventData.message;
                  } else if (eventType === "tool") {
                    if (eventData.name === "execute_read_only_sql") {
                      updatedInteraction.status = `SQL: ${eventData.args?.query || ""}`;
                    } else {
                      updatedInteraction.status = `Tool: ${eventData.name}`;
                    }
                  } else if (eventType === "report" || eventType === "result") {
                    const prevReport = updatedInteraction.result?.report || "";
                    const newReport =
                      eventData.report || eventData.content || "";
                    const isDone = eventType === "result";

                    updatedInteraction.result = {
                      ...(updatedInteraction.result || {}),
                      ...eventData,
                      report:
                        isDone && !newReport
                          ? prevReport
                          : newReport || prevReport,
                    };
                  } else if (eventType === "error") {
                    const errorMsg =
                      eventData.error || eventData.message || "Unknown error";
                    updatedInteraction.status = `Error: ${errorMsg}`;
                    setIsLoading(false);
                    if (!updatedInteraction.result) {
                      updatedInteraction.result = { report: errorMsg } as any;
                    }
                  } else if (eventType === "usage") {
                    updatedInteraction.usage = eventData;
                  }

                  return updatedInteraction;
                }),
              );
            } catch (e) {
              console.error("Error parsing stream chunk", e, trimmedLine);
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === "AbortError") return;
      console.error("Query failed", error);
      setInteractions((prev) =>
        prev.map((i) =>
          i.id === newInteractionId
            ? {
                ...i,
                result: { report: `An error occurred: ${error.message}` },
              }
            : i,
        ),
      );
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  return {
    currentSessionId,
    setCurrentSessionId,
    sessions,
    interactions,
    setInteractions,
    isLoading,
    handleNewChat,
    handleDeleteSession,
    handleStop,
    handleQuery,
  };
};
