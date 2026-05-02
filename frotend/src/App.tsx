import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Sidebar } from "./components/Sidebar";
import { MainContent } from "./components/MainContent";
import { RightSidebar } from "./components/RightSidebar";
import { SettingsModal } from "./components/SettingsModal";
import "./App.css";

function App() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return (localStorage.getItem("theme") as "light" | "dark") || "light";
  });
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // Settings State
  const [model, setModel] = useState(() => {
    return localStorage.getItem("model") || "openai:gpt-4o";
  });
  const [apiKey, setApiKey] = useState(() => {
    return localStorage.getItem("apiKey") || "";
  });
  const [dbUrl, setDbUrl] = useState(() => {
    return localStorage.getItem("dbUrl") || "";
  });

  // App State
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    return localStorage.getItem("currentSessionId") || Date.now().toString();
  });
  const [interactions, setInteractions] = useState<
    { id?: number | string; session_id?: string; query: string; result: any; status?: string }[]
  >([]);
  const [isLoading, setIsLoading] = useState(false);

  // Theme effect
  useEffect(() => {
    localStorage.setItem("theme", theme);
    if (theme === "dark") {
      document.body.classList.add("dark");
    } else {
      document.body.classList.remove("dark");
    }
  }, [theme]);

  // Sync settings to localStorage
  useEffect(() => {
    localStorage.setItem("model", model);
    localStorage.setItem("apiKey", apiKey);
    localStorage.setItem("dbUrl", dbUrl);
  }, [model, apiKey, dbUrl]);

  useEffect(() => {
    localStorage.setItem("currentSessionId", currentSessionId);
  }, [currentSessionId]);

  // Fetch History on Mount
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const response = await axios.get("http://localhost:8000/api/history/");
        // Ensure data is mapped with unique IDs for React keys
        const mappedData = response.data.map((item: any, idx: number) => ({
          ...item,
          id: item.id || `hist-${idx}-${Date.now()}`,
          session_id: String(item.session_id || "default")
        }));
        
        setInteractions(prev => {
          // Merge history into existing state, prioritizing ongoing queries
          const existingIds = new Set(prev.map(i => i.id));
          const newItems = mappedData.filter((i: any) => !existingIds.has(i.id));
          return [...newItems, ...prev].sort((_a, _b) => {
             // Keep simple sort by created_at or fallback to insertion order
             return 0; 
          });
        });
        
        // Handle session persistence
        const persistedSid = localStorage.getItem("currentSessionId");
        const sessionExists = mappedData.some((i: any) => i.session_id === persistedSid);

        if (persistedSid && sessionExists) {
          setCurrentSessionId(persistedSid);
        } else if (mappedData.length > 0) {
          // Default to latest session from history
          const sessions = Array.from(new Set(mappedData.map((i: any) => i.session_id)));
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

  const toggleTheme = () => setTheme((t) => (t === "light" ? "dark" : "light"));

  const handleNewChat = () => {
    setCurrentSessionId(Date.now().toString());
  };

  const abortControllerRef = useRef<AbortController | null>(null);

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    
    // Notify backend to stop
    fetch(`http://localhost:8000/api/cancel/?session_id=${currentSessionId}`, { method: "POST" })
      .catch(err => console.error("Failed to signal backend cancellation", err));

    setIsLoading(false);
    
    setInteractions((prev) => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1];
      if (!last.result) {
        return prev.map((i, idx) => 
          idx === prev.length - 1 
          ? { ...i, status: "Analysis stopped.", result: { report: "_Analysis cancelled by user._" } } 
          : i
        );
      }
      return prev;
    });
  };

  const handleQuery = async (query: string) => {
    if (!apiKey) {
      alert("Please enter your API key in Settings first.");
      setIsSettingsOpen(true);
      return;
    }

    // Optimistically add user query to interactions
    const newInteractionId = Date.now();
    setInteractions((prev) => [
      ...prev,
      { id: newInteractionId, session_id: currentSessionId, query, result: null },
    ]);
    setIsLoading(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch("http://localhost:8000/api/query/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          model,
          api_key: apiKey,
          db_url: dbUrl,
          session_id: currentSessionId,
        }),
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          
          // Keep the last partial line in the buffer
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmedLine = line.trim();
            if (!trimmedLine || !trimmedLine.startsWith("data: ")) continue;

            try {
              const data = JSON.parse(trimmedLine.slice(6));
              
              setInteractions((prev) =>
                prev.map((i) => {
                  if (i.id !== newInteractionId) return i;
                  
                  const updatedInteraction = { ...i };
                  
                  if (data.status) {
                    updatedInteraction.status = data.status;
                  }
                  
                  if (data.report !== undefined || data.done) {
                    // Merge new result data into existing result, but don't overwrite with empty report
                    const prevReport = updatedInteraction.result?.report || "";
                    const newReport = data.report || "";
                    
                    updatedInteraction.result = { 
                      ...(updatedInteraction.result || {}), 
                      ...data,
                      report: (data.done && !newReport) ? prevReport : (newReport || prevReport)
                    };
                  }
                  
                  return updatedInteraction;
                })
              );
            } catch (e) {
              console.error("Error parsing stream chunk", e, trimmedLine);
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('Query aborted');
        return;
      }
      console.error("Query failed", error);
      alert("Failed to analyze data. Please check your API key and try again.");

      setInteractions((prev) =>
        prev.map((i) =>
          i.id === newInteractionId
            ? {
                ...i,
                result: {
                  report: `An error occurred while generating the report.\n\nError: ${error.message}`,
                },
              }
            : i
        ),
      );
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  // Group interactions into unique sessions
  const sessionMap = new Map<string, string>();
  interactions.forEach((item) => {
    const sid = item.session_id || "default";
    if (!sessionMap.has(sid)) {
      sessionMap.set(sid, item.query); // use first query as title
    }
  });

  const sessions = Array.from(sessionMap.entries()).map(([id, title]) => ({
    id,
    title,
  })).reverse(); // Reverse so newest sessions appear at the top

  // If current session doesn't exist yet, show "New Chat..."
  if (!sessions.find((s) => s.id === currentSessionId)) {
    sessions.unshift({ id: currentSessionId, title: "New Chat..." });
  }

  // Filter messages for current view
  const currentInteractions = interactions.filter(
    (i) => (i.session_id || "default") === currentSessionId
  );

  return (
    <div className="app-container">
      <Sidebar
        theme={theme}
        toggleTheme={toggleTheme}
        openSettings={() => setIsSettingsOpen(true)}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={setCurrentSessionId}
        onNewChat={handleNewChat}
      />

      <MainContent
        onQuery={handleQuery}
        onStop={handleStop}
        isLoading={isLoading}
        interactions={currentInteractions}
        theme={theme}
      />

      <RightSidebar interactions={currentInteractions} />

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        model={model}
        setModel={setModel}
        apiKey={apiKey}
        setApiKey={setApiKey}
        dbUrl={dbUrl}
        setDbUrl={setDbUrl}
      />
    </div>
  );
}

export default App;
