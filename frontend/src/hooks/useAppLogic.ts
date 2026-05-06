import { useState, useEffect, useRef } from "react";
import { api } from "../api/api";
import type { Interaction } from "../types";

export const useAppLogic = () => {
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    return localStorage.getItem("currentSessionId") || Date.now().toString();
  });
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Sync session to localStorage
  useEffect(() => {
    localStorage.setItem("currentSessionId", currentSessionId);
  }, [currentSessionId]);

  // Fetch History on Mount
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const data = await api.fetchHistory();
        const mappedData = data.map((item: any, idx: number) => ({
          ...item,
          id: item.id || `hist-${idx}-${Date.now()}`,
          session_id: String(item.session_id || "default"),
        }));

        setInteractions((prev) => {
          const existingIds = new Set(prev.map((i) => i.id));
          const newItems = mappedData.filter(
            (i: any) => !existingIds.has(i.id),
          );
          return [...newItems, ...prev];
        });

        const persistedSid = localStorage.getItem("currentSessionId");
        const sessionExists = mappedData.some(
          (i: any) => i.session_id === persistedSid,
        );

        if (persistedSid && sessionExists) {
          setCurrentSessionId(persistedSid);
        } else if (mappedData.length > 0) {
          const sessions = Array.from(
            new Set(mappedData.map((i: any) => i.session_id)),
          );
          const latestSession = sessions[sessions.length - 1];
          if (latestSession) {
            setCurrentSessionId(latestSession as string);
          }
        }
      } catch (error) {
        console.error("Failed to fetch history", error);
      }
    };
    fetchHistory();
  }, []);

  const handleNewChat = () => {
    setCurrentSessionId(Date.now().toString());
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      setInteractions((prev) =>
        prev.filter((i) => (i as any).session_id !== sessionId),
      );
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
    interactions,
    setInteractions,
    isLoading,
    handleNewChat,
    handleDeleteSession,
    handleStop,
    handleQuery,
  };
};
