import { useState, memo, useCallback } from "react";
import { ConfirmModal } from "../modals/ConfirmModal";
import {
  Sun,
  Moon,
  Monitor,
  Database,
  Settings,
  PlusCircle,
  Trash2,
  Command,
  X,
} from "lucide-react";

interface Session {
  id: string;
  title: string;
}

interface SidebarProps {
  theme: "light" | "dark" | "system";
  toggleTheme: () => void;
  openSettings: () => void;
  sessions: Session[];
  currentSessionId: string;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  openManagePrompts: () => void;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export const Sidebar = memo(function Sidebar({
  theme,
  toggleTheme,
  openSettings,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  openManagePrompts,
  mobileOpen = false,
  onMobileClose,
}: SidebarProps) {
  const [deleteSessionId, setDeleteSessionId] = useState<string | null>(null);

  const closeMobile = useCallback(() => {
    onMobileClose?.();
  }, [onMobileClose]);

  const handleNewChat = useCallback(() => {
    onNewChat();
    closeMobile();
  }, [closeMobile, onNewChat]);

  const handleManagePrompts = useCallback(() => {
    openManagePrompts();
    closeMobile();
  }, [closeMobile, openManagePrompts]);

  const handleSettings = useCallback(() => {
    openSettings();
    closeMobile();
  }, [closeMobile, openSettings]);

  const handleSelectSession = useCallback((id: string) => {
    onSelectSession(id);
    closeMobile();
  }, [closeMobile, onSelectSession]);

  const handleDeleteClick = useCallback((e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setDeleteSessionId(sessionId);
  }, []);

  const handleConfirmDelete = useCallback(() => {
    if (deleteSessionId) {
      onDeleteSession(deleteSessionId);
      setDeleteSessionId(null);
    }
  }, [deleteSessionId, onDeleteSession]);

  const handleCancelDelete = useCallback(() => {
    setDeleteSessionId(null);
  }, []);

  return (
    <>
    {mobileOpen && <button className="sidebar-backdrop" onClick={closeMobile} aria-label="Close navigation" />}
    <aside className={`sidebar ${mobileOpen ? "mobile-open" : ""}`}>
      <div className="sidebar-header">
        <Database size={24} />
        <span>BusinessDataSight</span>
        <button className="mobile-close-btn" onClick={closeMobile} aria-label="Close navigation">
          <X size={18} />
        </button>
      </div>

      <div className="sidebar-content">
        <button className="new-chat-btn" onClick={handleNewChat}>
          <PlusCircle size={18} />
          <span>New Chat</span>
        </button>
        <button className="new-chat-btn new-chat-btn-secondary" onClick={handleManagePrompts}>
          <Command size={18} />
          <span>Saved Prompts</span>
        </button>

        <h3 className="sidebar-title">Recent Chats</h3>
        <div className="chat-list">
          {sessions.length === 0 ? (
            <div className="history-item history-item-empty">
              No chats yet
            </div>
          ) : (
            sessions.map((session) => (
              <button
                key={session.id}
                className={`history-item ${session.id === currentSessionId ? "active" : ""}`}
                onClick={() => handleSelectSession(session.id)}
              >
                <span className="history-item-text history-item-text-full">
                  {session.title}
                </span>
                <Trash2
                  size={14}
                  className="delete-btn"
                  onClick={(e) => handleDeleteClick(e, session.id)}
                />
              </button>
            ))
          )}
        </div>
      </div>

      <div className="sidebar-footer">
        <button className="action-btn" onClick={toggleTheme}>
          {theme === "light" ? (
            <Sun size={18} />
          ) : theme === "dark" ? (
            <Moon size={18} />
          ) : (
            <Monitor size={18} />
          )}
          <span>
            Theme:{" "}
            {theme === "light" ? "Light" : theme === "dark" ? "Dark" : "System"}
          </span>
        </button>

        <button className="action-btn" onClick={handleSettings}>
          <Settings size={18} />
          <span>Settings</span>
        </button>
      </div>

      <ConfirmModal
        isOpen={!!deleteSessionId}
        title="Delete Chat?"
        message="Are you sure you want to delete this chat? This action cannot be undone."
        onCancel={handleCancelDelete}
        onConfirm={handleConfirmDelete}
      />
    </aside>
    </>
  );
});
