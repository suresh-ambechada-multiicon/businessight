import React, { useState } from "react";
import { X } from "lucide-react";

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

  if (!isOpen) return null;

  const handleSave = () => {
    setModel(tempModel);
    setApiKey(tempApiKey);
    setDbUrl(tempDbUrl);
    onClose();
  };

  const predefinedModels = [
    "openai:gpt-4o",
    "openai:gpt-4o-mini",
    "openai:o3-mini",
    "anthropic:claude-3-7-sonnet-latest",
    "anthropic:claude-3-5-sonnet-latest",
    "anthropic:claude-3-5-haiku-latest",
    "google_genai:gemini-2.5-flash",
    "google_genai:gemini-2.0-flash",
    "google_genai:gemini-1.5-pro",
  ];

  // Determine what the select dropdown should show
  const showCustomInput =
    isCustom || (!predefinedModels.includes(tempModel) && tempModel !== "");
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
            <option value="openai:gpt-4o">OpenAI (GPT-4o)</option>
            <option value="openai:gpt-4o-mini">OpenAI (GPT-4o Mini)</option>
            <option value="openai:o3-mini">OpenAI (o3-mini)</option>
            <option value="anthropic:claude-3-7-sonnet-latest">
              Anthropic (Claude 3.7 Sonnet)
            </option>
            <option value="anthropic:claude-3-5-sonnet-latest">
              Anthropic (Claude 3.5 Sonnet)
            </option>
            <option value="anthropic:claude-3-5-haiku-latest">
              Anthropic (Claude 3.5 Haiku)
            </option>
            <option value="google_genai:gemini-2.5-flash">
              Google (Gemini 2.5 Flash)
            </option>
            <option value="google_genai:gemini-2.0-flash">
              Google (Gemini 2.0 Flash)
            </option>
            <option value="google_genai:gemini-1.5-pro">
              Google (Gemini 1.5 Pro)
            </option>
            <option value="custom">Custom (Enter manually)</option>
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
