import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { api } from "../api/api";
import type { AnalyticsAgentOptions, Interaction, Session } from "../types";
import type { AnalyticsQueryPayload } from "../api/api";
import {
  clearInflightStorage,
  drainAnalysisSseStream,
  rememberInflightTask,
} from "./analysisStream";

function isAnalysisIncomplete(i: Interaction): boolean {
  const r = i.result;
  if (r == null) return true;
  const t = r.execution_time;
  if (t === -1 || t === -1.0) return false;
  if (t === undefined || t === null) return true;
  return t === 0 || t === 0.0;
}

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
  const resumeStreamControllersRef = useRef(new Map<string, AbortController>());
  const interactionsRef = useRef<Interaction[]>([]);
  const pollingIntervalRef = useRef<number | null>(null);
  /** Same Celery task_id as handleQuery's live stream — resume effect must not double-connect */
  const activeSubmitTaskIdRef = useRef<string | null>(null);

  const inflightResumeKey = useMemo(() => {
    return interactions
      .filter((i) => String(i.session_id) === String(currentSessionId))
      .filter((i) => Boolean(i.task_id) && isAnalysisIncomplete(i))
      .map((i) => `${i.task_id}:${i.id}`)
      .sort()
      .join("|");
  }, [interactions, currentSessionId]);

  useEffect(() => {
    interactionsRef.current = interactions;
  }, [interactions]);

  useEffect(() => {
    return () => {
      resumeStreamControllersRef.current.forEach((ac) => ac.abort());
      resumeStreamControllersRef.current.clear();
      if (pollingIntervalRef.current !== null) {
        window.clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [currentSessionId]);

  useEffect(() => {
    if (!inflightResumeKey || !currentSessionId) return;
    const pairs = inflightResumeKey.split("|").filter(Boolean);
    const wantedTasks = new Set(
      pairs.map((p) => p.split(":")[0]).filter(Boolean) as string[],
    );

    resumeStreamControllersRef.current.forEach((ac, tid) => {
      if (!wantedTasks.has(tid)) {
        ac.abort();
        resumeStreamControllersRef.current.delete(tid);
      }
    });

    for (const p of pairs) {
      const colon = p.indexOf(":");
      if (colon === -1) continue;
      const taskId = p.slice(0, colon);
      const idStr = p.slice(colon + 1);
      if (!taskId || !idStr) continue;
      if (resumeStreamControllersRef.current.has(taskId)) continue;
      if (activeSubmitTaskIdRef.current === taskId) continue;

      const interactionId = /^\d+$/.test(idStr) ? Number(idStr) : idStr;
      const ac = new AbortController();
      resumeStreamControllersRef.current.set(taskId, ac);

      void drainAnalysisSseStream({
        taskId,
        signal: ac.signal,
        initialActiveId: interactionId,
        sessionIdForHistoryFallback: currentSessionId,
        setInteractions,
        setIsLoading,
      }).finally(() => {
        resumeStreamControllersRef.current.delete(taskId);
      });
    }
  }, [inflightResumeKey, currentSessionId]);

  useEffect(() => {
    localStorage.setItem("currentSessionId", currentSessionId);
  }, [currentSessionId]);

  // Fetch session list and saved prompts on mount
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const [sessionsData, promptsData] = await Promise.all([
          api.fetchSessions(),
          api.fetchSavedPrompts()
        ]);
        const sessionsList = Array.isArray(sessionsData) ? sessionsData : [];
        const promptsList = Array.isArray(promptsData) ? promptsData : [];

        const mapped: Session[] = sessionsList.map((s: any) => ({
          id: String(s.id),
          title: s.title || "New Chat",
          count: s.count || 0,
          last_activity: s.last_activity || "",
        }));
        setSessions(mapped);
        setSavedPrompts(promptsList);

        const persistedSid = localStorage.getItem("currentSessionId");
        const sessionExists = mapped.some((s) => s.id === persistedSid);

        if (persistedSid && sessionExists) {
          setCurrentSessionId(persistedSid);
        } else if (mapped.length > 0) {
          setCurrentSessionId(mapped[0].id);
        }
      } catch (error) {
        console.error("Failed to fetch initial data", error);
      }
    };

    fetchInitialData();
  }, []);

  // Load history for current session (lazy — only when session changes)
  const loadSessionHistory = useCallback(async (sessionId: string) => {
    if (loadedSessionsRef.current.has(sessionId)) return;

    try {
      const data = await api.fetchHistory(sessionId);
      const historyData = Array.isArray(data) ? data : [];
      const mappedData = historyData.map((item: any, idx: number) => ({
        ...item,
        id: item.id || `hist-${idx}-${Date.now()}`,
        session_id: String(item.session_id || "default"),
        task_id: item.task_id ?? null,
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

  // Poll history only when there are incomplete interactions.
  // Prefer SSE resume streams; fall back to polling only when no resume stream exists.
  useEffect(() => {
    if (!currentSessionId) return;

    const hasIncomplete = interactionsRef.current.some(
      (i) =>
        String((i as any).session_id) === String(currentSessionId) &&
        isAnalysisIncomplete(i)
    );

    // If nothing is incomplete, stop any polling
    if (!hasIncomplete) {
      if (pollingIntervalRef.current !== null) {
        window.clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      return;
    }

    // If any SSE stream is active, prefer Redis streaming and do not poll history.
    // This covers both resumed streams and the stream opened immediately after submit.
    if (
      activeSubmitTaskIdRef.current ||
      (resumeStreamControllersRef.current && resumeStreamControllersRef.current.size > 0)
    ) {
      if (pollingIntervalRef.current !== null) {
        window.clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      return;
    }

    if (pollingIntervalRef.current !== null) return;

    // Poll less aggressively; use 10s when falling back to polling.
    pollingIntervalRef.current = window.setInterval(async () => {
      // If a Redis stream started since interval creation, stop polling.
      if (
        activeSubmitTaskIdRef.current ||
        (resumeStreamControllersRef.current && resumeStreamControllersRef.current.size > 0)
      ) {
        if (pollingIntervalRef.current !== null) {
          window.clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
        return;
      }

      // Check again before making request
      const stillHasIncomplete = interactionsRef.current.some(
        (i) =>
          String((i as any).session_id) === String(currentSessionId) &&
          isAnalysisIncomplete(i)
      );

      if (!stillHasIncomplete) {
        if (pollingIntervalRef.current !== null) {
          window.clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
        return;
      }

      try {
        const data = await api.fetchHistory(currentSessionId);
        const historyData = Array.isArray(data) ? data : [];
        const mappedData = historyData.map((item: any, idx: number) => ({
          ...item,
          id: item.id || `hist-${idx}-${Date.now()}`,
          session_id: String(item.session_id || "default"),
          task_id: item.task_id ?? null,
        }));

        setInteractions((prev) => {
          let changed = false;
          const updated = [...prev];

          mappedData.forEach((newItem: any) => {
            const idx = updated.findIndex((i) => i.id === newItem.id);
            if (idx !== -1) {
              const existingItem = updated[idx];
              const wasIncomplete = isAnalysisIncomplete(existingItem);
              const isNowComplete =
                newItem.result != null && !isAnalysisIncomplete(newItem);

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
                  isAnalysisIncomplete(i)
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
    }, 10000);

    return () => {
      if (pollingIntervalRef.current !== null) {
        window.clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [currentSessionId, inflightResumeKey]);

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
          isAnalysisIncomplete(i)
      );
      if (lastIdx === -1) return prev;
      return prev.map((i, idx) =>
        idx === lastIdx
          ? {
            ...i,
            status: "Analysis stopped.",
            result: {
              report: "_Analysis cancelled by user._",
              execution_time: -1,
            },
          }
          : i,
      );
    });
  }, [currentSessionId]);

  const handleQuery = async (
    query: string,
    model: string,
    apiKey: string,
    dbUrl: string,
    directSql: string | undefined,
    promptName: string | undefined,
    agentOptions: AnalyticsAgentOptions,
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
      const payload: AnalyticsQueryPayload = {
        query,
        model,
        api_key: apiKey,
        db_url: dbUrl,
        session_id: currentSessionId,
      };
      if (directSql) {
        payload.direct_sql = directSql;
      }
      const execM = agentOptions.executorModel.trim();
      if (execM) {
        payload.executor_model = execM;
      }

      const response = await api.submitQuery(payload);
      const taskId = response.task_id;
      activeSubmitTaskIdRef.current = taskId;
      rememberInflightTask(taskId, currentSessionId);

      setInteractions((prev) =>
        prev.map((i) =>
          i.id === newInteractionId ? { ...i, task_id: taskId } : i,
        ),
      );

      await drainAnalysisSseStream({
        taskId,
        signal: controller.signal,
        initialActiveId: newInteractionId,
        sessionIdForHistoryFallback: currentSessionId,
        setInteractions,
        setIsLoading,
      });
      // Defer so React can apply final `result` before resume effect may see incomplete+task_id
      setTimeout(() => {
        activeSubmitTaskIdRef.current = null;
      }, 0);
    } catch (error: any) {
      activeSubmitTaskIdRef.current = null;
      if (error.name === "AbortError") {
        clearInflightStorage();
        return;
      }
      console.error("Query failed", error);
      clearInflightStorage();
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
      abortControllerRef.current = null;
      setIsLoading(false);
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
