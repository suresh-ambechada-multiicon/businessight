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
        className="modal-content modal-content-wide"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header modal-header-spaced">
          <h2 className="modal-title-row">
            <Save size={20} /> Save Prompt
          </h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          <div className="form-field">
            <label className="form-field-label">Prompt Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Daily Revenue Report"
              autoFocus
              className="form-field-input"
            />
          </div>

          <div className="form-field">
            <label className="form-field-label">User Query</label>
            <div className="form-field-value">
              {query}
            </div>
          </div>



          {error && <div className="error-message">{error}</div>}
        </div>

        <div className="modal-footer">
          <button
            onClick={onClose}
            disabled={isSaving}
            className="modal-btn"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || !name.trim()}
            className="modal-btn modal-btn-primary"
          >
            <Save size={16} />
            {isSaving ? "Saving..." : "Save Prompt"}
          </button>
        </div>
      </div>
    </div>
  );
};
