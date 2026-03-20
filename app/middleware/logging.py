"""Structured JSON logging middleware with correlation IDs.

Adds a unique ``X-Correlation-ID`` header to each request and includes
it in all log records. Configures the root logger to emit JSON lines
with file rotation (10 MB x 5 files).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Thread-local storage for correlation ID
import contextvars

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-",
)


def get_correlation_id() -> str:
    """Return the current request's correlation ID."""
    return _correlation_id.get()


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": _correlation_id.get(),
        }
        if record.exc_info and record.exc_info[1]:
            log_obj["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            log_obj["extra"] = record.extra_data
        return json.dumps(log_obj, default=str)


def configure_logging(
    log_file: str = "logs/trading_copilot.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    level: int = logging.INFO,
) -> None:
    """Configure structured JSON logging with rotation.

    Call this once at app startup (before any log calls).
    """
    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    formatter = JSONFormatter()

    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # Console handler (also JSON for consistency in Docker)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Clear existing handlers to avoid duplicates
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Add a correlation ID to each request."""

    async def dispatch(
        self, request: Request, call_next: Callable,
    ) -> Response:
        # Use incoming header or generate a new one
        corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4())[:8])
        token = _correlation_id.set(corr_id)

        start = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            logging.getLogger("http").info(
                "%s %s %d %.1fms",
                request.method,
                request.url.path,
                response.status_code if "response" in dir() else 500,
                duration_ms,
            )
            _correlation_id.reset(token)

        response.headers["X-Correlation-ID"] = corr_id
        return response
