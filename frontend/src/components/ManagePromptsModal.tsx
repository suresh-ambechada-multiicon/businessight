import React, { useState, useEffect } from "react";
import { X, Edit2, Trash2, Check, Command } from "lucide-react";
import { api } from "../api/api";
import type { SavedPrompt } from "../types";
import { ConfirmModal } from "./ConfirmModal";

interface ManagePromptsModalProps {
  isOpen: boolean;
  onClose: () => void;
  savedPrompts: SavedPrompt[];
  setSavedPrompts: React.Dispatch<React.SetStateAction<SavedPrompt[]>>;
}

export const ManagePromptsModal: React.FC<ManagePromptsModalProps> = ({
  isOpen,
  onClose,
  savedPrompts,
  setSavedPrompts,
}) => {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [deleteId, setDeleteId] = useState<number | null>(null);

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

  const handleStartEdit = (prompt: SavedPrompt) => {
    setEditingId(prompt.id);
    setEditName(prompt.name);
  };

  const handleSaveEdit = async (id: number) => {
    try {
      if (editName.trim()) {
        const updated = await api.renameSavedPrompt(id, editName.trim());
        setSavedPrompts(prev => prev.map(p => p.id === id ? { ...p, name: updated.name } : p));
      }
      setEditingId(null);
    } catch (e) {
      console.error("Failed to rename prompt", e);
    }
  };



  const handleDelete = async (id: number) => {
    try {
      await api.deleteSavedPrompt(id);
      setSavedPrompts(prev => prev.filter(p => p.id !== id));
      setDeleteId(null);
    } catch (e) {
      console.error("Failed to delete prompt", e);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: "600px" }}
      >
        <div className="modal-header">
          <h2><Command size={18} style={{ marginRight: "8px", verticalAlign: "text-bottom" }} /> Saved Prompts</h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body" style={{ maxHeight: "60vh", overflowY: "auto" }}>
          {savedPrompts.length === 0 ? (
            <div style={{ color: "var(--text-tertiary)", textAlign: "center", padding: "2rem" }}>
              No saved prompts yet.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {savedPrompts.map(p => (
                <div key={p.id} style={{ 
                  background: "var(--bg-secondary)", 
                  padding: "12px", 
                  borderRadius: "8px",
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between"
                }}>
                  <div style={{ flex: 1, marginRight: "16px" }}>
                    {editingId === p.id ? (
                      <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
                        <input
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="settings-input"
                          style={{ margin: 0, padding: "4px 8px" }}
                          autoFocus
                          onKeyDown={(e) => e.key === "Enter" && handleSaveEdit(p.id)}
                        />
                        <button className="icon-btn" onClick={() => handleSaveEdit(p.id)} title="Save">
                          <Check size={16} />
                        </button>
                        <button className="icon-btn" onClick={() => setEditingId(null)} title="Cancel">
                          <X size={16} />
                        </button>
                      </div>
                    ) : (
                      <div style={{ fontWeight: 600, marginBottom: "4px" }}>{p.name}</div>
                    )}

                  </div>
                  <div style={{ display: "flex", gap: "8px" }}>
                    {editingId !== p.id && (
                      <>
                        <button className="icon-btn" onClick={() => handleStartEdit(p)} title="Rename">
                          <Edit2 size={16} />
                        </button>
                        <button className="icon-btn" onClick={() => setDeleteId(p.id)} title="Delete" style={{ color: "var(--danger-color, #e53e3e)" }}>
                          <Trash2 size={16} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <ConfirmModal
        isOpen={!!deleteId}
        title="Delete Prompt?"
        message="Are you sure you want to delete this saved prompt? This action cannot be undone."
        onCancel={() => setDeleteId(null)}
        onConfirm={() => {
          if (deleteId) {
            handleDelete(deleteId);
          }
        }}
      />
    </div>
  );
};
