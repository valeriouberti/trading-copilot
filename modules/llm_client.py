"""Unified LLM client — Groq with Qwen 3 32B.

Provides a single `llm_call()` function that routes all LLM calls
through Groq's API using Qwen 3 32B for financial analysis.

Usage:
    from modules.llm_client import llm_call

    text = llm_call(system_msg="...", user_msg="...", max_tokens=500)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from modules.exceptions import LLMRateLimited, LLMUnavailable

logger = logging.getLogger(__name__)

# Default model — Qwen 3 32B on Groq: best for financial analysis + JSON output
DEFAULT_MODEL = "qwen/qwen3-32b"


def get_active_provider() -> str:
    """Return which LLM provider is currently active."""
    if bool(os.environ.get("GROQ_API_KEY", "")):
        return "groq"
    return "none"


def llm_call(
    system_msg: str,
    user_msg: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
    model: str | None = None,
) -> str:
    """Make an LLM call via Groq.

    Args:
        system_msg: System prompt.
        user_msg: User prompt.
        max_tokens: Max response tokens.
        temperature: Sampling temperature.
        model: Override model name. If None, uses GROQ_MODEL env or default.

    Returns:
        Raw text response from the LLM.

    Raises:
        LLMRateLimited: If Groq returns 429.
        LLMUnavailable: If Groq is not configured or unavailable.
    """
    from modules.groq_client import get_groq_client

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise LLMUnavailable(provider="groq", detail="GROQ_API_KEY not set")

    client = get_groq_client(api_key)
    if client is None:
        raise LLMUnavailable(provider="groq", detail="Client not available")

    groq_model = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
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
        content = response.choices[0].message.content.strip()
        # Qwen 3 may include <think>...</think> reasoning blocks — strip them
        if "<think>" in content:
            import re
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return content
    except Exception as exc:
        exc_str = str(exc).lower()
        if "rate_limit" in exc_str or "429" in exc_str:
            raise LLMRateLimited(provider="groq", detail=str(exc)) from exc
        raise LLMUnavailable(provider="groq", detail=str(exc)) from exc


def reset_clients() -> None:
    """Reset all clients (for testing)."""
    from modules.groq_client import reset_client
    reset_client()
