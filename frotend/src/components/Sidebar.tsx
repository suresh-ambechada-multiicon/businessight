import { Sun, Moon, Database, Settings, PlusCircle, MessageSquare } from "lucide-react";

interface Session {
  id: string;
  title: string;
}

interface SidebarProps {
  theme: "light" | "dark";
  toggleTheme: () => void;
  openSettings: () => void;
  sessions: Session[];
  currentSessionId: string;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
}

export function Sidebar({
  theme,
  toggleTheme,
  openSettings,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewChat,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <Database size={24} />
        <span>BusinessDataSight</span>
      </div>

      <div className="sidebar-content">
        <button className="new-chat-btn" onClick={onNewChat}>
          <PlusCircle size={18} />
          <span>New Chat</span>
        </button>

        <h3 className="sidebar-title">Recent Chats</h3>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {sessions.length === 0 ? (
            <div className="history-item" style={{ cursor: 'default' }}>No chats yet</div>
          ) : (
            sessions.map((session) => (
              <button
                key={session.id}
                className={`history-item ${session.id === currentSessionId ? "active" : ""}`}
                onClick={() => onSelectSession(session.id)}
              >
                <MessageSquare size={16} />
                <span className="history-item-text">{session.title}</span>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="sidebar-footer">
        <button className="action-btn" onClick={toggleTheme}>
          {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          <span>{theme === "light" ? "Dark Mode" : "Light Mode"}</span>
        </button>

        <button className="action-btn" onClick={openSettings}>
          <Settings size={18} />
          <span>Settings</span>
        </button>
      </div>
    </aside>
  );
}
