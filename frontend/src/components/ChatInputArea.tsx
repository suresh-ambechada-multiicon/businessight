import { useState, memo, useRef, useEffect } from "react";
import { ArrowUp, Square, Command } from "lucide-react";
import type { SavedPrompt } from "../types";

interface ChatInputAreaProps {
  onQuery: (query: string, directSql?: string, promptName?: string) => void;
  onStop: () => void;
  isLoading: boolean;
  isInitial: boolean;
  savedPrompts: SavedPrompt[];
}

export const ChatInputArea = memo(({ onQuery, onStop, isLoading, isInitial, savedPrompts }: ChatInputAreaProps) => {
  const [input, setInput] = useState("");
  const [showPromptsMenu, setShowPromptsMenu] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Filter prompts based on search after the slash
  const filteredPrompts = savedPrompts.filter(p => 
    input.startsWith("/") ? p.name.toLowerCase().includes(input.slice(1).toLowerCase()) : false
  );

  useEffect(() => {
    if (input.startsWith("/")) {
      setShowPromptsMenu(true);
      setSelectedIndex(0);
    } else {
      setShowPromptsMenu(false);
    }
  }, [input]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showPromptsMenu && filteredPrompts.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex(prev => (prev < filteredPrompts.length - 1 ? prev + 1 : prev));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex(prev => (prev > 0 ? prev - 1 : 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        const selected = filteredPrompts[selectedIndex];
        onQuery(selected.query, selected.sql_command, selected.name);
        setInput("");
        setShowPromptsMenu(false);
      } else if (e.key === "Escape") {
        setShowPromptsMenu(false);
      }
    }
  };

  const handleSelectPrompt = (prompt: SavedPrompt) => {
    onQuery(prompt.query, prompt.sql_command, prompt.name);
    setInput("");
    setShowPromptsMenu(false);
    inputRef.current?.focus();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) {
      onStop();
    } else if (input.trim()) {
      onQuery(input);
      setInput("");
    }
  };

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
            className={`submit-btn ${input.trim() || isLoading ? "active" : ""}`}
            disabled={!input.trim() && !isLoading}
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

