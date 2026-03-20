"""Custom exception hierarchy for the Trading Copilot.

Replaces bare ``except Exception`` with typed exceptions that allow
callers to distinguish transient (retryable) failures from permanent
ones, and to identify which subsystem is at fault.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class TradingCopilotError(Exception):
    """Root exception for all Trading Copilot errors."""


class TransientError(TradingCopilotError):
    """Temporary failure — safe to retry (network blip, rate-limit, etc.)."""


class PermanentError(TradingCopilotError):
    """Non-retryable failure — bad input, missing config, logic bug."""


# ---------------------------------------------------------------------------
# Data-fetch subsystem (yfinance, Twelve Data)
# ---------------------------------------------------------------------------

class DataFetchError(TradingCopilotError):
    """Error fetching market data."""

    def __init__(self, symbol: str, source: str, detail: str = ""):
        self.symbol = symbol
        self.source = source
        super().__init__(f"[{source}] Failed to fetch {symbol}: {detail}")


class DataFetchTransient(DataFetchError, TransientError):
    """Transient data-fetch failure (timeout, rate-limit)."""


class DataFetchPermanent(DataFetchError, PermanentError):
    """Permanent data-fetch failure (bad symbol, no API key)."""


class NoDataAvailable(DataFetchPermanent):
    """No data source could return data for the requested symbol."""


# ---------------------------------------------------------------------------
# External API subsystem (Polymarket, Forex Factory, RSS)
# ---------------------------------------------------------------------------

class ExternalAPIError(TradingCopilotError):
    """Error calling an external API."""

    def __init__(self, service: str, detail: str = ""):
        self.service = service
        super().__init__(f"[{service}] API error: {detail}")


class ExternalAPITransient(ExternalAPIError, TransientError):
    """Transient external API failure."""


class ExternalAPIPermanent(ExternalAPIError, PermanentError):
    """Permanent external API failure."""


# ---------------------------------------------------------------------------
# LLM / Sentiment subsystem (Groq, FinBERT)
# ---------------------------------------------------------------------------

class LLMError(TradingCopilotError):
    """Error in LLM processing."""

    def __init__(self, provider: str, detail: str = ""):
        self.provider = provider
        super().__init__(f"[{provider}] LLM error: {detail}")


class LLMRateLimited(LLMError, TransientError):
    """LLM rate-limited — retry after backoff."""


class LLMResponseInvalid(LLMError, PermanentError):
    """LLM returned unparseable or invalid output."""


class LLMUnavailable(LLMError, TransientError):
    """LLM service is temporarily unavailable."""


# ---------------------------------------------------------------------------
# Notification subsystem (Telegram)
# ---------------------------------------------------------------------------

class NotificationError(TradingCopilotError):
    """Error sending notifications."""

    def __init__(self, channel: str, detail: str = ""):
        self.channel = channel
        super().__init__(f"[{channel}] Notification error: {detail}")


class NotificationTransient(NotificationError, TransientError):
    """Transient notification failure."""


class NotificationPermanent(NotificationError, PermanentError):
    """Permanent notification failure (bad token, chat not found)."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ConfigurationError(PermanentError):
    """Missing or invalid configuration."""


# ---------------------------------------------------------------------------
# Signal / Analysis
# ---------------------------------------------------------------------------

class AnalysisError(TradingCopilotError):
    """Error during the analysis pipeline."""


class SignalDetectionError(TradingCopilotError):
    """Error during signal detection."""
