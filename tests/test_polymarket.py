"""Test suite for the Polymarket module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from modules.polymarket import (
    _classify_category,
    _get_tags_for_assets,
    _get_keywords_for_assets,
    _keyword_classify_single,
    _classify_markets_with_keywords,
    classify_markets_with_llm,
    compute_signal,
    fetch_markets,
)
from modules.hallucination_guard import validate_polymarket_consistency


# ---------------------------------------------------------------------------
# Helper: build a fake market dict (raw from API)
# ---------------------------------------------------------------------------

def _make_market(
    question: str = "Test market?",
    prob_yes: float = 50.0,
    volume: float = 100_000,
    slug: str = "test-market",
) -> dict[str, Any]:
    """Build a mock market for tests."""
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
    impact: str = "",
) -> dict[str, Any]:
    """Already-processed market (output of fetch_markets + classify)."""
    return {
        "question": question,
        "prob_yes": prob_yes,
        "prob_no": 100 - prob_yes,
        "volume_usd": volume_usd,
        "end_date": "2026-12-31",
        "url": "https://polymarket.com/event/test",
        "category": category,
        "impact": impact,
    }


# ---------------------------------------------------------------------------
# Tests: fetch_markets (with pagination and tags)
# ---------------------------------------------------------------------------

class TestFetchMarketsFiltersByKeyword:
    def test_returns_only_matching_markets(self) -> None:
        """Only markets with matching keywords should be returned."""
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
        """Markets with volume below threshold should be excluded."""
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


class TestFetchMarketsWithTags:
    def test_passes_tag_parameter_to_api(self) -> None:
        """The tag parameter is passed to the API."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.polymarket.requests.get", return_value=mock_resp) as mock_get:
            fetch_markets(["fed"], tags=["economics"])

        # Check that at least one call included the tag
        calls = mock_get.call_args_list
        assert any(
            call.kwargs.get("params", {}).get("tag") == "economics"
            or (call.args[0] if call.args else None) and call.kwargs.get("params", {}).get("tag") == "economics"
            for call in calls
        )


class TestFetchMarketsPagination:
    def test_fetches_multiple_pages(self) -> None:
        """Should paginate when there are more than MARKETS_PER_PAGE results."""
        page1 = [_make_market(f"Market fed {i}?", 50, 100_000) for i in range(100)]
        page2 = [_make_market(f"Market fed extra {i}?", 50, 100_000) for i in range(50)]

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            offset = kwargs.get("params", {}).get("offset", 0)
            resp.json.return_value = page1 if offset == 0 else page2
            return resp

        with patch("modules.polymarket.requests.get", side_effect=mock_get):
            result = fetch_markets(["fed"], tags=[None])

        # Should have made at least 2 API calls (page 1 + page 2)
        assert call_count >= 2


class TestFetchMarketsDeduplication:
    def test_deduplicates_across_tags(self) -> None:
        """Duplicate markets from different tags are deduplicated."""
        same_market = _make_market("Will the Fed cut rates?", 60, 200_000)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [same_market]
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.polymarket.requests.get", return_value=mock_resp):
            result = fetch_markets(["fed"], tags=["economics", "politics"])

        assert len(result) == 1


class TestFetchMarketsNetworkFailure:
    def test_returns_empty_on_connection_error(self) -> None:
        """On network error, should return empty list."""
        with patch("modules.polymarket.requests.get", side_effect=ConnectionError("network down")):
            with patch("modules.polymarket.time.sleep"):
                result = fetch_markets(["fed"])

        assert result == []


# ---------------------------------------------------------------------------
# Tests: tag and keyword helpers
# ---------------------------------------------------------------------------

class TestGetTagsForAssets:
    def test_returns_tags_for_nasdaq(self) -> None:
        assets = [{"symbol": "NQ=F", "display_name": "NASDAQ 100"}]
        tags = _get_tags_for_assets(assets)
        assert "economics" in tags

    def test_returns_default_for_unknown(self) -> None:
        assets = [{"symbol": "ZZZ", "display_name": "Unknown"}]
        tags = _get_tags_for_assets(assets)
        assert tags == _get_tags_for_assets(assets)  # Should not crash

    def test_deduplicates(self) -> None:
        assets = [
            {"symbol": "NQ=F", "display_name": "NASDAQ"},
            {"symbol": "ES=F", "display_name": "S&P 500"},
        ]
        tags = _get_tags_for_assets(assets)
        assert len(tags) == len(set(tags))


class TestGetKeywordsForAssets:
    def test_returns_keywords_for_nasdaq(self) -> None:
        assets = [{"symbol": "NQ=F", "display_name": "NASDAQ 100"}]
        kw = _get_keywords_for_assets(assets)
        assert "fed" in kw
        assert "recession" in kw

    def test_returns_keywords_for_gold(self) -> None:
        assets = [{"symbol": "GC=F", "display_name": "Gold Futures"}]
        kw = _get_keywords_for_assets(assets)
        assert "gold" in kw
        assert "war" in kw


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
        assert _classify_category(question) == expected


# ---------------------------------------------------------------------------
# Tests: keyword classification (fallback)
# ---------------------------------------------------------------------------

class TestKeywordClassification:
    def test_bearish_keyword(self) -> None:
        assert _keyword_classify_single("Will recession hit US?") == "BEARISH_IF_YES"

    def test_bullish_keyword(self) -> None:
        assert _keyword_classify_single("Will rate cut happen?") == "BULLISH_IF_YES"

    def test_unknown_defaults_to_bearish(self) -> None:
        assert _keyword_classify_single("Will aliens arrive?") == "BEARISH_IF_YES"

    def test_classify_markets_with_keywords_adds_impact(self) -> None:
        markets = [
            _make_signal_market("Will recession hit?", 70, 100_000),
            _make_signal_market("Will rate cut happen?", 60, 100_000),
        ]
        result = _classify_markets_with_keywords(markets)
        assert result[0]["impact"] == "BEARISH_IF_YES"
        assert result[1]["impact"] == "BULLISH_IF_YES"


# ---------------------------------------------------------------------------
# Tests: LLM classification
# ---------------------------------------------------------------------------

class TestLLMClassification:
    def test_falls_back_to_keywords_without_api_key(self) -> None:
        """Without API key, uses keyword fallback."""
        markets = [
            _make_signal_market("Will recession hit?", 70, 100_000),
        ]
        with patch.dict("os.environ", {"GROQ_API_KEY": ""}, clear=False):
            result = classify_markets_with_llm(markets, api_key="")
        assert result[0]["impact"] == "BEARISH_IF_YES"

    def test_empty_markets_returns_empty(self) -> None:
        assert classify_markets_with_llm([]) == []

    def test_llm_success(self) -> None:
        """LLM classification applies impact correctly."""
        markets = [
            _make_signal_market("Will US avoid recession?", 70, 100_000),
            _make_signal_market("Will tariffs increase?", 80, 200_000),
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '[{"index": 1, "impact": "BULLISH_IF_YES"}, {"index": 2, "impact": "BEARISH_IF_YES"}]'

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response

        mock_groq_cls = MagicMock(return_value=mock_client_instance)

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}, clear=False):
            with patch.dict("sys.modules", {"groq": MagicMock(Groq=mock_groq_cls)}):
                # Re-import to pick up patched module
                import importlib
                import modules.polymarket as pm
                importlib.reload(pm)
                result = pm.classify_markets_with_llm(markets, api_key="test-key")

        assert result[0]["impact"] == "BULLISH_IF_YES"
        assert result[1]["impact"] == "BEARISH_IF_YES"

    def test_llm_failure_falls_back(self) -> None:
        """If LLM fails, uses keyword fallback."""
        markets = [
            _make_signal_market("Will recession hit?", 70, 100_000),
        ]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = RuntimeError("LLM down")

        mock_groq_cls = MagicMock(return_value=mock_client_instance)

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}, clear=False):
            with patch.dict("sys.modules", {"groq": MagicMock(Groq=mock_groq_cls)}):
                import importlib
                import modules.polymarket as pm
                importlib.reload(pm)
                result = pm.classify_markets_with_llm(markets, api_key="test-key")

        assert result[0]["impact"] == "BEARISH_IF_YES"


# ---------------------------------------------------------------------------
# Tests: compute_signal (volume-weighted)
# ---------------------------------------------------------------------------

class TestComputeSignalBearish:
    def test_bearish_markets_produce_bearish_signal(self) -> None:
        """High-probability high-volume bearish markets produce BEARISH signal."""
        markets = [
            _make_signal_market("Will recession hit US?", prob_yes=75,
                                volume_usd=300_000, impact="BEARISH_IF_YES"),
            _make_signal_market("Will there be a market crash?", prob_yes=70,
                                volume_usd=200_000, impact="BEARISH_IF_YES"),
            _make_signal_market("Will war escalate?", prob_yes=80,
                                volume_usd=250_000, impact="BEARISH_IF_YES"),
        ]
        result = compute_signal(markets)
        assert result["signal"] == "BEARISH"
        assert result["confidence"] > 60


class TestComputeSignalBullish:
    def test_bullish_markets_produce_bullish_signal(self) -> None:
        """High-probability high-volume bullish markets produce BULLISH signal."""
        markets = [
            _make_signal_market("Will the Fed announce a rate cut?", prob_yes=80,
                                volume_usd=300_000, impact="BULLISH_IF_YES"),
            _make_signal_market("Will economic recovery continue?", prob_yes=75,
                                volume_usd=200_000, impact="BULLISH_IF_YES"),
            _make_signal_market("Will expansion continue in Q2?", prob_yes=70,
                                volume_usd=250_000, impact="BULLISH_IF_YES"),
        ]
        result = compute_signal(markets)
        assert result["signal"] == "BULLISH"
        assert result["confidence"] > 60


class TestComputeSignalNeutral:
    def test_mixed_markets_produce_neutral_signal(self) -> None:
        """Mixed markets with similar probabilities and volumes produce NEUTRAL."""
        markets = [
            _make_signal_market("Will recession hit?", prob_yes=50,
                                volume_usd=200_000, impact="BEARISH_IF_YES"),
            _make_signal_market("Will rate cut happen?", prob_yes=50,
                                volume_usd=200_000, impact="BULLISH_IF_YES"),
        ]
        result = compute_signal(markets)
        assert result["signal"] == "NEUTRAL"


class TestComputeSignalVolumeWeighting:
    def test_high_volume_market_dominates(self) -> None:
        """A market with much higher volume should dominate the signal."""
        markets = [
            _make_signal_market("Will recession hit?", prob_yes=60,
                                volume_usd=10_000, impact="BEARISH_IF_YES"),
            _make_signal_market("Will rate cut happen?", prob_yes=80,
                                volume_usd=1_000_000, impact="BULLISH_IF_YES"),
        ]
        result = compute_signal(markets)
        assert result["signal"] == "BULLISH"


class TestComputeSignalEmptyMarkets:
    def test_empty_list_returns_neutral(self) -> None:
        result = compute_signal([])
        assert result["signal"] == "NEUTRAL"
        assert result["confidence"] == 50.0
        assert result["market_count"] == 0
        assert result["top_markets"] == []


class TestComputeSignalFallbackClassification:
    def test_missing_impact_uses_keyword_fallback(self) -> None:
        """If impact is missing, compute_signal uses inline keyword fallback."""
        markets = [
            _make_signal_market("Will recession hit?", prob_yes=80, volume_usd=200_000),
        ]
        # No impact field set
        del markets[0]["impact"]
        result = compute_signal(markets)
        # Should still produce a signal without crashing
        assert result["signal"] in ("BEARISH", "BULLISH", "NEUTRAL")


# ---------------------------------------------------------------------------
# Tests: hallucination guard — Polymarket consistency
# ---------------------------------------------------------------------------

class TestTripleConfluenceFlag:
    def test_triple_confluence_detected(self, make_sentiment, make_asset_analysis) -> None:
        """Triple confluence when LLM, technicals and Polymarket agree BEARISH."""
        sentiment = make_sentiment(score=-2.0, label="Bearish", bias="BEARISH")
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
        """Conflict when LLM is BULLISH but Polymarket is BEARISH."""
        sentiment = make_sentiment(score=2.0, label="Bullish", bias="BULLISH")
        poly = {
            "signal": "BEARISH",
            "confidence": 70.0,
            "market_count": 5,
        }

        flags = validate_polymarket_consistency(sentiment, poly)
        assert any("POLYMARKET_CONFLICT" in f for f in flags)

    def test_no_conflict_when_confidence_low(self, make_sentiment) -> None:
        """No conflict if Polymarket confidence is low."""
        sentiment = make_sentiment(score=2.0, label="Bullish", bias="BULLISH")
        poly = {
            "signal": "BEARISH",
            "confidence": 40.0,
            "market_count": 5,
        }

        flags = validate_polymarket_consistency(sentiment, poly)
        assert not any("POLYMARKET_CONFLICT" in f for f in flags)

    def test_no_flags_with_empty_poly(self, make_sentiment) -> None:
        """No flags if Polymarket data absent."""
        sentiment = make_sentiment()
        flags = validate_polymarket_consistency(sentiment, None)
        assert flags == []


# ---------------------------------------------------------------------------
# Tests: v2 — temporal decay
# ---------------------------------------------------------------------------

class TestTemporalDecay:
    def test_imminent_market_high_weight(self) -> None:
        """Market expiring today has weight ~1.0."""
        from modules.polymarket import _compute_time_weight
        from datetime import datetime, timedelta, timezone

        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        weight = _compute_time_weight(tomorrow)
        assert weight > 0.9

    def test_distant_market_low_weight(self) -> None:
        """Market expiring in 6 months has low weight."""
        from modules.polymarket import _compute_time_weight
        from datetime import datetime, timedelta, timezone

        far_future = (datetime.now(timezone.utc) + timedelta(days=180)).isoformat()
        weight = _compute_time_weight(far_future)
        assert weight < 0.15

    def test_unknown_end_date_moderate_weight(self) -> None:
        """Unknown end date → weight 0.5."""
        from modules.polymarket import _compute_time_weight

        assert _compute_time_weight("") == 0.5
        assert _compute_time_weight(None) == 0.5

    def test_invalid_date_moderate_weight(self) -> None:
        """Invalid date → weight 0.5."""
        from modules.polymarket import _compute_time_weight

        assert _compute_time_weight("not-a-date") == 0.5


# ---------------------------------------------------------------------------
# Tests: v2 — impact magnitude
# ---------------------------------------------------------------------------

class TestImpactMagnitude:
    def test_keyword_fallback_sets_default_magnitude(self) -> None:
        """Keyword classification sets default magnitude = 3."""
        markets = [_make_signal_market("Will recession hit?", 70, 100_000)]
        _classify_markets_with_keywords(markets)
        assert markets[0]["impact_magnitude"] == 3

    def test_high_magnitude_market_dominates(self) -> None:
        """Market with high magnitude dominates the signal."""
        markets = [
            {**_make_signal_market("Low impact event", prob_yes=80,
                                   volume_usd=200_000, impact="BULLISH_IF_YES"),
             "impact_magnitude": 1},
            {**_make_signal_market("Fed surprise cut", prob_yes=80,
                                   volume_usd=200_000, impact="BEARISH_IF_YES"),
             "impact_magnitude": 5},
        ]
        result = compute_signal(markets)
        # The bearish market (magnitude 5) should dominate
        assert result["signal"] == "BEARISH"


# ---------------------------------------------------------------------------
# Tests: v2 — probability inversion fix (both sides counted)
# ---------------------------------------------------------------------------

class TestProbabilityInversionFix:
    def test_low_prob_bearish_event_is_net_bullish(self) -> None:
        """Recession at 12% prob → mostly bullish signal (88% no recession)."""
        markets = [
            {**_make_signal_market("Will US enter recession?", prob_yes=12,
                                   volume_usd=500_000, impact="BEARISH_IF_YES"),
             "impact_magnitude": 4},
        ]
        result = compute_signal(markets)
        # 12% bearish, 88% bullish → net bullish
        assert result["signal"] == "BULLISH"
        assert result["net_score"] > 0

    def test_high_prob_bearish_event_is_net_bearish(self) -> None:
        """Recession at 80% prob → clearly bearish."""
        markets = [
            {**_make_signal_market("Will US enter recession?", prob_yes=80,
                                   volume_usd=500_000, impact="BEARISH_IF_YES"),
             "impact_magnitude": 4},
        ]
        result = compute_signal(markets)
        assert result["signal"] == "BEARISH"
        assert result["net_score"] < 0

    def test_50_50_market_is_neutral(self) -> None:
        """50/50 market produces no directional signal."""
        markets = [
            {**_make_signal_market("Coin flip event", prob_yes=50,
                                   volume_usd=500_000, impact="BEARISH_IF_YES"),
             "impact_magnitude": 3},
        ]
        result = compute_signal(markets)
        assert result["signal"] == "NEUTRAL"
        assert abs(result["net_score"]) < 1.0


class TestComputeSignalV2OutputKeys:
    def test_output_has_net_score(self) -> None:
        """compute_signal v2 returns net_score."""
        markets = [
            {**_make_signal_market("Test", prob_yes=70,
                                   volume_usd=100_000, impact="BEARISH_IF_YES"),
             "impact_magnitude": 3},
        ]
        result = compute_signal(markets)
        assert "net_score" in result
        assert isinstance(result["net_score"], float)
