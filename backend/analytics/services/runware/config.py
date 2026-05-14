RUNWARE_API_URL = "https://api.runware.ai/v1"

DEFAULT_ANALYTICS_MAX_TOKENS = 16384
DEFAULT_REPORT_MAX_TOKENS = 4096

ANALYTICS_THINKING_LEVEL = "high"
REPORT_THINKING_LEVEL = "medium"

REQUEST_TIMEOUT_SECONDS = 180
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2

# None = omit thinkingLevel entirely. Useful fallback for Gemini no-content errors.
THINKING_FALLBACK_ORDER = ["medium", "low", None]
