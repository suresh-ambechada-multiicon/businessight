import { useState, useEffect, useMemo, useCallback, memo } from "react";
import { Sidebar } from "./components/layout/Sidebar";
import { MainContent } from "./components/layout/MainContent";
import { SettingsModal } from "./components/modals/SettingsModal";
import { ManagePromptsModal } from "./components/modals/ManagePromptsModal";
import { useAppLogic } from "./hooks/useAppLogic";
import type { AnalyticsAgentOptions } from "./types";
import "./App.css";

function loadAgentOptions(): AnalyticsAgentOptions {
  try {
    return {
      executorModel: localStorage.getItem("executorModel") || "",
    };
  } catch {
    return {
      executorModel: "",
    };
  }
}

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

  const [model, setModel] = useState(
    () => localStorage.getItem("model") || "google_genai:gemini-2.5-flash",
  );
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem("apiKey") || "",
  );
  const [dbUrl, setDbUrl] = useState(() => localStorage.getItem("dbUrl") || "");
  const [agentOptions, setAgentOptions] =
    useState<AnalyticsAgentOptions>(loadAgentOptions);

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

  useEffect(() => {
    localStorage.setItem("model", model);
    localStorage.setItem("apiKey", apiKey);
    localStorage.setItem("dbUrl", dbUrl);
  }, [model, apiKey, dbUrl]);

  useEffect(() => {
    localStorage.setItem("executorModel", agentOptions.executorModel);
  }, [agentOptions]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => {
      if (t === "light") return "dark";
      if (t === "dark") return "system";
      return "light";
    });
  }, []);

  const openSettings = useCallback(() => setIsSettingsOpen(true), []);
  const closeSettings = useCallback(() => setIsSettingsOpen(false), []);
  const openManagePrompts = useCallback(() => setIsManagePromptsOpen(true), []);
  const closeManagePrompts = useCallback(
    () => setIsManagePromptsOpen(false),
    [],
  );

  const displaySessions = useMemo(() => {
    const list = [...sessions];
    if (!list.find((s) => s.id === currentSessionId)) {
      list.unshift({ id: currentSessionId, title: "New Chat..." });
    }
    return list;
  }, [sessions, currentSessionId]);

  const currentInteractions = useMemo(
    () =>
      interactions.filter((i) => (i as any).session_id === currentSessionId),
    [interactions, currentSessionId],
  );

  const handleQueryWrapper = useCallback(
    (q: string, d?: string, pName?: string) =>
      handleQuery(q, model, apiKey, dbUrl, d, pName, agentOptions),
    [handleQuery, model, apiKey, dbUrl, agentOptions],
  );

  return (
    <div className="app-container">
      <Sidebar
        theme={theme}
        toggleTheme={toggleTheme}
        openSettings={openSettings}
        sessions={displaySessions}
        currentSessionId={currentSessionId}
        onSelectSession={setCurrentSessionId}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        openManagePrompts={openManagePrompts}
      />

      <MainContent
        onQuery={handleQueryWrapper}
        onStop={handleStop}
        isLoading={isLoading}
        interactions={currentInteractions}
        theme={effectiveTheme}
        savedPrompts={savedPrompts}
        setSavedPrompts={setSavedPrompts}
      />

      {/*<RightSidebar interactions={currentInteractions} />*/}

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={closeSettings}
        model={model}
        setModel={setModel}
        apiKey={apiKey}
        setApiKey={setApiKey}
        dbUrl={dbUrl}
        setDbUrl={setDbUrl}
        agentOptions={agentOptions}
        setAgentOptions={setAgentOptions}
      />

      <ManagePromptsModal
        isOpen={isManagePromptsOpen}
        onClose={closeManagePrompts}
        savedPrompts={savedPrompts}
        setSavedPrompts={setSavedPrompts}
      />
    </div>
  );
}

export default memo(App);
