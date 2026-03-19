"""Test per il modulo Polymarket."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from modules.polymarket import (
    _classify_category,
    compute_signal,
    fetch_markets,
)
from modules.hallucination_guard import validate_polymarket_consistency


# ---------------------------------------------------------------------------
# Helper: build a fake market dict
# ---------------------------------------------------------------------------

def _make_market(
    question: str = "Test market?",
    prob_yes: float = 50.0,
    volume: float = 100_000,
    slug: str = "test-market",
) -> dict[str, Any]:
    """Costruisce un mercato mock per i test."""
    return {
        "question": question,
        "outcomePrices": f'["{prob_yes / 100:.2f}","{(100 - prob_yes) / 100:.2f}"]',
        "volume": str(volume),
        "slug": slug,
        "endDate": "2026-12-31T00:00:00Z",
    }


def _make_signal_market(
    question: str = "Test market?",
    prob_yes: float = 50.0,
    volume_usd: float = 100_000,
    category: str = "OTHER",
) -> dict[str, Any]:
    """Mercato già elaborato (output di fetch_markets)."""
    return {
        "question": question,
        "prob_yes": prob_yes,
        "prob_no": 100 - prob_yes,
        "volume_usd": volume_usd,
        "end_date": "2026-12-31",
        "url": "https://polymarket.com/event/test",
        "category": category,
    }


# ---------------------------------------------------------------------------
# Tests: fetch_markets
# ---------------------------------------------------------------------------

class TestFetchMarketsFiltersByKeyword:
    def test_returns_only_matching_markets(self) -> None:
        """Solo i mercati con keyword corrispondente devono essere restituiti."""
        raw_markets = [
            _make_market("Will the Fed cut rates?", 60, 200_000, "fed-cut"),
            _make_market("Will it rain in NYC?", 40, 200_000, "rain-nyc"),
            _make_market("Will recession hit in 2026?", 55, 200_000, "recession"),
            _make_market("Will Bitcoin reach 100k?", 30, 200_000, "btc-100k"),
            _make_market("Will Mars be colonized?", 10, 200_000, "mars"),
        ]

        mock_resp = MagicMock()
        mock_resp.json.return_value = raw_markets
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.polymarket.requests.get", return_value=mock_resp):
            result = fetch_markets(["fed", "recession"])

        assert len(result) == 2
        questions = [m["question"] for m in result]
        assert "Will the Fed cut rates?" in questions
        assert "Will recession hit in 2026?" in questions


class TestFetchMarketsFiltersByVolume:
    def test_filters_low_volume_markets(self) -> None:
        """Mercati con volume sotto la soglia devono essere esclusi."""
        raw_markets = [
            _make_market("Will recession happen?", 60, 5_000, "low"),
            _make_market("Will recession strike?", 60, 50_000, "mid"),
            _make_market("Will recession occur?", 60, 200_000, "high"),
        ]

        mock_resp = MagicMock()
        mock_resp.json.return_value = raw_markets
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.polymarket.requests.get", return_value=mock_resp):
            result = fetch_markets(["recession"], min_volume_usd=10_000)

        assert len(result) == 2
        volumes = [m["volume_usd"] for m in result]
        assert 5_000 not in volumes


class TestFetchMarketsNetworkFailure:
    def test_returns_empty_on_connection_error(self) -> None:
        """In caso di errore di rete, deve restituire lista vuota senza eccezioni."""
        with patch("modules.polymarket.requests.get", side_effect=ConnectionError("network down")):
            with patch("modules.polymarket.time.sleep"):  # skip actual sleeps
                result = fetch_markets(["fed"])

        assert result == []


# ---------------------------------------------------------------------------
# Tests: category classification
# ---------------------------------------------------------------------------

class TestCategoryClassification:
    @pytest.mark.parametrize("question,expected", [
        ("Will the Fed raise rates?", "FED"),
        ("Will inflation exceed 3%?", "FED"),
        ("Will FOMC signal hawkish stance?", "FED"),
        ("Will the US enter recession?", "MACRO"),
        ("Will GDP growth slow?", "MACRO"),
        ("Will unemployment rise?", "MACRO"),
        ("Will Russia invade another country?", "GEOPOLITICAL"),
        ("Will new tariffs be imposed?", "GEOPOLITICAL"),
        ("Will China retaliate on trade?", "GEOPOLITICAL"),
        ("Will Bitcoin hit 100k?", "CRYPTO"),
        ("Will ETH surpass 5k?", "CRYPTO"),
        ("Will it rain tomorrow?", "OTHER"),
    ])
    def test_category_per_keyword(self, question: str, expected: str) -> None:
        """Ogni categoria deve essere attivata dalle keyword corrette."""
        assert _classify_category(question) == expected


# ---------------------------------------------------------------------------
# Tests: compute_signal
# ---------------------------------------------------------------------------

class TestComputeSignalBearish:
    def test_bearish_markets_produce_bearish_signal(self) -> None:
        """Mercati con eventi bearish ad alta probabilità danno segnale BEARISH."""
        markets = [
            _make_signal_market("Will recession hit US?", prob_yes=75, volume_usd=300_000),
            _make_signal_market("Will there be a market crash?", prob_yes=70, volume_usd=200_000),
            _make_signal_market("Will war escalate?", prob_yes=80, volume_usd=250_000),
        ]
        result = compute_signal(markets)
        assert result["signal"] == "BEARISH"
        assert result["confidence"] > 60


class TestComputeSignalBullish:
    def test_bullish_markets_produce_bullish_signal(self) -> None:
        """Mercati con eventi bullish ad alta probabilità danno segnale BULLISH."""
        markets = [
            _make_signal_market("Will the Fed announce a rate cut?", prob_yes=80, volume_usd=300_000),
            _make_signal_market("Will economic recovery continue?", prob_yes=75, volume_usd=200_000),
            _make_signal_market("Will expansion continue in Q2?", prob_yes=70, volume_usd=250_000),
        ]
        result = compute_signal(markets)
        assert result["signal"] == "BULLISH"
        assert result["confidence"] > 60


class TestComputeSignalNeutral:
    def test_mixed_markets_produce_neutral_signal(self) -> None:
        """Mercati misti con probabilità ~50% danno segnale NEUTRAL."""
        markets = [
            _make_signal_market("Will recession hit?", prob_yes=50, volume_usd=200_000),
            _make_signal_market("Will rate cut happen?", prob_yes=50, volume_usd=200_000),
            _make_signal_market("Will recovery continue?", prob_yes=50, volume_usd=200_000),
            _make_signal_market("Will market crash?", prob_yes=50, volume_usd=200_000),
        ]
        result = compute_signal(markets)
        assert result["signal"] == "NEUTRAL"


class TestComputeSignalEmptyMarkets:
    def test_empty_list_returns_neutral(self) -> None:
        """Lista vuota deve restituire NEUTRAL senza crash."""
        result = compute_signal([])
        assert result["signal"] == "NEUTRAL"
        assert result["confidence"] == 50.0
        assert result["market_count"] == 0
        assert result["top_markets"] == []


# ---------------------------------------------------------------------------
# Tests: hallucination guard — Polymarket consistency
# ---------------------------------------------------------------------------

class TestTripleConfluenceFlag:
    def test_triple_confluence_detected(self, make_sentiment, make_asset_analysis) -> None:
        """Confluenza tripla quando LLM, tecnici e Polymarket concordano BEARISH."""
        sentiment = make_sentiment(score=-2.0, label="Ribassista", bias="BEARISH")
        assets = [make_asset_analysis(composite_score="BEARISH")]
        poly = {
            "signal": "BEARISH",
            "confidence": 70.0,
            "market_count": 5,
        }

        flags = validate_polymarket_consistency(sentiment, poly, assets)
        assert any("TRIPLE_CONFLUENCE" in f for f in flags)


class TestPolymarketConflictFlag:
    def test_conflict_when_llm_bullish_poly_bearish(self, make_sentiment) -> None:
        """Conflitto quando LLM è BULLISH ma Polymarket è BEARISH con alta confidenza."""
        sentiment = make_sentiment(score=2.0, label="Rialzista", bias="BULLISH")
        poly = {
            "signal": "BEARISH",
            "confidence": 70.0,
            "market_count": 5,
        }

        flags = validate_polymarket_consistency(sentiment, poly)
        assert any("POLYMARKET_CONFLICT" in f for f in flags)

    def test_no_conflict_when_confidence_low(self, make_sentiment) -> None:
        """Nessun conflitto se la confidenza Polymarket è bassa."""
        sentiment = make_sentiment(score=2.0, label="Rialzista", bias="BULLISH")
        poly = {
            "signal": "BEARISH",
            "confidence": 40.0,
            "market_count": 5,
        }

        flags = validate_polymarket_consistency(sentiment, poly)
        assert not any("POLYMARKET_CONFLICT" in f for f in flags)

    def test_no_flags_with_empty_poly(self, make_sentiment) -> None:
        """Nessun flag se dati Polymarket assenti."""
        sentiment = make_sentiment()
        flags = validate_polymarket_consistency(sentiment, None)
        assert flags == []
