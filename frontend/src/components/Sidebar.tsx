import { useState } from "react";
import { ConfirmModal } from "./ConfirmModal";
import {
  Sun,
  Moon,
  Monitor,
  Database,
  Settings,
  PlusCircle,
  Trash2,
  Command,
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
}

export function Sidebar({
  theme,
  toggleTheme,
  openSettings,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  openManagePrompts,
}: SidebarProps) {
  const [deleteSessionId, setDeleteSessionId] = useState<string | null>(null);
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <Database size={24} />
        <span>BusinessDataSight</span>
      </div>

      <div className="sidebar-content">
        <button className="new-chat-btn" onClick={onNewChat} style={{ marginBottom: "8px" }}>
          <PlusCircle size={18} />
          <span>New Chat</span>
        </button>
        <button className="new-chat-btn" onClick={openManagePrompts} style={{ background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border-color)" }}>
          <Command size={18} />
          <span>Saved Prompts</span>
        </button>

        <h3 className="sidebar-title">Recent Chats</h3>
        <div className="chat-list">
          {sessions.length === 0 ? (
            <div className="history-item" style={{ cursor: "default" }}>
              No chats yet
            </div>
          ) : (
            sessions.map((session) => (
              <button
                key={session.id}
                className={`history-item ${session.id === currentSessionId ? "active" : ""}`}
              >
                <span
                  className="history-item-text"
                  onClick={() => onSelectSession(session.id)}
                  style={{
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {session.title}
                </span>
                <Trash2
                  size={14}
                  className="delete-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteSessionId(session.id);
                  }}
                  style={{ opacity: 0.4, transition: "opacity 0.2s" }}
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

        <button className="action-btn" onClick={openSettings}>
          <Settings size={18} />
          <span>Settings</span>
        </button>
      </div>

      <ConfirmModal
        isOpen={!!deleteSessionId}
        title="Delete Chat?"
        message="Are you sure you want to delete this chat? This action cannot be undone."
        onCancel={() => setDeleteSessionId(null)}
        onConfirm={() => {
          if (deleteSessionId) {
            onDeleteSession(deleteSessionId);
            setDeleteSessionId(null);
          }
        }}
      />
    </aside>
  );
}
