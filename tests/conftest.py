"""Fixture condivise e dati mock per la test suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Mock news items
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_news_items() -> list[dict[str, Any]]:
    """5 notizie realistiche: 2 bullish, 2 bearish, 1 neutrale."""
    now = datetime.now(timezone.utc)
    return [
        {
            "title": "Tech stocks rally as NASDAQ hits new record high",
            "summary": "Strong earnings from major tech companies fuel a broad market surge.",
            "source": "Yahoo Finance",
            "published_at": now - timedelta(hours=2),
        },
        {
            "title": "EUR/USD jumps on dollar weakness after dovish Fed comments",
            "summary": "The euro gained ground as investors priced in a rate pause.",
            "source": "Investing.com",
            "published_at": now - timedelta(hours=3),
        },
        {
            "title": "Oil prices crash to three-month low on demand fears",
            "summary": "Crude tumbled amid recession concerns and weaker Chinese data.",
            "source": "Google News",
            "published_at": now - timedelta(hours=4),
        },
        {
            "title": "Stock market sell-off intensifies as panic selling spreads",
            "summary": "Investors dump risk assets amid fear of a global slowdown.",
            "source": "Yahoo Finance",
            "published_at": now - timedelta(hours=5),
        },
        {
            "title": "Markets await central bank decisions this week",
            "summary": "Traders remain cautious ahead of multiple policy meetings.",
            "source": "Google News",
            "published_at": now - timedelta(hours=6),
        },
    ]


# ---------------------------------------------------------------------------
# Mock price / technical data
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_price_data() -> dict[str, Any]:
    """Dati tecnici realistici per NAS100."""
    return {
        "symbol": "NQ=F",
        "display_name": "NASDAQ 100 Futures",
        "price": 21450.75,
        "change_pct": 1.23,
        "signals": {
            "RSI": {"value": 58.3, "label": "BULLISH", "detail": "RSI 58.3 — momentum rialzista"},
            "MACD": {"value": 12.5, "label": "BULLISH", "detail": "MACD crossover rialzista"},
            "VWAP": {"value": 21380.0, "label": "BULLISH", "detail": "Prezzo sopra VWAP (+0.33%)"},
            "ATR": {"value": 45.2, "label": "NEUTRAL", "detail": "ATR 45.2 (0.21%) — volatilita' normale"},
            "EMA_TREND": {"value": 21200.0, "label": "BULLISH", "detail": "EMA20 > EMA50"},
        },
        "composite_score": "BULLISH",
        "confidence_pct": 62.0,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Mock LLM response
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_response() -> dict[str, Any]:
    """Risposta JSON valida simulata da Groq."""
    return {
        "sentiment_score": 1.0,
        "sentiment_label": "moderatamente rialzista",
        "key_drivers": [
            "Fed in pausa sui tassi",
            "Tech earnings sopra attese",
            "Dollaro debole favorisce risk-on",
        ],
        "directional_bias": "BULLISH",
        "risk_events": [],
        "confidence": 71,
    }


# ---------------------------------------------------------------------------
# Mock RSS XML
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_rss_feed_xml() -> str:
    """XML RSS valido con 3 entry per feedparser."""
    now = datetime.now(timezone.utc)
    dates = [
        (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
        (now - timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
        (now - timedelta(hours=5)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
    ]
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Financial News</title>
    <link>https://example.com</link>
    <description>Test feed</description>
    <item>
      <title>S&amp;P 500 closes at record high on strong earnings</title>
      <description>Major indices rallied on upbeat corporate results.</description>
      <pubDate>{dates[0]}</pubDate>
      <source>TestSource</source>
    </item>
    <item>
      <title>Gold prices fall as dollar strengthens</title>
      <description>Precious metals declined amid risk-on sentiment.</description>
      <pubDate>{dates[1]}</pubDate>
      <source>TestSource</source>
    </item>
    <item>
      <title>European markets mixed ahead of ECB meeting</title>
      <description>Investors await policy signals from Frankfurt.</description>
      <pubDate>{dates[2]}</pubDate>
      <source>TestSource</source>
    </item>
  </channel>
</rss>"""


# ---------------------------------------------------------------------------
# Mock AssetAnalysis helper
# ---------------------------------------------------------------------------

@pytest.fixture
def make_asset_analysis():
    """Factory fixture per creare AssetAnalysis mock."""
    from modules.price_data import AssetAnalysis, TechnicalSignal

    def _make(
        symbol: str = "NQ=F",
        display_name: str = "NASDAQ 100 Futures",
        price: float = 21450.0,
        composite_score: str = "BULLISH",
        confidence_pct: float = 62.0,
        error: str | None = None,
    ) -> AssetAnalysis:
        signals = [
            TechnicalSignal("RSI", 58.3, "BULLISH", "RSI 58.3"),
            TechnicalSignal("MACD", 12.5, composite_score, "MACD signal"),
            TechnicalSignal("VWAP", 21380.0, composite_score, "vs VWAP"),
            TechnicalSignal("EMA_TREND", 21200.0, composite_score, "EMA trend"),
        ]
        return AssetAnalysis(
            symbol=symbol,
            display_name=display_name,
            price=price,
            change_pct=1.23,
            signals=signals,
            composite_score=composite_score,
            confidence_pct=confidence_pct,
            error=error,
        )

    return _make


# ---------------------------------------------------------------------------
# Mock SentimentResult helper
# ---------------------------------------------------------------------------

@pytest.fixture
def make_sentiment():
    """Factory fixture per creare SentimentResult mock."""
    from modules.sentiment import SentimentResult

    def _make(
        score: float = 1.0,
        label: str = "Moderatamente Rialzista",
        bias: str = "BULLISH",
        drivers: list[str] | None = None,
        risk_events: list[str] | None = None,
        confidence: float = 71.0,
        source: str = "groq",
    ) -> SentimentResult:
        return SentimentResult(
            sentiment_score=score,
            sentiment_label=label,
            key_drivers=drivers or ["Driver 1", "Driver 2", "Driver 3"],
            directional_bias=bias,
            risk_events=risk_events or [],
            confidence=confidence,
            source=source,
        )

    return _make


# ---------------------------------------------------------------------------
# Mock Polymarket data
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_polymarket_data() -> dict:
    """Dati mock Polymarket per i test."""
    return {
        "signal": "BEARISH",
        "confidence": 67.5,
        "net_score": -27.5,
        "bullish_prob": 31.2,
        "bearish_prob": 58.7,
        "top_markets": [
            {
                "question": "Will the Fed cut rates in May 2025?",
                "prob_yes": 28.0,
                "prob_no": 72.0,
                "volume_usd": 450_000,
                "end_date": "2025-06-01",
                "category": "FED",
                "url": "https://polymarket.com/event/fed-may",
            },
            {
                "question": "Will US enter recession in 2025?",
                "prob_yes": 64.0,
                "prob_no": 36.0,
                "volume_usd": 380_000,
                "end_date": "2025-12-31",
                "category": "MACRO",
                "url": "https://polymarket.com/event/recession",
            },
            {
                "question": "Will inflation exceed 3% in March?",
                "prob_yes": 71.0,
                "prob_no": 29.0,
                "volume_usd": 210_000,
                "end_date": "2025-04-01",
                "category": "MACRO",
                "url": "https://polymarket.com/event/inflation",
            },
        ],
        "total_volume": 1_040_000,
        "market_count": 12,
    }
