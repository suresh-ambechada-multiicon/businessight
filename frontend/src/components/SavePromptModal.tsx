import React, { useState, useEffect } from "react";
import { X, Save } from "lucide-react";
import { api } from "../api/api";
import type { SavedPrompt } from "../types";

interface SavePromptModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultName: string;
  query: string;
  sqlCommand: string;
  setSavedPrompts?: React.Dispatch<React.SetStateAction<SavedPrompt[]>>;
}

export const SavePromptModal: React.FC<SavePromptModalProps> = ({
  isOpen,
  onClose,
  defaultName,
  query,
  sqlCommand,
  setSavedPrompts,
}) => {
  const [name, setName] = useState(defaultName);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setName(defaultName);
      setError(null);
    }
  }, [isOpen, defaultName]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setIsSaving(true);
    setError(null);

    // Try to extract just the SQL if it has "-- Query X" wrappers
    let cleanSql = sqlCommand;
    const matches = [...sqlCommand.matchAll(/-- Query \d+(?: \([^)]+\))?\s*\n([\s\S]*?)(?=-- Query \d+|$)/g)];
    if (matches.length > 0) {
      // Just save the primary query (usually the first one, or the one doing the main SELECT)
      cleanSql = matches[0][1].trim();
    }

    try {
      const newPrompt = await api.createSavedPrompt({
        name: name.trim(),
        query,
        sql_command: cleanSql,
      });

      if (setSavedPrompts) {
        setSavedPrompts((prev) => [newPrompt, ...prev]);
      }
      onClose();
    } catch (e: any) {
      console.error("Failed to save prompt", e);
      if (e.response?.data?.detail) {
        setError(e.response.data.detail);
      } else {
        setError("Failed to save prompt. Please try again.");
      }
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: "600px", padding: "24px" }}
      >
        <div className="modal-header" style={{ marginBottom: "20px" }}>
          <h2 style={{ fontSize: "1.25rem", fontWeight: 600, display: "flex", alignItems: "center", gap: "8px" }}>
            <Save size={20} /> Save Prompt
          </h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <label style={{ fontSize: "0.9rem", fontWeight: 500, color: "var(--text-secondary)" }}>Prompt Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Daily Revenue Report"
              autoFocus
              style={{
                width: "100%",
                padding: "10px 14px",
                borderRadius: "8px",
                border: "1px solid var(--border-color)",
                background: "var(--bg-secondary)",
                color: "var(--text-primary)",
                fontSize: "0.95rem",
                outline: "none",
              }}
              onFocus={(e) => e.target.style.borderColor = "var(--primary-color)"}
              onBlur={(e) => e.target.style.borderColor = "var(--border-color)"}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <label style={{ fontSize: "0.9rem", fontWeight: 500, color: "var(--text-secondary)" }}>User Query</label>
            <div style={{ 
              padding: "12px 14px", 
              background: "var(--bg-secondary)", 
              borderRadius: "8px", 
              fontSize: "0.95rem",
              color: "var(--text-primary)",
              border: "1px solid var(--border-color)",
              opacity: 0.8
            }}>
              {query}
            </div>
          </div>



          {error && <div style={{ color: "var(--danger-color, #ef4444)", fontSize: "0.9rem", marginTop: "-10px" }}>{error}</div>}
        </div>

        <div className="modal-footer" style={{ display: "flex", justifyContent: "flex-end", gap: "12px", marginTop: "24px" }}>
          <button
            onClick={onClose}
            disabled={isSaving}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              background: "transparent",
              border: "1px solid var(--border-color)",
              color: "var(--text-primary)",
              cursor: "pointer",
              fontWeight: 500
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || !name.trim()}
            style={{ 
              display: "flex", 
              alignItems: "center", 
              gap: "8px",
              padding: "8px 16px",
              borderRadius: "6px",
              background: "var(--primary-color)",
              color: "white",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              opacity: (isSaving || !name.trim()) ? 0.7 : 1
            }}
          >
            <Save size={16} />
            {isSaving ? "Saving..." : "Save Prompt"}
          </button>
        </div>
      </div>
    </div>
  );
};
