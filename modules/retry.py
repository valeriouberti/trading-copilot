"""Retry utilities built on ``tenacity``.

Provides pre-configured retry decorators for common subsystems.
All retryable calls should use one of these decorators instead of
hand-rolling retry loops.
"""

from __future__ import annotations

import logging

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from modules.exceptions import TransientError

logger = logging.getLogger(__name__)


def _log_before_retry(retry_state: RetryCallState) -> None:
    """Log a warning before each retry attempt."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retry %d/%s for %s: %s",
        retry_state.attempt_number,
        retry_state.retry_object.stop.max_attempt_number  # type: ignore[union-attr]
        if hasattr(retry_state.retry_object.stop, "max_attempt_number")
        else "?",
        retry_state.fn.__name__ if retry_state.fn else "?",
        exc,
    )


# ---------------------------------------------------------------------------
# Pre-configured decorators
# ---------------------------------------------------------------------------

def retry_transient(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    multiplier: float = 2.0,
):
    """Retry on any ``TransientError`` with exponential backoff.

    Usage::

        @retry_transient(max_attempts=3)
        def call_api():
            ...
    """
    return retry(
        retry=retry_if_exception_type(TransientError),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
        before_sleep=_log_before_retry,
        reraise=True,
    )


def retry_data_fetch(max_attempts: int = 3):
    """Retry decorator for data-fetch calls (yfinance, Twelve Data)."""
    return retry_transient(max_attempts=max_attempts, min_wait=2.0, max_wait=30.0)


def retry_llm(max_attempts: int = 3):
    """Retry decorator for LLM calls (Groq)."""
    return retry_transient(max_attempts=max_attempts, min_wait=2.0, max_wait=60.0)


def retry_external_api(max_attempts: int = 3):
    """Retry decorator for external APIs (Polymarket, RSS, etc.)."""
    return retry_transient(max_attempts=max_attempts, min_wait=1.0, max_wait=15.0)
