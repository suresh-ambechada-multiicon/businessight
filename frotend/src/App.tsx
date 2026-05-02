import { useState, useEffect, useMemo } from "react";
import { Sidebar } from "./components/Sidebar";
import { MainContent } from "./components/MainContent";
import { RightSidebar } from "./components/RightSidebar";
import { SettingsModal } from "./components/SettingsModal";
import { useAppLogic } from "./hooks/useAppLogic";
import "./App.css";

function App() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return (localStorage.getItem("theme") as "light" | "dark") || "light";
  });
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // Settings State
  const [model, setModel] = useState(() => localStorage.getItem("model") || "openai:gpt-4o");
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("apiKey") || "");
  const [dbUrl, setDbUrl] = useState(() => localStorage.getItem("dbUrl") || "");

  const {
    currentSessionId,
    setCurrentSessionId,
    interactions,
    isLoading,
    handleNewChat,
    handleDeleteSession,
    handleStop,
    handleQuery
  } = useAppLogic();

  // Theme effect
  useEffect(() => {
    localStorage.setItem("theme", theme);
    document.body.classList.toggle("dark", theme === "dark");
  }, [theme]);

  // Sync settings to localStorage
  useEffect(() => {
    localStorage.setItem("model", model);
    localStorage.setItem("apiKey", apiKey);
    localStorage.setItem("dbUrl", dbUrl);
  }, [model, apiKey, dbUrl]);

  const toggleTheme = () => setTheme((t) => (t === "light" ? "dark" : "light"));

  const sessions = useMemo(() => {
    const sessionMap = new Map<string, string>();
    interactions.forEach((item) => {
      const sid = (item as any).session_id || "default";
      if (!sessionMap.has(sid)) {
        sessionMap.set(sid, item.query);
      }
    });

    const list = Array.from(sessionMap.entries()).map(([id, title]) => ({ id, title })).reverse();
    if (!list.find((s) => s.id === currentSessionId)) {
      list.unshift({ id: currentSessionId, title: "New Chat..." });
    }
    return list;
  }, [interactions, currentSessionId]);

  const currentInteractions = useMemo(() => 
    interactions.filter((i) => ((i as any).session_id || "default") === currentSessionId),
  [interactions, currentSessionId]);

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
        onDeleteSession={handleDeleteSession}
      />

      <MainContent
        onQuery={(q) => handleQuery(q, model, apiKey, dbUrl)}
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
