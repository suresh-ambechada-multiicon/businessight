export const formatNumber = (num: any) => {
  if (num == null || typeof num !== "number") return num || "";
  if (num >= 1e9) return (num / 1e9).toFixed(1) + "B";
  if (num >= 1e6) return (num / 1e6).toFixed(1) + "M";
  if (num >= 1e4) return (num / 1e3).toFixed(1) + "K";
  return num.toLocaleString();
};

export const formatTime = (seconds: number) => {
  if (typeof seconds !== "number") return seconds;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  if (mins < 60) return `${mins}m ${secs}s`;
  const hrs = Math.floor(mins / 60);
  const remainingMins = mins % 60;
  return `${hrs}h ${remainingMins}m`;
};

export const formatXAxisDate = (tickItem: any) => {
  if (
    typeof tickItem === "string" &&
    tickItem.includes("T") &&
    tickItem.includes("-")
  ) {
    try {
      const date = new Date(tickItem);
      if (!isNaN(date.getTime())) {
        return date.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        });
      }
    } catch (e) {
      // Ignore
    }
  }
  return tickItem;
};
