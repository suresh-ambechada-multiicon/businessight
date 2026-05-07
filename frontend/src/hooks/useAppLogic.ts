import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "../api/api";
import type { Interaction, Session } from "../types";

export const useAppLogic = () => {
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    return localStorage.getItem("currentSessionId") || Date.now().toString();
  });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [savedPrompts, setSavedPrompts] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  
  const abortControllerRef = useRef<AbortController | null>(null);
  const loadedSessionsRef = useRef<Set<string>>(new Set());

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

    const fetchSavedPrompts = async () => {
      try {
        const data = await api.fetchSavedPrompts();
        setSavedPrompts(data);
      } catch (error) {
        console.error("Failed to fetch saved prompts", error);
      }
    };

    fetchSessions();
    fetchSavedPrompts();
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
      // Cap the set to prevent unbounded growth across session switches
      if (loadedSessionsRef.current.size > 20) {
        const first = loadedSessionsRef.current.values().next().value;
        if (first) loadedSessionsRef.current.delete(first);
      }

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

  // Poll history if there are any incomplete interactions.
  // Uses a ref to avoid putting `interactions` in the dep array (which causes
  // an infinite re-render loop: setInteractions -> deps change -> new interval).
  const needsPollingRef = useRef(false);

  useEffect(() => {
    needsPollingRef.current = interactions.some(
      (i) =>
        String(i.session_id) === String(currentSessionId) &&
        (!i.result || i.result.execution_time === 0)
    );
  }, [interactions, currentSessionId]);

  useEffect(() => {
    if (!currentSessionId) return;

    const interval = setInterval(async () => {
      if (!needsPollingRef.current) return; // Skip poll if nothing is incomplete

      try {
        const data = await api.fetchHistory(currentSessionId);
        const mappedData = data.map((item: any, idx: number) => ({
          ...item,
          id: item.id || `hist-${idx}-${Date.now()}`,
          session_id: String(item.session_id || "default"),
        }));

        setInteractions((prev) => {
          let changed = false;
          const updated = [...prev];

          mappedData.forEach((newItem: any) => {
            const idx = updated.findIndex((i) => i.id === newItem.id);
            if (idx !== -1) {
              const existingItem = updated[idx];
              const wasIncomplete =
                !existingItem.result || existingItem.result.execution_time === 0;
              const isNowComplete =
                newItem.result && newItem.result.execution_time !== 0;

              if (wasIncomplete && isNowComplete) {
                updated[idx] = newItem;
                changed = true;
              }
            } else if (
              String(newItem.session_id) === String(currentSessionId)
            ) {
              const isOptimisticMatch = updated.some(
                (i) =>
                  i.query === newItem.query &&
                  (!i.result || i.result.execution_time === 0)
              );
              if (!isOptimisticMatch) {
                updated.push(newItem);
                changed = true;
              }
            }
          });

          return changed ? updated : prev;
        });
      } catch (error) {
        console.error("Polling history failed", error);
      }
    }, 4000);

    return () => clearInterval(interval);
  }, [currentSessionId]); // Only re-create interval when session changes

  const handleNewChat = useCallback(() => {
    const newId = Date.now().toString();
    setCurrentSessionId(newId);
    setSessions((prev) => [
      { id: newId, title: "New Chat...", count: 0, last_activity: "" },
      ...prev,
    ]);
  }, []);

  const handleDeleteSession = useCallback(async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      setInteractions((prev) =>
        prev.filter((i) => (i as any).session_id !== sessionId),
      );
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      loadedSessionsRef.current.delete(sessionId);
      if (currentSessionId === sessionId) {
        const newId = Date.now().toString();
        setCurrentSessionId(newId);
        setSessions((prev) => [
          { id: newId, title: "New Chat...", count: 0, last_activity: "" },
          ...prev,
        ]);
      }
    } catch (error) {
      console.error("Failed to delete session", error);
      alert("Failed to delete session.");
    }
  }, [currentSessionId]);

  const handleStop = useCallback(() => {
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
      const lastIdx = prev.findLastIndex(
        (i) =>
          ((i as any).session_id || "default") === currentSessionId &&
          !i.result
      );
      if (lastIdx === -1) return prev;
      return prev.map((i, idx) =>
        idx === lastIdx
          ? { ...i, status: "Analysis stopped.", result: { report: "_Analysis cancelled by user._" } }
          : i,
      );
    });
  }, [currentSessionId]);

  const handleQuery = async (
    query: string,
    model: string,
    apiKey: string,
    dbUrl: string,
    directSql?: string,
    promptName?: string
  ) => {
    const newInteractionId = Date.now();
    setInteractions((prev) => [
      ...prev,
      {
        id: newInteractionId,
        session_id: currentSessionId,
        query,
        saved_prompt_name: promptName,
        result: null,
      },
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
      const payload: any = {
        query,
        model,
        api_key: apiKey,
        db_url: dbUrl,
        session_id: currentSessionId,
      };
      if (directSql) {
        payload.direct_sql = directSql;
      }
      
      const response = await api.submitQuery(payload);

      const taskId = response.task_id;
      const streamResponse = await api.streamResults(taskId, controller.signal);

      if (!streamResponse.ok)
        throw new Error(`HTTP error! status: ${streamResponse.status}`);

      const reader = streamResponse.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let activeId: string | number = newInteractionId;

      if (reader) {
        let receivedResult = false;
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

              if (eventType === "result") receivedResult = true;

              // Update activeId BEFORE queuing the state update.
              // This must be outside setInteractions because React Strict Mode
              // double-invokes updater functions — side effects inside updaters
              // corrupt the variable on the second run.
              const prevActiveId = activeId;
              if (eventType === "query_id") {
                activeId = eventData.id;
              }

              setInteractions((prev) =>
                prev.map((i) => {
                  // For query_id, match on the OLD id (prevActiveId)
                  // For everything else, match on the current activeId
                  const matchId = eventType === "query_id" ? prevActiveId : activeId;
                  if (i.id !== matchId) return i;
                  const updatedInteraction = { ...i };

                  if (eventType === "query_id") {
                    updatedInteraction.id = eventData.id;
                  } else if (eventType === "status") {
                    updatedInteraction.status = eventData.message;
                  } else if (eventType === "tool") {
                    if (eventData.name === "execute_read_only_sql") {
                      updatedInteraction.status = `Executing database query...`;
                    } else {
                      updatedInteraction.status = `Tool: ${eventData.name}`;
                    }
                  } else if (eventType === "report" || eventType === "result" || eventType === "delta") {
                    const prevReport = updatedInteraction.result?.report || "";
                    const newContent = eventData.report || eventData.content || "";
                    const isDelta = eventType === "delta";

                    const updatedReport = isDelta ? prevReport + newContent : newContent || prevReport;

                    updatedInteraction.result = {
                      ...(updatedInteraction.result || {}),
                      ...eventData,
                      report: updatedReport,
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

        // --- Fallback: If SSE closed without receiving a result event ---
        // (race condition: worker published before SSE connected, or stream was cut)
        // Immediately poll history to get the completed result from DB.
        if (!receivedResult) {
          try {
            const sessionIdForFetch = currentSessionId;
            const data = await api.fetchHistory(sessionIdForFetch);
            const mappedData = data.map((item: any, idx: number) => ({
              ...item,
              id: item.id || `hist-${idx}-${Date.now()}`,
              session_id: String(item.session_id || "default"),
            }));

            setInteractions((prev) => {
              const updated = [...prev];
              mappedData.forEach((newItem: any) => {
                const idx = updated.findIndex((i) => i.id === newItem.id || 
                  (i.id === activeId && String(newItem.session_id) === String(sessionIdForFetch)));
                if (idx !== -1) {
                  const existingItem = updated[idx];
                  const wasIncomplete = !existingItem.result || existingItem.result.execution_time === 0;
                  const isNowComplete = newItem.result && newItem.result.execution_time !== 0;
                  if (wasIncomplete && isNowComplete) {
                    updated[idx] = newItem;
                  }
                }
              });
              return updated;
            });
          } catch (err) {
            console.error("Fallback history fetch failed", err);
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
                result: { 
                  report: `An error occurred: ${error.message}`,
                  execution_time: 0.1 // Signal completion to UI
                },
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
    savedPrompts,
    setSavedPrompts,
  };
};
