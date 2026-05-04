import React, { useState, useEffect } from "react";
import { X } from "lucide-react";
import { api } from "../api/api";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  model: string;
  setModel: (m: string) => void;
  apiKey: string;
  setApiKey: (k: string) => void;
  dbUrl: string;
  setDbUrl: (u: string) => void;
}

export function SettingsModal({
  isOpen,
  onClose,
  model,
  setModel,
  apiKey,
  setApiKey,
  dbUrl,
  setDbUrl,
}: SettingsModalProps) {
  const [tempModel, setTempModel] = useState(model);
  const [tempApiKey, setTempApiKey] = useState(apiKey);
  const [tempDbUrl, setTempDbUrl] = useState(dbUrl);
  const [isCustom, setIsCustom] = useState(false);
  const [availableModels, setAvailableModels] = useState<{ id: string, name: string, provider: string }[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(true);

  useEffect(() => {
    if (isOpen) {
      api.fetchModels().then(data => {
        setAvailableModels(data);
        setIsLoadingModels(false);
      }).catch(err => {
        console.error("Failed to load models:", err);
        setIsLoadingModels(false);
      });
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSave = () => {
    setModel(tempModel);
    setApiKey(tempApiKey);
    setDbUrl(tempDbUrl);
    onClose();
  };

  const showCustomInput = isCustom || (!isLoadingModels && !availableModels.some(m => m.id === tempModel) && tempModel !== "");
  const selectValue = showCustomInput ? "custom" : tempModel;

  const handleModelChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    if (val === "custom") {
      setIsCustom(true);
      setTempModel("");
    } else {
      setIsCustom(false);
      setTempModel(val);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <div className="modal-header">
          <h2 className="modal-title">Settings</h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="form-group">
          <label className="form-label">LLM Provider & Model</label>
          <select
            className="form-input"
            value={selectValue}
            onChange={handleModelChange}
          >
            {isLoadingModels ? (
              <option value="">Loading models...</option>
            ) : (
              <>
                {availableModels.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.provider === 'openai' ? 'OpenAI' : m.provider === 'anthropic' ? 'Anthropic' : 'Google'} ({m.name})
                  </option>
                ))}
                <option value="custom">Custom (Enter manually)</option>
              </>
            )}
          </select>

          {showCustomInput && (
            <div style={{ marginTop: "var(--space-2)" }}>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. openai:gpt-4"
                value={tempModel}
                onChange={(e) => setTempModel(e.target.value)}
                autoFocus
              />
              <span
                style={{
                  fontSize: "0.75rem",
                  color: "var(--text-secondary)",
                  display: "block",
                  marginTop: "var(--space-1)",
                }}
              >
                Format: <code>provider:model-name</code>
              </span>
            </div>
          )}
        </div>

        <div className="form-group">
          <label className="form-label">API Key</label>
          <input
            type="password"
            className="form-input"
            placeholder="Enter your API key"
            value={tempApiKey}
            onChange={(e) => setTempApiKey(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label className="form-label">Analytics Database URL</label>
          <input
            type="text"
            className="form-input"
            placeholder="postgresql://user:pass@host/db"
            value={tempDbUrl}
            onChange={(e) => setTempDbUrl(e.target.value)}
          />
          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
            Leave blank to use the backend's default DB.
          </span>
        </div>

        <button className="btn-primary" onClick={handleSave}>
          {" "}
          Save Configuration
        </button>
      </div>
    </div>
  );
}
