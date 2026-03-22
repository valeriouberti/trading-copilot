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


SAMPLE_ASSETS = [{"symbol": "EQQQ.MI", "display_name": "Invesco NASDAQ-100"}]


def _mock_llm_call_for(response_data: dict) -> callable:
    """Create a mock _llm_call that returns reasoning then JSON."""
    call_count = 0

    def mock_call(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 1:
            # Pass 1: reasoning
            return "Bullish outlook due to tech rally and supportive macro environment."
        # Pass 2: JSON extraction
        return json.dumps(response_data)

    return mock_call


class TestValidGroqResponse:
    def test_valid_response_parsed(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verify that a valid LLM response is parsed correctly."""
        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(mock_llm_response)):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        assert result.sentiment_score == 1.0
        assert result.sentiment_label == "moderately bullish"
        assert result.source in ("groq", "groq-2pass")

    def test_response_has_all_keys(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verify that the output contains all required keys."""
        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(mock_llm_response)):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        result_dict = result.to_dict()
        required_keys = {"sentiment_score", "sentiment_label", "key_drivers", "directional_bias", "risk_events", "confidence"}
        assert required_keys.issubset(result_dict.keys())


class TestSentimentScoreRange:
    def test_score_within_range(self, mock_news_items: list) -> None:
        """Verify that the sentiment score is between -3 and +3."""
        data = {"sentiment_score": 2.5, "sentiment_label": "bullish", "key_drivers": ["a", "b", "c"],
                "directional_bias": "BULLISH", "risk_events": [], "confidence": 80}
        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(data)):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        assert -3 <= result.sentiment_score <= 3

    def test_out_of_range_score_accepted_as_float(self, mock_news_items: list) -> None:
        """Verify that an out-of-range score is still parsed as float."""
        data = {"sentiment_score": 5, "sentiment_label": "test", "key_drivers": ["a", "b", "c"],
                "directional_bias": "BULLISH", "risk_events": [], "confidence": 80}
        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(data)):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        assert isinstance(result.sentiment_score, float)


class TestKeyDriversCount:
    def test_exactly_three_drivers(self, mock_news_items: list) -> None:
        """Verify that key_drivers contains exactly 3 elements."""
        data = {"sentiment_score": 1, "sentiment_label": "ok", "key_drivers": ["a", "b", "c"],
                "directional_bias": "BULLISH", "risk_events": [], "confidence": 70}
        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(data)):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        assert len(result.key_drivers) == 3

    def test_five_drivers_truncated_to_three(self, mock_news_items: list) -> None:
        """Verify that 5 drivers are truncated to 3."""
        data = {"sentiment_score": 1, "sentiment_label": "ok", "key_drivers": ["a", "b", "c", "d", "e"],
                "directional_bias": "BULLISH", "risk_events": [], "confidence": 70}
        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(data)):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        assert len(result.key_drivers) <= 3


class TestMalformedResponse:
    def test_plain_text_response_raises(self, mock_news_items: list) -> None:
        """Verify that a non-JSON response raises LLMResponseInvalid."""
        from modules.exceptions import LLMResponseInvalid

        def mock_call(**kwargs):
            return "This is not JSON at all, just plain text analysis."

        with patch("modules.sentiment._llm_call", side_effect=mock_call):
            with pytest.raises(LLMResponseInvalid):
                _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

    def test_malformed_json_full_pipeline_fallback(self, mock_news_items: list) -> None:
        """Verify that the full pipeline returns neutral if LLM returns text."""
        def mock_call(**kwargs):
            return "not json"

        with patch("modules.sentiment._llm_call", side_effect=mock_call):
            result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "none"
        assert result.directional_bias == "NEUTRAL"


class TestGroqRateLimit:
    def test_retry_on_rate_limit(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verify retry with exponential backoff on rate limit."""
        from modules.exceptions import LLMUnavailable

        call_count = 0

        def mock_inner_call(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise LLMUnavailable("[all] LLM error: rate limited")
            if call_count % 2 == 1:
                return "Bullish outlook."
            return json.dumps(mock_llm_response)

        with patch("modules.llm_client.llm_call", side_effect=mock_inner_call):
            with patch("tenacity.nap.time.sleep"):
                result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        assert result.sentiment_score == 1.0
        assert call_count >= 3


class TestGroqTotalFailure:
    def test_fallback_on_total_groq_failure(self, mock_news_items: list) -> None:
        """Verify that neutral fallback works if LLM fails completely."""
        from modules.exceptions import LLMUnavailable

        with patch("modules.sentiment._llm_call", side_effect=LLMUnavailable("down")):
            result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "none"
        assert result.directional_bias == "NEUTRAL"


class TestNoApiKey:
    def test_no_api_key_returns_neutral(self, mock_news_items: list) -> None:
        """Verify that without any LLM provider the result is neutral."""
        with patch("modules.llm_client.get_active_provider", return_value="none"):
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
        assert "Invesco NASDAQ-100" in prompt

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
        with patch("modules.llm_client.get_active_provider", return_value="none"):
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
        call_count = 0

        def mock_call(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                return "Bullish outlook."
            return f"```json\n{json.dumps(mock_llm_response)}\n```"

        with patch("modules.sentiment._llm_call", side_effect=mock_call):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

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
            "asset_scores": {"EQQQ.MI": 1.5, "SGLD.MI": -0.8},
        }
        assets = [
            {"symbol": "EQQQ.MI", "display_name": "Invesco NASDAQ-100"},
            {"symbol": "SGLD.MI", "display_name": "Invesco Physical Gold"},
        ]

        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(response_data)):
            result = _analyze_with_groq(mock_news_items, assets, "qwen/qwen3-32b", "fake-key")

        assert result.asset_scores["EQQQ.MI"] == 1.5
        assert result.asset_scores["SGLD.MI"] == -0.8
        assert result.asset_biases["EQQQ.MI"] == "BULLISH"
        assert result.asset_biases["SGLD.MI"] == "BEARISH"

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

        with patch("modules.sentiment._llm_call", side_effect=_mock_llm_call_for(response_data)):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "qwen/qwen3-32b", "fake-key")

        # Falls back to global sentiment_score of 1.0
        assert result.asset_scores["EQQQ.MI"] == 1.0
        assert result.asset_biases["EQQQ.MI"] == "BULLISH"


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
