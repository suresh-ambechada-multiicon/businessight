import { useState, memo, useRef, useEffect, useMemo, useCallback } from "react";
import { ArrowUp, Square, Command } from "lucide-react";
import type { SavedPrompt } from "../../types";

interface ChatInputAreaProps {
  onQuery: (query: string, directSql?: string, promptName?: string) => void;
  onStop: () => void;
  isLoading: boolean;
  isInitial: boolean;
  savedPrompts: SavedPrompt[];
}

export const ChatInputArea = memo(function ChatInputArea({ onQuery, onStop, isLoading, isInitial, savedPrompts }: ChatInputAreaProps) {
  const [input, setInput] = useState("");
  const [showPromptsMenu, setShowPromptsMenu] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filteredPrompts = useMemo(() => {
    if (!input.startsWith("/")) return [];
    const search = input.slice(1).toLowerCase();
    return savedPrompts.filter(p => p.name.toLowerCase().includes(search));
  }, [input, savedPrompts]);

  useEffect(() => {
    setShowPromptsMenu(input.startsWith("/") && filteredPrompts.length > 0);
    setSelectedIndex(0);
  }, [input, filteredPrompts.length]);

  const handleSelectPrompt = useCallback((prompt: SavedPrompt) => {
    onQuery(prompt.query, prompt.sql_command, prompt.name);
    setInput("");
    setShowPromptsMenu(false);
    inputRef.current?.focus();
  }, [onQuery]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) {
      onStop();
    } else if (input.trim()) {
      onQuery(input);
      setInput("");
    }
  }, [isLoading, onStop, onQuery, input]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!showPromptsMenu || filteredPrompts.length === 0) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedIndex(prev => Math.min(prev + 1, filteredPrompts.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedIndex(prev => Math.max(prev - 1, 0));
        break;
      case "Enter":
      case "Tab":
        e.preventDefault();
        handleSelectPrompt(filteredPrompts[selectedIndex]);
        break;
      case "Escape":
        setShowPromptsMenu(false);
        break;
    }
  }, [showPromptsMenu, filteredPrompts, selectedIndex, handleSelectPrompt]);

  const isActive = input.trim().length > 0 || isLoading;

  return (
    <div className={`input-area ${isInitial ? "input-area-initial" : "input-area-active"}`}>

      {showPromptsMenu && filteredPrompts.length > 0 && (
        <div className="saved-prompts-menu">
          <div className="saved-prompts-header">
            <Command size={14} /> Saved Prompts
          </div>
          {filteredPrompts.map((p, idx) => (
            <div
              key={p.id}
              className={`saved-prompt-item ${idx === selectedIndex ? "selected" : ""}`}
              onClick={() => handleSelectPrompt(p)}
              onMouseEnter={() => setSelectedIndex(idx)}
            >
              <div className="prompt-name">{p.name}</div>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="query-container">
        <div className="query-input-wrapper">
          <input
            ref={inputRef}
            type="text"
            className="query-input"
            placeholder="Ask about your business data... (Type '/' for saved prompts)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            type="submit"
            className={`submit-btn ${isActive ? "active" : ""}`}
            disabled={!isActive}
          >
            {isLoading ? (
              <Square size={16} fill="currentColor" />
            ) : (
              <ArrowUp size={20} />
            )}
          </button>
        </div>
      </form>
    </div>
  );
});

