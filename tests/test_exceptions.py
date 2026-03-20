"""Tests for the custom exception hierarchy and retry module."""

from __future__ import annotations

import pytest

from modules.exceptions import (
    AnalysisError,
    ConfigurationError,
    DataFetchError,
    DataFetchPermanent,
    DataFetchTransient,
    ExternalAPIError,
    ExternalAPITransient,
    LLMError,
    LLMRateLimited,
    LLMResponseInvalid,
    LLMUnavailable,
    NoDataAvailable,
    NotificationError,
    NotificationPermanent,
    NotificationTransient,
    PermanentError,
    TradingCopilotError,
    TransientError,
)


class TestExceptionHierarchy:
    """Verify inheritance chains for exception matching."""

    def test_transient_is_trading_copilot_error(self):
        assert issubclass(TransientError, TradingCopilotError)

    def test_permanent_is_trading_copilot_error(self):
        assert issubclass(PermanentError, TradingCopilotError)

    def test_data_fetch_transient_hierarchy(self):
        exc = DataFetchTransient(symbol="NQ=F", source="yfinance", detail="timeout")
        assert isinstance(exc, DataFetchError)
        assert isinstance(exc, TransientError)
        assert isinstance(exc, TradingCopilotError)

    def test_data_fetch_permanent_hierarchy(self):
        exc = DataFetchPermanent(symbol="BAD", source="yfinance", detail="bad symbol")
        assert isinstance(exc, DataFetchError)
        assert isinstance(exc, PermanentError)

    def test_no_data_available(self):
        exc = NoDataAvailable(symbol="NQ=F", source="all", detail="no sources")
        assert isinstance(exc, DataFetchPermanent)
        assert isinstance(exc, PermanentError)

    def test_llm_rate_limited_is_transient(self):
        exc = LLMRateLimited(provider="groq", detail="429")
        assert isinstance(exc, LLMError)
        assert isinstance(exc, TransientError)

    def test_llm_response_invalid_is_permanent(self):
        exc = LLMResponseInvalid(provider="groq", detail="bad json")
        assert isinstance(exc, LLMError)
        assert isinstance(exc, PermanentError)

    def test_llm_unavailable_is_transient(self):
        exc = LLMUnavailable(provider="groq", detail="500")
        assert isinstance(exc, TransientError)

    def test_external_api_transient(self):
        exc = ExternalAPITransient(service="polymarket", detail="timeout")
        assert isinstance(exc, ExternalAPIError)
        assert isinstance(exc, TransientError)

    def test_notification_permanent(self):
        exc = NotificationPermanent(channel="telegram", detail="bad token")
        assert isinstance(exc, NotificationError)
        assert isinstance(exc, PermanentError)

    def test_notification_transient(self):
        exc = NotificationTransient(channel="telegram", detail="timeout")
        assert isinstance(exc, TransientError)

    def test_configuration_error(self):
        exc = ConfigurationError("missing API key")
        assert isinstance(exc, PermanentError)

    def test_catch_all_transient(self):
        """Catch all transient errors with a single except clause."""
        errors = [
            DataFetchTransient(symbol="X", source="y"),
            LLMRateLimited(provider="groq"),
            LLMUnavailable(provider="groq"),
            ExternalAPITransient(service="polymarket"),
            NotificationTransient(channel="telegram"),
        ]
        for exc in errors:
            try:
                raise exc
            except TransientError:
                pass  # all caught

    def test_data_fetch_error_message(self):
        exc = DataFetchTransient(symbol="NQ=F", source="yfinance", detail="timeout")
        assert "yfinance" in str(exc)
        assert "NQ=F" in str(exc)
        assert exc.symbol == "NQ=F"
        assert exc.source == "yfinance"


class TestRetryDecorator:
    """Test that the retry decorators work correctly."""

    def test_retry_transient_retries_on_transient(self):
        from modules.retry import retry_transient

        call_count = 0

        @retry_transient(max_attempts=3, min_wait=0.01, max_wait=0.02)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TransientError("transient")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 3

    def test_retry_transient_gives_up_after_max(self):
        from modules.retry import retry_transient

        @retry_transient(max_attempts=2, min_wait=0.01, max_wait=0.02)
        def always_fails():
            raise TransientError("always fails")

        with pytest.raises(TransientError, match="always fails"):
            always_fails()

    def test_retry_transient_does_not_retry_permanent(self):
        from modules.retry import retry_transient

        call_count = 0

        @retry_transient(max_attempts=3, min_wait=0.01, max_wait=0.02)
        def permanent_fail():
            nonlocal call_count
            call_count += 1
            raise PermanentError("permanent")

        with pytest.raises(PermanentError):
            permanent_fail()

        assert call_count == 1  # no retries for permanent errors
