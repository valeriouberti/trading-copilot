"""Test suite for the sentiment module."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from modules.sentiment import (
    SentimentResult,
    analyze_sentiment,
    _analyze_with_groq,
    _build_prompt,
)


SAMPLE_ASSETS = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]


def _make_groq_response(content: str) -> MagicMock:
    """Create a mock Groq response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


class TestValidGroqResponse:
    def test_valid_response_parsed(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verify that a valid Groq response is parsed correctly."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(mock_llm_response)
        )

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert result.sentiment_score == 1.0
        assert result.sentiment_label == "moderately bullish"
        assert result.source in ("groq", "groq-2pass")

    def test_response_has_all_keys(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verify that the output contains all required keys."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(mock_llm_response)
        )

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        result_dict = result.to_dict()
        required_keys = {"sentiment_score", "sentiment_label", "key_drivers", "directional_bias", "risk_events", "confidence"}
        assert required_keys.issubset(result_dict.keys())


class TestSentimentScoreRange:
    def test_score_within_range(self, mock_news_items: list) -> None:
        """Verify that the sentiment score is between -3 and +3."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 2.5, "sentiment_label": "bullish", "key_drivers": ["a", "b", "c"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 80})
        )

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert -3 <= result.sentiment_score <= 3

    def test_out_of_range_score_accepted_as_float(self, mock_news_items: list) -> None:
        """Verify that an out-of-range score is still parsed as float."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 5, "sentiment_label": "test", "key_drivers": ["a", "b", "c"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 80})
        )

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert isinstance(result.sentiment_score, float)


class TestKeyDriversCount:
    def test_exactly_three_drivers(self, mock_news_items: list) -> None:
        """Verify that key_drivers contains exactly 3 elements."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 1, "sentiment_label": "ok", "key_drivers": ["a", "b", "c"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 70})
        )

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert len(result.key_drivers) == 3

    def test_five_drivers_truncated_to_three(self, mock_news_items: list) -> None:
        """Verify that 5 drivers are truncated to 3."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 1, "sentiment_label": "ok", "key_drivers": ["a", "b", "c", "d", "e"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 70})
        )

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert len(result.key_drivers) <= 3


class TestMalformedResponse:
    def test_plain_text_response_raises(self, mock_news_items: list) -> None:
        """Verify that a non-JSON response causes fallback after retries."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            "This is not JSON at all, just plain text analysis."
        )

        from modules.exceptions import LLMResponseInvalid

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            with pytest.raises(LLMResponseInvalid):
                _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

    def test_malformed_json_full_pipeline_fallback(self, mock_news_items: list) -> None:
        """Verify that the full pipeline returns neutral if Groq returns text."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response("not json")

        with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key"}):
            with patch("modules.sentiment.get_groq_client", return_value=mock_client):
                result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "none"
        assert result.directional_bias == "NEUTRAL"


class TestGroqRateLimit:
    def test_retry_on_rate_limit(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verify retry with exponential backoff on rate limit (via tenacity)."""
        from modules.exceptions import LLMRateLimited

        mock_client = MagicMock()
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Error code: 429 rate_limit exceeded")
            return _make_groq_response(json.dumps(mock_llm_response))

        mock_client.chat.completions.create.side_effect = side_effect

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            # Tenacity handles sleep internally — patch it to avoid actual waits
            with patch("tenacity.nap.time.sleep"):
                result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert result.sentiment_score == 1.0
        assert call_count >= 3  # retried at least twice before success


class TestGroqTotalFailure:
    def test_fallback_on_total_groq_failure(self, mock_news_items: list) -> None:
        """Verify that neutral fallback works if Groq fails completely."""
        mock_failing_client = MagicMock()
        mock_failing_client.chat.completions.create.side_effect = Exception("Service down")
        with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key"}):
            with patch("modules.sentiment.get_groq_client", return_value=mock_failing_client):
                result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "none"
        assert result.directional_bias == "NEUTRAL"


class TestNoApiKey:
    def test_no_api_key_returns_neutral(self, mock_news_items: list) -> None:
        """Verify that without any LLM provider the result is neutral."""
        with patch.dict(os.environ, {}, clear=True):
            env = os.environ.copy()
            env.pop("GROQ_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                with patch("modules.sentiment.get_active_provider", return_value="none"):
                    result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "none"
        assert result.directional_bias == "NEUTRAL"


class TestEmptyNews:
    def test_empty_news_returns_neutral(self) -> None:
        """Verify that without news the result is neutral."""
        result = analyze_sentiment([], SAMPLE_ASSETS)
        assert result.sentiment_score == 0.0
        assert result.directional_bias == "NEUTRAL"


class TestBuildPrompt:
    def test_prompt_contains_asset_names(self, mock_news_items: list) -> None:
        """Verify that the prompt contains the asset names."""
        prompt = _build_prompt(mock_news_items, SAMPLE_ASSETS)
        assert "NASDAQ 100 Futures" in prompt

    def test_prompt_contains_news(self, mock_news_items: list) -> None:
        """Verify that the prompt contains the news titles."""
        prompt = _build_prompt(mock_news_items, SAMPLE_ASSETS)
        assert "Tech stocks rally" in prompt

    def test_prompt_requests_json(self, mock_news_items: list) -> None:
        """Verify that the prompt requests JSON output."""
        prompt = _build_prompt(mock_news_items, SAMPLE_ASSETS)
        assert "JSON" in prompt


class TestLLMFallbackReturnsNeutral:
    def test_neutral_fallback_on_no_provider(self) -> None:
        """Verify that when no LLM is available, neutral result is returned."""
        news = [{"title": "Test", "summary": "", "source": "A", "published_at": "now"}]
        with patch("modules.sentiment.get_active_provider", return_value="none"):
            result = analyze_sentiment(news, SAMPLE_ASSETS)
        assert result.source == "none"
        assert result.sentiment_score == 0.0
        assert result.directional_bias == "NEUTRAL"


class TestSentimentResultSerialization:
    def test_to_dict(self) -> None:
        """Verify serialization of SentimentResult."""
        result = SentimentResult(
            sentiment_score=1.5,
            sentiment_label="Bullish",
            key_drivers=["a", "b", "c"],
            directional_bias="BULLISH",
            risk_events=["CPI release"],
            confidence=75.0,
            source="groq",
        )
        d = result.to_dict()
        assert d["sentiment_score"] == 1.5
        assert d["directional_bias"] == "BULLISH"
        assert len(d["key_drivers"]) == 3
        assert "CPI release" in d["risk_events"]

    def test_to_dict_with_error(self) -> None:
        """Verify serialization with error."""
        result = SentimentResult(
            sentiment_score=0.0,
            sentiment_label="Error",
            error="API timeout",
        )
        d = result.to_dict()
        assert d["error"] == "API timeout"


class TestGroqMarkdownCleanup:
    def test_markdown_fenced_json_cleaned(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verify that JSON wrapped in markdown fences is cleaned."""
        mock_client = MagicMock()
        fenced_json = f"```json\n{json.dumps(mock_llm_response)}\n```"
        mock_client.chat.completions.create.return_value = _make_groq_response(fenced_json)

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert result.sentiment_score == 1.0
        assert result.source in ("groq", "groq-2pass")


class TestPerAssetScoring:
    """Test per-asset scoring (v2)."""

    def test_per_asset_scores_populated(self, mock_news_items: list) -> None:
        """Verify that per-asset scores are extracted from JSON."""
        response_data = {
            "sentiment_score": 1.0,
            "sentiment_label": "bullish",
            "key_drivers": ["a", "b", "c"],
            "directional_bias": "BULLISH",
            "risk_events": [],
            "confidence": 70,
            "asset_scores": {"NQ=F": 1.5, "GC=F": -0.8},
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(response_data)
        )
        assets = [
            {"symbol": "NQ=F", "display_name": "NASDAQ 100"},
            {"symbol": "GC=F", "display_name": "Gold"},
        ]

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, assets, "llama-3.3-70b-versatile", "fake-key")

        assert result.asset_scores["NQ=F"] == 1.5
        assert result.asset_scores["GC=F"] == -0.8
        assert result.asset_biases["NQ=F"] == "BULLISH"
        assert result.asset_biases["GC=F"] == "BEARISH"

    def test_asset_scores_fallback_to_global(self, mock_news_items: list) -> None:
        """If an asset has no specific score, use the global one."""
        response_data = {
            "sentiment_score": 1.0,
            "sentiment_label": "bullish",
            "key_drivers": ["a", "b", "c"],
            "directional_bias": "BULLISH",
            "risk_events": [],
            "confidence": 70,
            "asset_scores": {},  # Empty
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(response_data)
        )

        with patch("modules.sentiment.get_groq_client", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        # Falls back to global sentiment_score of 1.0
        assert result.asset_scores["NQ=F"] == 1.0
        assert result.asset_biases["NQ=F"] == "BULLISH"


class TestTemporalTagging:
    """Test temporal recency tagging."""

    def test_news_tagged_with_recency(self, mock_news_items: list) -> None:
        """Verify that news are tagged with recency."""
        from modules.sentiment import _tag_news_with_recency

        tagged = _tag_news_with_recency(mock_news_items)
        assert len(tagged) == len(mock_news_items)
        # First article was 2h ago
        assert "h ago" in tagged[0]["_time_tag"]

    def test_news_without_datetime_gets_no_tag(self) -> None:
        """News without valid datetime receive an empty tag."""
        from modules.sentiment import _tag_news_with_recency

        news = [{"title": "Test", "published_at": "not-a-date", "source": "X"}]
        tagged = _tag_news_with_recency(news)
        assert tagged[0]["_time_tag"] == ""


class TestSentimentResultV2Fields:
    def test_to_dict_includes_v2_fields(self) -> None:
        """Verify that to_dict includes v2 fields."""
        result = SentimentResult(
            sentiment_score=1.0,
            sentiment_label="Bullish",
            asset_scores={"EQQQ.MI": 1.5},
            asset_biases={"EQQQ.MI": "BULLISH"},
            finbert_score=1.2,
            finbert_agreement="AGREE",
        )
        d = result.to_dict()
        assert d["asset_scores"] == {"EQQQ.MI": 1.5}
        assert d["asset_biases"] == {"EQQQ.MI": "BULLISH"}
        assert d["finbert_score"] == 1.2
        assert d["finbert_agreement"] == "AGREE"
