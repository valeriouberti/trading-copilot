"""Circuit breaker for external API calls.

After ``failure_threshold`` consecutive failures, the circuit opens and
all calls immediately raise ``CircuitOpenError`` for ``recovery_timeout``
seconds, avoiding cascading timeouts.  After the timeout the circuit
moves to half-open: the next call is allowed through.  If it succeeds
the circuit closes; if it fails it reopens.

Thread-safe: uses a ``threading.Lock`` for state transitions.

Usage::

    yfinance_breaker = CircuitBreaker("yfinance", failure_threshold=3, recovery_timeout=300)

    @yfinance_breaker
    def fetch_prices(symbol):
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when the circuit is open and calls are blocked."""

    def __init__(self, name: str, until: float):
        self.name = name
        self.until = until
        remaining = max(0, until - time.monotonic())
        super().__init__(
            f"Circuit '{name}' is OPEN — retry after {remaining:.0f}s"
        )


class CircuitBreaker:
    """Simple circuit breaker with closed/open/half-open states."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 300.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("Circuit '%s' → HALF_OPEN", self.name)
            return self._state

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state != CircuitState.CLOSED:
                logger.info("Circuit '%s' → CLOSED", self.name)
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "Circuit '%s' → OPEN after %d failures (recovery in %ds)",
                        self.name, self._failure_count, self.recovery_timeout,
                    )
                self._state = CircuitState.OPEN

    def __call__(self, fn: Callable) -> Callable:
        """Use as a decorator: ``@circuit_breaker``."""

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            state = self.state
            if state == CircuitState.OPEN:
                raise CircuitOpenError(
                    self.name,
                    self._last_failure_time + self.recovery_timeout,
                )

            try:
                result = fn(*args, **kwargs)
                self.record_success()
                return result
            except CircuitOpenError:
                raise
            except Exception:
                self.record_failure()
                raise

        wrapper.circuit_breaker = self  # type: ignore[attr-defined]
        return wrapper

    def status(self) -> dict[str, Any]:
        """Return current breaker status for the dashboard."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ---------------------------------------------------------------------------
# Pre-configured breakers for each external service
# ---------------------------------------------------------------------------

yfinance_breaker = CircuitBreaker("yfinance", failure_threshold=3, recovery_timeout=300)
twelvedata_breaker = CircuitBreaker("twelvedata", failure_threshold=3, recovery_timeout=300)
groq_breaker = CircuitBreaker("groq", failure_threshold=3, recovery_timeout=300)
polymarket_breaker = CircuitBreaker("polymarket", failure_threshold=3, recovery_timeout=300)
rss_breaker = CircuitBreaker("rss", failure_threshold=5, recovery_timeout=120)
