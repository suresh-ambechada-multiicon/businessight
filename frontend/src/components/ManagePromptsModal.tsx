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
        className="modal-content modal-content-wide"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 className="modal-title-row">
            <Command size={18} /> Saved Prompts
          </h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body manage-prompts-body">
          {savedPrompts.length === 0 ? (
            <div className="manage-prompts-empty">
              No saved prompts yet.
            </div>
          ) : (
            <div className="prompts-list">
              {savedPrompts.map(p => (
                <div key={p.id} className="prompt-item">
                  <div className="prompt-item-content">
                    {editingId === p.id ? (
                      <div className="prompt-edit-row">
                        <input
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="prompt-edit-input"
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
                      <div className="prompt-item-name">{p.name}</div>
                    )}

                  </div>
                  <div className="prompt-item-actions">
                    {editingId !== p.id && (
                      <>
                        <button className="icon-btn" onClick={() => handleStartEdit(p)} title="Rename">
                          <Edit2 size={16} />
                        </button>
                        <button className="icon-btn icon-btn-danger" onClick={() => setDeleteId(p.id)} title="Delete">
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
