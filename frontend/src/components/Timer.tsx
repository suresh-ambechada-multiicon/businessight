import { useState, useEffect, memo } from "react";
import { formatTime } from "../utils/formatters";

interface TimerProps {
  className?: string;
}

export const Timer = memo(function Timer({ className }: TimerProps) {
  const [elapsed, setElapsed] = useState(0);
  
  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(
      () => setElapsed((Date.now() - start) / 1000),
      100,
    );
    return () => clearInterval(interval);
  }, []);
  
  return (
    <span className={className}>
      {formatTime(elapsed)}
    </span>
  );
});