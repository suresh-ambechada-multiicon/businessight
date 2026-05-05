"""
Structured logging for the analytics pipeline.

Provides a JSON-formatted logger that captures request context
(session_id, client_ip, model, request_id) alongside every log event.

Usage:
    from analytics.services.logger import get_logger, RequestContext

    logger = get_logger("tools")
    ctx = RequestContext(session_id="abc", client_ip="1.2.3.4")

    logger.info("SQL executed", extra={"data": {
        **ctx.to_dict(),
        "query": "SELECT ...",
        "rows": 200,
        "time_ms": 3.2,
    }})
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestContext:
    """Immutable context that flows through the entire request pipeline."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    client_ip: str = ""
    model: str = ""
    query: str = ""
    db_uri_hash: str = ""  # Hashed for security — never log raw URI
    task_id: str = ""      # Celery task ID — used for status channel
    start_time: float = field(default_factory=time.time)

    def elapsed_ms(self) -> float:
        """Milliseconds since request start."""
        return round((time.time() - self.start_time) * 1000, 2)

    def to_dict(self) -> dict:
        """Core fields for log injection. Excludes start_time and raw query."""
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "client_ip": self.client_ip,
            "model": self.model,
            "db_uri_hash": self.db_uri_hash,
        }


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for file output."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge structured data from extra={"data": {...}}
        if hasattr(record, "data") and isinstance(record.data, dict):
            log_entry.update(record.data)

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """
    Readable single-line format for console/terminal output.
    Example: [11:18:17] INFO analytics.tools | SQL executed | req=abc123 rows=200 time_ms=3.2
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        base = f"[{ts}] {record.levelname:<5} {record.name} | {record.getMessage()}"

        # Append structured data as key=value pairs
        if hasattr(record, "data") and isinstance(record.data, dict):
            pairs = " ".join(
                f"{k}={v}" for k, v in record.data.items()
                if k not in ("request_id",) and v  # skip noisy/empty fields
            )
            if pairs:
                base += f" | {pairs}"

        return base


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced analytics logger."""
    return logging.getLogger(f"analytics.{name}")
