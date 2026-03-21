"""Unified LLM client — Groq → Ollama fallback chain.

Provides a single `llm_call()` function that tries Groq first,
then falls back to a local Ollama instance if Groq is rate-limited
or unavailable. This eliminates rate-limit issues on Groq's free tier.

Usage:
    from modules.llm_client import llm_call, get_llm_client

    # Simple call (auto-selects provider)
    text = llm_call(system_msg="...", user_msg="...", max_tokens=500)

    # Get a client object for direct use
    client = get_llm_client()
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from modules.exceptions import LLMRateLimited, LLMUnavailable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ollama client (OpenAI-compatible via ollama's REST API)
# ---------------------------------------------------------------------------

_ollama_lock = threading.Lock()
_ollama_client: Any = None

# Default Ollama model — Qwen 2.5 14B excels at financial analysis + JSON output
OLLAMA_DEFAULT_MODEL = "qwen2.5:14b"
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434")


def _get_ollama_client() -> Any:
    """Return an OpenAI-compatible client pointing to Ollama."""
    global _ollama_client
    with _ollama_lock:
        if _ollama_client is not None:
            return _ollama_client
        try:
            from openai import OpenAI
        except ImportError:
            logger.debug("openai library not installed — Ollama fallback unavailable")
            return None

        _ollama_client = OpenAI(
            base_url=f"{OLLAMA_API_URL}/v1",
            api_key="ollama",  # Ollama doesn't need a real key
        )
        logger.debug("Created Ollama client → %s", OLLAMA_API_URL)
        return _ollama_client


def _ollama_available() -> bool:
    """Check if Ollama is running and has the required model."""
    try:
        import httpx
        r = httpx.get(f"{OLLAMA_API_URL}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        model = os.environ.get("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
        # Check if model is available (exact or prefix match)
        return any(model in m for m in models)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Groq client (reuses existing singleton)
# ---------------------------------------------------------------------------


def _groq_available() -> bool:
    """Check if Groq API key is configured."""
    return bool(os.environ.get("GROQ_API_KEY", ""))


# ---------------------------------------------------------------------------
# Unified LLM call with fallback
# ---------------------------------------------------------------------------


def get_active_provider() -> str:
    """Return which LLM provider is currently active."""
    if _groq_available():
        return "groq"
    if _ollama_available():
        return "ollama"
    return "none"


def llm_call(
    system_msg: str,
    user_msg: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
    model: str | None = None,
) -> str:
    """Make an LLM call with automatic Groq → Ollama fallback.

    Args:
        system_msg: System prompt.
        user_msg: User prompt.
        max_tokens: Max response tokens.
        temperature: Sampling temperature.
        model: Override model name. If None, uses provider default.

    Returns:
        Raw text response from the LLM.

    Raises:
        LLMUnavailable: If no LLM provider is available.
    """
    # Try Groq first
    if _groq_available():
        try:
            return _call_groq(system_msg, user_msg, max_tokens, temperature, model)
        except LLMRateLimited:
            logger.warning("Groq rate-limited — falling back to Ollama")
        except LLMUnavailable:
            logger.warning("Groq unavailable — falling back to Ollama")

    # Fallback to Ollama
    if _ollama_available():
        return _call_ollama(system_msg, user_msg, max_tokens, temperature, model)

    raise LLMUnavailable(provider="all", detail="No LLM provider available (Groq rate-limited, Ollama not running)")


def _call_groq(
    system_msg: str,
    user_msg: str,
    max_tokens: int,
    temperature: float,
    model: str | None,
) -> str:
    """Call Groq API."""
    from modules.groq_client import get_groq_client

    api_key = os.environ.get("GROQ_API_KEY", "")
    client = get_groq_client(api_key)
    if client is None:
        raise LLMUnavailable(provider="groq", detail="Client not available")

    groq_model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    try:
        response = client.chat.completions.create(
            model=groq_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        exc_str = str(exc).lower()
        if "rate_limit" in exc_str or "429" in exc_str:
            raise LLMRateLimited(provider="groq", detail=str(exc)) from exc
        raise LLMUnavailable(provider="groq", detail=str(exc)) from exc


def _call_ollama(
    system_msg: str,
    user_msg: str,
    max_tokens: int,
    temperature: float,
    model: str | None,
) -> str:
    """Call local Ollama instance via OpenAI-compatible API."""
    client = _get_ollama_client()
    if client is None:
        raise LLMUnavailable(provider="ollama", detail="openai library not installed")

    ollama_model = model or os.environ.get("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
    try:
        response = client.chat.completions.create(
            model=ollama_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        raise LLMUnavailable(provider="ollama", detail=str(exc)) from exc


def reset_clients() -> None:
    """Reset all clients (for testing)."""
    global _ollama_client
    with _ollama_lock:
        _ollama_client = None
    from modules.groq_client import reset_client
    reset_client()
