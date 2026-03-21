"""Singleton Groq client — reuses HTTP connections across LLM calls.

Avoids creating a new Groq client (and TCP connection) for every
sentiment, polymarket classification, and news summary call.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_client: Any = None
_client_api_key: str = ""


def get_groq_client(api_key: str | None = None) -> Any:
    """Return a shared Groq client instance.

    Creates a new client only if one doesn't exist or the API key changed.
    Thread-safe via lock.
    """
    global _client, _client_api_key

    key = api_key or os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None

    with _lock:
        if _client is not None and _client_api_key == key:
            return _client

        try:
            from groq import Groq
        except ImportError:
            logger.warning("groq library not installed")
            return None

        _client = Groq(api_key=key)
        _client_api_key = key
        logger.debug("Created new Groq client singleton")
        return _client


def reset_client() -> None:
    """Reset the singleton (for testing)."""
    global _client, _client_api_key
    with _lock:
        _client = None
        _client_api_key = ""
