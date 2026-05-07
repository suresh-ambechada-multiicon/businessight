import React, { useState, useMemo } from "react";
import { ChevronUp } from "lucide-react";
import type { Interaction, SavedPrompt } from "../types";
import { InteractionItem } from "./InteractionItem";
import { ChatInputArea } from "./ChatInputArea";
import { useChatScroll } from "../hooks/useChatScroll";

interface MainContentProps {
  onQuery: (query: string, directSql?: string, promptName?: string) => void;
  onStop: () => void;
  isLoading: boolean;
  interactions: Interaction[];
  theme: "light" | "dark";
  savedPrompts: SavedPrompt[];
  setSavedPrompts: React.Dispatch<React.SetStateAction<SavedPrompt[]>>;
}

export const MainContent: React.FC<MainContentProps> = ({
  onQuery,
  onStop,
  isLoading,
  interactions,
  theme,
  savedPrompts,
  setSavedPrompts,
}) => {
  const [chartOverrides, setChartOverrides] = useState<Record<number, string>>(
    {},
  );
  const [visibleCount, setVisibleCount] = useState(30);

  const paginatedInteractions = useMemo(() => {
    return interactions.slice(-visibleCount);
  }, [interactions, visibleCount]);

  const messagesEndRef = useChatScroll(interactions.length, isLoading, visibleCount);

  const isInitial = interactions.length === 0 && !isLoading;

  return (
    <main className="main-content">
      {isInitial ? (
        <div className="center-layout">
          <h1 className="hero-title">Data analytics</h1>
        </div>
      ) : (
        <div className="chat-container">
          <div className="chat-scroll-area">
            {interactions.length > visibleCount && (
              <div style={{ textAlign: "center", padding: "1rem" }}>
                <button
                  className="load-more-btn"
                  onClick={() => setVisibleCount((prev) => prev + 50)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                  }}
                >
                  <ChevronUp size={14} />
                  Load previous messages
                </button>
              </div>
            )}
            {paginatedInteractions.map((interaction, mapIdx) => {
              // Compute the index within the full interactions array
              const fullIdx = interactions.length - paginatedInteractions.length + mapIdx;
              return (
                <InteractionItem
                  key={interaction.id || `int-${fullIdx}`}
                  interaction={interaction}
                  idx={fullIdx}
                  chartOverrides={chartOverrides}
                  setChartOverrides={setChartOverrides}
                  theme={theme}
                  savedPrompts={savedPrompts}
                  setSavedPrompts={setSavedPrompts}
                />
              );
            })}
            <div ref={messagesEndRef} />
            <div style={{ height: "150px", flexShrink: 0 }} />
          </div>
        </div>
      )}

      <ChatInputArea
        onQuery={onQuery}
        onStop={onStop}
        isLoading={isLoading}
        isInitial={isInitial}
        savedPrompts={savedPrompts}
      />
    </main>
  );
};
