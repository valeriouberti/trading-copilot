"""Tests for the circuit breaker module."""

from __future__ import annotations

import time

import pytest

from modules.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # count was reset

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_decorator_success(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        @cb
        def ok():
            return 42

        assert ok() == 42
        assert cb.state == CircuitState.CLOSED

    def test_decorator_failure_and_open(self):
        cb = CircuitBreaker("test", failure_threshold=2)

        @cb
        def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            fail()
        with pytest.raises(ValueError):
            fail()

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            fail()

    def test_decorator_blocks_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)
        cb.record_failure()

        @cb
        def should_not_run():
            raise AssertionError("Should not be called")

        with pytest.raises(CircuitOpenError):
            should_not_run()

    def test_status(self):
        cb = CircuitBreaker("myservice", failure_threshold=3, recovery_timeout=300)
        status = cb.status()
        assert status["name"] == "myservice"
        assert status["state"] == "CLOSED"
        assert status["failure_count"] == 0
        assert status["failure_threshold"] == 3

    def test_circuit_open_error_message(self):
        err = CircuitOpenError("yfinance", time.monotonic() + 60)
        assert "yfinance" in str(err)
        assert "OPEN" in str(err)
