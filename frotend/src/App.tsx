import { useState, useEffect } from "react";
import axios from "axios";
import { Sidebar } from "./components/Sidebar";
import { MainContent } from "./components/MainContent";
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
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => Date.now().toString());
  const [interactions, setInteractions] = useState<
    { id?: number; session_id?: string; query: string; result: any }[]
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

  // Fetch History on Mount
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const response = await axios.get("http://localhost:8000/api/history/");
        setInteractions(response.data);
        
        // Automatically set current session if history exists
        if (response.data.length > 0) {
          const sessions = Array.from(new Set(response.data.map((item: any) => item.session_id || "default")));
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

  const handleQuery = async (query: string) => {
    if (!apiKey) {
      alert("Please enter your API key in Settings first.");
      setIsSettingsOpen(true);
      return;
    }

    // Optimistically add user query to interactions so it renders above loading indicator
    const newInteractionId = Date.now();
    setInteractions((prev) => [
      ...prev,
      { id: newInteractionId, session_id: currentSessionId, query, result: null },
    ]);
    setIsLoading(true);

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
      });

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let accumulatedResponse = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));
                
                // Handle status updates
                if (data.status) {
                  setInteractions((prev) =>
                    prev.map((i) =>
                      i.id === newInteractionId
                        ? { ...i, status: data.status }
                        : i
                    )
                  );
                }

                // Handle final or partial result
                if (data.report || data.done) {
                  setInteractions((prev) =>
                    prev.map((i) =>
                      i.id === newInteractionId ? { ...i, result: data } : i
                    )
                  );
                }
              } catch (e) {
                console.error("Error parsing stream chunk", e);
              }
            }
          }
        }
      }
    } catch (error: any) {
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
  }));

  // If current session doesn't exist yet, show "New Chat..."
  if (!sessions.find((s) => s.id === currentSessionId)) {
    sessions.push({ id: currentSessionId, title: "New Chat..." });
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
        isLoading={isLoading}
        interactions={currentInteractions}
      />

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
