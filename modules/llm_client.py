"""Unified LLM client — Groq (primary) with Ollama fallback.

All LLM calls in the app go through `llm_call()`. It tries Groq first
(fast, cloud) and falls back to a local Ollama instance if Groq is
rate-limited or unavailable.

Usage:
    from modules.llm_client import llm_call

    text = llm_call(system_msg="...", user_msg="...", max_tokens=500)
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

from modules.exceptions import LLMRateLimited, LLMUnavailable

logger = logging.getLogger(__name__)

# Default models
GROQ_DEFAULT_MODEL = "qwen/qwen3-32b"
OLLAMA_DEFAULT_MODEL = "qwen2.5:14b"
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434")

# Ollama singleton
_ollama_lock = threading.Lock()
_ollama_client: Any = None

# Regex for stripping Qwen 3 <think> blocks
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_TRUNCATED_RE = re.compile(r"<think>.*", re.DOTALL)


def _strip_think(content: str) -> str:
    """Strip Qwen 3 <think>...</think> reasoning blocks from output.

    Handles both complete and truncated think blocks (when max_tokens
    cuts off the response mid-reasoning).
    """
    if "<think>" not in content:
        return content
    # First try to strip complete <think>...</think> blocks
    stripped = _THINK_RE.sub("", content).strip()
    if stripped:
        return stripped
    # If nothing left, the response was truncated mid-think block.
    # Try removing the incomplete <think> block (everything from <think> onward)
    stripped = _THINK_TRUNCATED_RE.sub("", content).strip()
    return stripped


# ---------------------------------------------------------------------------
# Provider checks
# ---------------------------------------------------------------------------

def _groq_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", ""))


def _ollama_available() -> bool:
    """Check if Ollama is running and has the required model."""
    try:
        import httpx
        r = httpx.get(f"{OLLAMA_API_URL}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        model = os.environ.get("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
        return any(model in m for m in models)
    except Exception:
        return False


def get_active_provider() -> str:
    """Return which LLM provider is currently active."""
    if _groq_available():
        return "groq"
    if _ollama_available():
        return "ollama"
    return "none"


# ---------------------------------------------------------------------------
# Unified LLM call
# ---------------------------------------------------------------------------

def llm_call(
    system_msg: str,
    user_msg: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
    model: str | None = None,
) -> str:
    """Make an LLM call. Tries Groq first, falls back to Ollama.

    Returns:
        Raw text response from the LLM.

    Raises:
        LLMUnavailable: If no provider is available.
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

    raise LLMUnavailable(
        provider="all",
        detail="No LLM available (Groq rate-limited, Ollama not running)",
    )


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------

def _call_groq(
    system_msg: str,
    user_msg: str,
    max_tokens: int,
    temperature: float,
    model: str | None,
) -> str:
    from modules.groq_client import get_groq_client

    api_key = os.environ.get("GROQ_API_KEY", "")
    client = get_groq_client(api_key)
    if client is None:
        raise LLMUnavailable(provider="groq", detail="Client not available")

    groq_model = model or os.environ.get("GROQ_MODEL", GROQ_DEFAULT_MODEL)
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
        return _strip_think(response.choices[0].message.content.strip())
    except Exception as exc:
        exc_str = str(exc).lower()
        if "rate_limit" in exc_str or "429" in exc_str:
            raise LLMRateLimited(provider="groq", detail=str(exc)) from exc
        raise LLMUnavailable(provider="groq", detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def _get_ollama_client() -> Any:
    global _ollama_client
    with _ollama_lock:
        if _ollama_client is not None:
            return _ollama_client
        try:
            from openai import OpenAI
        except ImportError:
            return None
        _ollama_client = OpenAI(
            base_url=f"{OLLAMA_API_URL}/v1",
            api_key="ollama",
        )
        return _ollama_client


def _call_ollama(
    system_msg: str,
    user_msg: str,
    max_tokens: int,
    temperature: float,
    model: str | None,
) -> str:
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


# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

def reset_clients() -> None:
    global _ollama_client
    with _ollama_lock:
        _ollama_client = None
    from modules.groq_client import reset_client
    reset_client()
