import { useState, useEffect, useMemo } from "react";
import { Sidebar } from "./components/Sidebar";
import { MainContent } from "./components/MainContent";
import { RightSidebar } from "./components/RightSidebar";
import { SettingsModal } from "./components/SettingsModal";
import { ManagePromptsModal } from "./components/ManagePromptsModal";
import { useAppLogic } from "./hooks/useAppLogic";
import "./App.css";

function App() {
  const [theme, setTheme] = useState<"light" | "dark" | "system">(() => {
    return (
      (localStorage.getItem("theme") as "light" | "dark" | "system") || "light"
    );
  });
  const [effectiveTheme, setEffectiveTheme] = useState<"light" | "dark">(
    "light",
  );
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isManagePromptsOpen, setIsManagePromptsOpen] = useState(false);

  // Settings State
  const [model, setModel] = useState(
    () => localStorage.getItem("model") || "google_genai:gemini-2.5-flash",
  );
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem("apiKey") || "",
  );
  const [dbUrl, setDbUrl] = useState(() => localStorage.getItem("dbUrl") || "");

  const {
    currentSessionId,
    setCurrentSessionId,
    sessions,
    interactions,
    isLoading,
    handleNewChat,
    handleDeleteSession,
    handleStop,
    handleQuery,
    savedPrompts,
    setSavedPrompts,
  } = useAppLogic();

  // Theme effect
  useEffect(() => {
    localStorage.setItem("theme", theme);

    const applyTheme = () => {
      let isDark = theme === "dark";
      if (theme === "system") {
        isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      }
      setEffectiveTheme(isDark ? "dark" : "light");
      document.body.classList.toggle("dark", isDark);
    };

    applyTheme();

    if (theme === "system") {
      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      const handleChange = () => applyTheme();
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }
  }, [theme]);

  // Sync settings to localStorage
  useEffect(() => {
    localStorage.setItem("model", model);
    localStorage.setItem("apiKey", apiKey);
    localStorage.setItem("dbUrl", dbUrl);
  }, [model, apiKey, dbUrl]);

  const toggleTheme = () => {
    setTheme((t) => {
      if (t === "light") return "dark";
      if (t === "dark") return "system";
      return "light";
    });
  };

  // Sessions come from the hook now (loaded from /sessions/ endpoint)
  // Ensure current session always appears in the list
  const displaySessions = useMemo(() => {
    const list = [...sessions];
    if (!list.find((s) => s.id === currentSessionId)) {
      list.unshift({ id: currentSessionId, title: "New Chat..." });
    }
    return list;
  }, [sessions, currentSessionId]);

  const currentInteractions = useMemo(
    () =>
      interactions.filter(
        (i) => (i.session_id || "default") === currentSessionId,
      ),
    [interactions, currentSessionId],
  );

  return (
    <div className="app-container">
      <Sidebar
        theme={theme}
        toggleTheme={toggleTheme}
        openSettings={() => setIsSettingsOpen(true)}
        sessions={displaySessions}
        currentSessionId={currentSessionId}
        onSelectSession={setCurrentSessionId}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        openManagePrompts={() => setIsManagePromptsOpen(true)}
      />

      <MainContent
        onQuery={(q, d, pName) => handleQuery(q, model, apiKey, dbUrl, d, pName)}
        onStop={handleStop}
        isLoading={isLoading}
        interactions={currentInteractions}
        theme={effectiveTheme}
        savedPrompts={savedPrompts}
        setSavedPrompts={setSavedPrompts}
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

      <ManagePromptsModal
        isOpen={isManagePromptsOpen}
        onClose={() => setIsManagePromptsOpen(false)}
        savedPrompts={savedPrompts}
        setSavedPrompts={setSavedPrompts}
      />
    </div>
  );
}

export default App;
