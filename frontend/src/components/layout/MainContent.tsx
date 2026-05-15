import React, { useState, useMemo, useCallback, memo } from "react";
import { ChevronUp } from "lucide-react";
import type { Interaction, SavedPrompt } from "../../types";
import { InteractionItem } from "../chat/InteractionItem";
import { ChatInputArea } from "../chat/ChatInputArea";
import { useChatScroll } from "../../hooks/useChatScroll";

interface MainContentProps {
  onQuery: (query: string, directSql?: string, promptName?: string) => void;
  onStop: () => void;
  isLoading: boolean;
  interactions: Interaction[];
  savedPrompts: SavedPrompt[];
  setSavedPrompts: React.Dispatch<React.SetStateAction<SavedPrompt[]>>;
}

export const MainContent = memo(function MainContent({
  onQuery,
  onStop,
  isLoading,
  interactions,
  savedPrompts,
  setSavedPrompts,
}: MainContentProps) {
  const [chartOverrides, setChartOverrides] = useState<Record<string, string>>({});
  const [visibleCount, setVisibleCount] = useState(30);

  const paginatedInteractions = useMemo(() => {
    return interactions.slice(-visibleCount);
  }, [interactions, visibleCount]);

  const messagesEndRef = useChatScroll(interactions.length, isLoading, visibleCount);

  const isInitial = interactions.length === 0 && !isLoading;

  const handleLoadMore = useCallback(() => {
    setVisibleCount(prev => prev + 50);
  }, []);

  const startIdx = interactions.length - visibleCount;

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
              <div className="load-more-container">
                <button
                  className="load-more-btn load-more-btn-inline"
                  onClick={handleLoadMore}
                >
                  <ChevronUp size={14} />
                  Load previous messages
                </button>
              </div>
            )}
            {paginatedInteractions.map((interaction, mapIdx) => (
              <InteractionItem
                key={interaction.id || `int-${startIdx + mapIdx}`}
                interaction={interaction}
                idx={startIdx + mapIdx}
                chartOverrides={chartOverrides}
                setChartOverrides={setChartOverrides}
                setSavedPrompts={setSavedPrompts}
              />
            ))}
            <div ref={messagesEndRef} />
            <div className="spacer" />
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
});
