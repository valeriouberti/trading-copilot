"""API key authentication middleware.

Supports authentication via:
- ``X-API-Key`` header
- ``api_key`` query parameter

Configuration:
- Set ``TRADING_COPILOT_API_KEY`` env var to enable authentication.
- If the env var is **not** set, authentication is disabled (development mode).
- ``/api/health`` and page routes (``/``, ``/asset/*``, etc.) are exempt.
"""

from __future__ import annotations

import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Paths that never require authentication
_PUBLIC_PATHS: set[str] = {
    "/api/health",
    "/",
    "/trades",
    "/analytics",
    "/signals",
    "/settings",
}

# Prefixes that are always public (dashboard pages, static files)
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/asset/",
)


def _is_public(path: str) -> bool:
    """Return True if *path* does not require authentication."""
    if path in _PUBLIC_PATHS:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests that lack a valid API key.

    The expected key is read from the ``TRADING_COPILOT_API_KEY`` env var at
    construction time.  If the env var is empty or unset the middleware lets
    everything through (development mode).
    """

    def __init__(self, app, api_key: str | None = None) -> None:
        super().__init__(app)
        self.api_key = api_key or os.environ.get("TRADING_COPILOT_API_KEY", "")

    async def dispatch(self, request: Request, call_next):
        # If no API key is configured, skip auth entirely
        if not self.api_key:
            return await call_next(request)

        # Public endpoints are always allowed
        if _is_public(request.url.path):
            return await call_next(request)

        # Check header first, then query param
        provided_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

        if provided_key != self.api_key:
            logger.warning(
                "Unauthorized request to %s from %s",
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
