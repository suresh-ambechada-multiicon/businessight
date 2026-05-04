import { useEffect, useRef } from "react";

export const useChatScroll = (interactionsLength: number, isLoading: boolean, visibleCount: number) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastInteractionsLength = useRef(interactionsLength);
  const lastVisibleCount = useRef(visibleCount);
  const isFirstLoad = useRef(true);

  useEffect(() => {
    const interactionAdded = interactionsLength > lastInteractionsLength.current;
    const countChanged = visibleCount !== lastVisibleCount.current;

    // Always scroll on first load, or when interaction added, or while loading
    if (isFirstLoad.current || ((interactionAdded || isLoading) && !countChanged)) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
      if (isFirstLoad.current && interactionsLength > 0) {
        isFirstLoad.current = false;
      }
    }

    lastInteractionsLength.current = interactionsLength;
    lastVisibleCount.current = visibleCount;
  }, [interactionsLength, isLoading, visibleCount]);

  return messagesEndRef;
};

