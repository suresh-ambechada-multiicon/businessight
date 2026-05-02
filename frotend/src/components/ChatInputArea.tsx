import { useState, memo } from "react";
import { ArrowUp, Square } from "lucide-react";

interface ChatInputAreaProps {
  onQuery: (query: string) => void;
  onStop: () => void;
  isLoading: boolean;
  isInitial: boolean;
}

export const ChatInputArea = memo(({ onQuery, onStop, isLoading, isInitial }: ChatInputAreaProps) => {
  const [input, setInput] = useState("");

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
      <form onSubmit={handleSubmit} className="query-container">
        <div className="query-input-wrapper">
          <input
            type="text"
            className="query-input"
            placeholder="Ask about your business data..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
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

