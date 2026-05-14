import React, { useState, useEffect } from "react";
import { X } from "lucide-react";
import { api } from "../../api/api";
import type { AnalyticsAgentOptions } from "../../types";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  model: string;
  setModel: (m: string) => void;
  apiKey: string;
  setApiKey: (k: string) => void;
  dbUrl: string;
  setDbUrl: (u: string) => void;
  agentOptions: AnalyticsAgentOptions;
  setAgentOptions: React.Dispatch<React.SetStateAction<AnalyticsAgentOptions>>;
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
  agentOptions,
  setAgentOptions,
}: SettingsModalProps) {
  const [tempModel, setTempModel] = useState(model);
  const [tempApiKey, setTempApiKey] = useState(apiKey);
  const [tempDbUrl, setTempDbUrl] = useState(dbUrl);
  const [tempAgent, setTempAgent] = useState<AnalyticsAgentOptions>(agentOptions);
  const [isCustom, setIsCustom] = useState(false);
  const [availableModels, setAvailableModels] = useState<
    { id: string; name: string; provider: string }[]
  >([]);
  const [isLoadingModels, setIsLoadingModels] = useState(true);

  // Sync temp state from props whenever modal opens
  useEffect(() => {
    if (isOpen) {
      setTempModel(model);
      setTempApiKey(apiKey);
      setTempDbUrl(dbUrl);
      setTempAgent(agentOptions);
      setIsCustom(false);
    }
  }, [isOpen, model, apiKey, dbUrl, agentOptions]);

  useEffect(() => {
    if (isOpen) {
      api
        .fetchModels()
        .then((data) => {
          setAvailableModels(data);
          setIsLoadingModels(false);
        })
        .catch((err) => {
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
    setAgentOptions(tempAgent);
    onClose();
  };

  const showCustomInput =
    isCustom ||
    (!isLoadingModels &&
      !availableModels.some((m) => m.id === tempModel) &&
      tempModel !== "");
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
          <button type="button" className="icon-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="form-group">
          <label className="form-label">LLM Provider & Model</label>
          <select className="form-input" value={selectValue} onChange={handleModelChange}>
            {isLoadingModels ? (
              <option value="">Loading models...</option>
            ) : (
              <>
                {availableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.provider === "openai"
                      ? "OpenAI"
                      : m.provider === "anthropic"
                        ? "Anthropic"
                        : m.provider === "runware"
                          ? "Runware"
                          : "Google"}{" "}
                    ({m.name})
                  </option>
                ))}
                <option value="custom">Custom (Enter manually)</option>
              </>
            )}
          </select>

          {showCustomInput && (
            <div className="select-custom-option">
              <input
                type="text"
                className="form-input"
                placeholder="e.g. openai:gpt-4"
                value={tempModel}
                onChange={(e) => setTempModel(e.target.value)}
                autoFocus
              />
              <span className="select-hint">
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
          <span className="select-hint">Leave blank to use the backend&apos;s default DB.</span>
        </div>

        <div className="settings-section-divider">
          <h3 className="settings-subheading">Agent &amp; verification</h3>
          <p className="settings-subtext">
            Optional overrides for the analytics pipeline. Blank model fields use the primary model
            above.
          </p>
        </div>


        <div className="form-group">
          <label className="form-label">Executor model (optional)</label>
          <input
            type="text"
            className="form-input"
            placeholder="Same as primary if empty — e.g. openai:gpt-4o"
            value={tempAgent.executorModel}
            onChange={(e) =>
              setTempAgent((a) => ({ ...a, executorModel: e.target.value }))
            }
          />
        </div>


        <button type="button" className="btn-primary" onClick={handleSave}>
          Save Configuration
        </button>
      </div>
    </div>
  );
}
