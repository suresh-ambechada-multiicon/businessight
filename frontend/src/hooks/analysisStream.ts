import type { Dispatch, SetStateAction } from "react";
import { api } from "../api/api";
import type { Interaction } from "../types";

export const INFLIGHT_STORAGE_KEY = "bds_analytics_inflight";

export function clearInflightStorage(): void {
  try {
    sessionStorage.removeItem(INFLIGHT_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function rememberInflightTask(taskId: string, sessionId: string): void {
  try {
    sessionStorage.setItem(
      INFLIGHT_STORAGE_KEY,
      JSON.stringify({ taskId, sessionId }),
    );
  } catch {
    /* ignore */
  }
}

function mapHistoryItem(item: any, idx: number): Interaction {
  return {
    ...item,
    id: item.id ?? `hist-${idx}-${Date.now()}`,
    session_id: String(item.session_id || "default"),
    task_id: item.task_id ?? null,
  };
}

/**
 * Reads SSE from GET /stream/{taskId}/ (Redis stream replay from id 0).
 * Updates the interaction whose id matches activeId (starts as initialActiveId, then query_id).
 */
export async function drainAnalysisSseStream(params: {
  taskId: string;
  signal: AbortSignal;
  initialActiveId: number | string;
  sessionIdForHistoryFallback: string;
  setInteractions: Dispatch<SetStateAction<Interaction[]>>;
  setIsLoading: Dispatch<SetStateAction<boolean>>;
}): Promise<{ receivedResult: boolean; activeId: number | string }> {
  const {
    taskId,
    signal,
    initialActiveId,
    sessionIdForHistoryFallback,
    setInteractions,
    setIsLoading,
  } = params;

  const streamResponse = await api.streamResults(taskId, signal);
  if (!streamResponse.ok) {
    throw new Error(`HTTP error! status: ${streamResponse.status}`);
  }

  const reader = streamResponse.body?.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let activeId: string | number = initialActiveId;
  let receivedResult = false;

  if (!reader) {
    return { receivedResult, activeId };
  }

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

        const prevActiveId = activeId;
        if (eventType === "query_id") {
          activeId = eventData.id;
        }

        setInteractions((prev) =>
          prev.map((i) => {
            const matchId = eventType === "query_id" ? prevActiveId : activeId;
            if (i.id !== matchId) return i;
            const updatedInteraction: Interaction = { ...i };

            if (eventType === "query_id") {
              updatedInteraction.id = eventData.id;
              updatedInteraction.task_id = taskId;
            } else if (eventType === "status") {
              updatedInteraction.status = eventData.message;
            } else if (eventType === "tool") {
              if (eventData.name === "execute_read_only_sql") {
                updatedInteraction.status = "Executing database query...";
              } else {
                updatedInteraction.status = `Tool: ${eventData.name}`;
              }
            } else if (
              eventType === "report" ||
              eventType === "result" ||
              eventType === "delta"
            ) {
              const prevReport = updatedInteraction.result?.report || "";
              const newContent = eventData.report || eventData.content || "";
              const isDelta = eventType === "delta";
              const updatedReport = isDelta
                ? prevReport + newContent
                : newContent || prevReport;

              updatedInteraction.result = {
                ...(updatedInteraction.result || {}),
                ...eventData,
                report: updatedReport,
              };
              if (eventData.agent_trace != null) {
                updatedInteraction.agent_trace = eventData.agent_trace;
                delete (updatedInteraction.result as unknown as Record<string, unknown>)
                  .agent_trace;
              }
            } else if (eventType === "error") {
              const errorMsg =
                eventData.error || eventData.message || "Unknown error";
              updatedInteraction.status = `Error: ${errorMsg}`;
              setIsLoading(false);
              if (!updatedInteraction.result) {
                updatedInteraction.result = { report: errorMsg } as NonNullable<
                  Interaction["result"]
                >;
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

  if (!receivedResult) {
    try {
      const data = await api.fetchHistory(sessionIdForHistoryFallback);
      const mappedData = data.map((item: any, idx: number) =>
        mapHistoryItem(item, idx),
      );

      setInteractions((prev) => {
        const updated = [...prev];
        mappedData.forEach((newItem: Interaction) => {
          const idx = updated.findIndex(
            (i) =>
              i.id === newItem.id ||
              (i.id === activeId &&
                String(newItem.session_id) === String(sessionIdForHistoryFallback)),
          );
          if (idx !== -1) {
            const existingItem = updated[idx];
            const wasIncomplete =
              !existingItem.result || existingItem.result.execution_time === 0;
            const isNowComplete =
              newItem.result && newItem.result.execution_time !== 0;
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

  if (receivedResult) {
    clearInflightStorage();
  }

  return { receivedResult, activeId };
}
