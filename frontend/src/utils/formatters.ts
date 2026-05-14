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

const DEFAULT_USD_TO_INR = 95.63;

const getUsdToInrRate = () => {
  const rawRate = import.meta.env.VITE_USD_TO_INR;
  const parsed = Number(rawRate);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_USD_TO_INR;
};

export const formatUsdAsInr = (usd: number | undefined | null) => {
  if (typeof usd !== "number" || !Number.isFinite(usd)) return "";
  const inr = usd * getUsdToInrRate();
  const formatter = new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: inr < 1 ? 4 : 2,
    maximumFractionDigits: inr < 1 ? 4 : 2,
  });
  return formatter.format(inr);
};

const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATE_TIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/;

export const formatDateTimeValue = (value: any) => {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toLocaleString("en-IN", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  if (typeof value !== "string") return null;
  const raw = value.trim();
  if (!raw) return null;

  if (DATE_ONLY_PATTERN.test(raw)) {
    const date = new Date(`${raw}T00:00:00`);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleDateString("en-IN", {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  }

  if (!ISO_DATE_TIME_PATTERN.test(raw)) return null;
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("en-IN", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const formatTableCellValue = (value: any, isNumericColumn = false) => {
  if (value == null) {
    return isNumericColumn ? "0" : "—";
  }
  const formattedDate = formatDateTimeValue(value);
  if (formattedDate) return formattedDate;
  if (typeof value === "number") return value.toLocaleString("en-IN");
  return String(value);
};

export const formatXAxisDate = (tickItem: any) => {
  if (
    typeof tickItem === "string" &&
    tickItem.includes("T") &&
    tickItem.includes("-")
  ) {
    try {
      const normalized = tickItem.includes("T") ? tickItem : tickItem.replace(" ", "T");
      const date = new Date(normalized);
      if (!isNaN(date.getTime())) {
        return date.toLocaleDateString("en-IN", {
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
