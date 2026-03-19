"""Test suite for the hallucination_guard module."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.hallucination_guard import validate, _keyword_sentiment, ValidationResult


class TestNoFlagsOnConsistentData:
    def test_consistent_bullish_data(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify no flags when LLM, keyword and technicals agree."""
        # Use only bullish news
        bullish_news = [n for n in mock_news_items if any(kw in n["title"].lower() for kw in ["rally", "jump", "surge"])]
        sentiment = make_sentiment(score=2.0, bias="BULLISH")
        assets = [make_asset_analysis(composite_score="BULLISH")]

        result = validate(sentiment, bullish_news, assets)

        assert result.validated is True
        assert result.flags == []

    def test_consistent_bearish_data(self, make_sentiment, make_asset_analysis) -> None:
        """Verify no flags with consistently bearish data."""
        now = datetime.now(timezone.utc)
        bearish_news = [
            {"title": "Markets crash on recession fears", "summary": "Panic selling.", "source": "Test", "published_at": now},
            {"title": "Stocks drop sharply amid crisis", "summary": "Bear market.", "source": "Test", "published_at": now},
        ]
        sentiment = make_sentiment(score=-2.0, bias="BEARISH")
        assets = [make_asset_analysis(composite_score="BEARISH")]

        result = validate(sentiment, bearish_news, assets)

        assert result.validated is True
        assert result.flags == []


class TestSentimentMismatch:
    def test_bullish_llm_bearish_news(self, make_sentiment, make_asset_analysis) -> None:
        """Verify SENTIMENT_MISMATCH flag: LLM bullish but news bearish."""
        now = datetime.now(timezone.utc)
        bearish_news = [
            {"title": "Markets crash on recession fears", "summary": "", "source": "A", "published_at": now},
            {"title": "Stock market in panic sell-off", "summary": "", "source": "B", "published_at": now},
            {"title": "Investors fear global collapse", "summary": "", "source": "C", "published_at": now},
            {"title": "Economy faces severe decline", "summary": "", "source": "D", "published_at": now},
        ]
        sentiment = make_sentiment(score=2.5, bias="BULLISH")
        assets = [make_asset_analysis(composite_score="BULLISH")]

        result = validate(sentiment, bearish_news, assets)

        assert "SENTIMENT_MISMATCH" in result.flags

    def test_bearish_llm_bullish_news(self, make_sentiment, make_asset_analysis) -> None:
        """Verify SENTIMENT_MISMATCH flag: LLM bearish but news bullish."""
        now = datetime.now(timezone.utc)
        bullish_news = [
            {"title": "Stock market rally continues", "summary": "", "source": "A", "published_at": now},
            {"title": "Record high surge in tech stocks", "summary": "", "source": "B", "published_at": now},
            {"title": "Bull market gains momentum", "summary": "", "source": "C", "published_at": now},
            {"title": "Strong growth in corporate profits", "summary": "", "source": "D", "published_at": now},
        ]
        sentiment = make_sentiment(score=-2.0, bias="BEARISH")
        assets = [make_asset_analysis(composite_score="BEARISH")]

        result = validate(sentiment, bullish_news, assets)

        assert "SENTIMENT_MISMATCH" in result.flags


class TestDirectionConflict:
    def test_long_bias_bearish_technicals(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify DIRECTION_CONFLICT flag: LLM BULLISH but technicals BEARISH."""
        sentiment = make_sentiment(score=1.0, bias="BULLISH")
        assets = [make_asset_analysis(composite_score="BEARISH")]

        result = validate(sentiment, mock_news_items, assets)

        assert "DIRECTION_CONFLICT" in result.flags

    def test_short_bias_bullish_technicals(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify DIRECTION_CONFLICT flag: LLM BEARISH but technicals BULLISH."""
        sentiment = make_sentiment(score=-1.0, bias="BEARISH")
        assets = [make_asset_analysis(composite_score="BULLISH")]

        result = validate(sentiment, mock_news_items, assets)

        assert "DIRECTION_CONFLICT" in result.flags

    def test_no_conflict_when_neutral(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify no DIRECTION_CONFLICT flag with neutral technicals."""
        sentiment = make_sentiment(score=1.0, bias="BULLISH")
        assets = [make_asset_analysis(composite_score="NEUTRAL")]

        result = validate(sentiment, mock_news_items, assets)

        assert "DIRECTION_CONFLICT" not in result.flags


class TestPerAssetDirectionConflict:
    def test_per_asset_conflict_detected(self, make_asset_analysis, mock_news_items) -> None:
        """Verify per-asset DIRECTION_CONFLICT when asset_biases diverge."""
        from modules.sentiment import SentimentResult

        sentiment = SentimentResult(
            sentiment_score=1.0,
            sentiment_label="Bullish",
            directional_bias="BULLISH",
            asset_biases={"NQ=F": "BULLISH", "GC=F": "BEARISH"},
            asset_scores={"NQ=F": 1.5, "GC=F": -1.0},
        )
        assets = [
            make_asset_analysis(symbol="NQ=F", composite_score="BEARISH"),
            make_asset_analysis(symbol="GC=F", composite_score="BEARISH"),
        ]

        result = validate(sentiment, mock_news_items, assets)

        # NQ=F: LLM BULLISH vs tech BEARISH → conflict
        assert any("DIRECTION_CONFLICT_NQ=F" in f for f in result.flags)
        # GC=F: LLM BEARISH vs tech BEARISH → no conflict
        assert not any("DIRECTION_CONFLICT_GC=F" in f for f in result.flags)

    def test_no_per_asset_conflict_when_aligned(self, make_asset_analysis, mock_news_items) -> None:
        """No per-asset conflict when LLM and technicals agree."""
        from modules.sentiment import SentimentResult

        sentiment = SentimentResult(
            sentiment_score=1.0,
            sentiment_label="Bullish",
            directional_bias="BULLISH",
            asset_biases={"NQ=F": "BULLISH"},
            asset_scores={"NQ=F": 1.5},
        )
        assets = [make_asset_analysis(symbol="NQ=F", composite_score="BULLISH")]

        result = validate(sentiment, mock_news_items, assets)

        assert not any("DIRECTION_CONFLICT" in f for f in result.flags)


class TestExtremeScoreNeutralNews:
    def test_extreme_positive_neutral_news(self, make_sentiment, make_asset_analysis) -> None:
        """Verify flag on extreme score (+3) with neutral news."""
        now = datetime.now(timezone.utc)
        neutral_news = [
            {"title": "Central bank meets next week", "summary": "", "source": "A", "published_at": now},
            {"title": "Markets await economic data", "summary": "", "source": "B", "published_at": now},
            {"title": "Trading volume remains steady", "summary": "", "source": "C", "published_at": now},
        ]
        sentiment = make_sentiment(score=3.0, bias="BULLISH")
        assets = [make_asset_analysis(composite_score="BULLISH")]

        result = validate(sentiment, neutral_news, assets)

        assert "EXTREME_SCORE_NEUTRAL_NEWS" in result.flags

    def test_extreme_negative_neutral_news(self, make_sentiment, make_asset_analysis) -> None:
        """Verify flag on extreme score (-3) with neutral news."""
        now = datetime.now(timezone.utc)
        neutral_news = [
            {"title": "Markets closed for holiday", "summary": "", "source": "A", "published_at": now},
            {"title": "Weekly review of bond yields", "summary": "", "source": "B", "published_at": now},
        ]
        sentiment = make_sentiment(score=-3.0, bias="BEARISH")
        assets = [make_asset_analysis(composite_score="BEARISH")]

        result = validate(sentiment, neutral_news, assets)

        assert "EXTREME_SCORE_NEUTRAL_NEWS" in result.flags


class TestMultipleFlags:
    def test_both_mismatch_and_conflict(self, make_sentiment, make_asset_analysis) -> None:
        """Verify that multiple flags can appear simultaneously."""
        now = datetime.now(timezone.utc)
        bearish_news = [
            {"title": "Markets crash on recession fears", "summary": "", "source": "A", "published_at": now},
            {"title": "Panic selling spreads globally", "summary": "", "source": "B", "published_at": now},
            {"title": "Stocks plunge to yearly lows", "summary": "", "source": "C", "published_at": now},
            {"title": "Fear grips investors as markets drop", "summary": "", "source": "D", "published_at": now},
        ]
        # LLM says strong bullish but news is bearish AND technicals are bearish
        sentiment = make_sentiment(score=3.0, bias="BULLISH")
        assets = [make_asset_analysis(composite_score="BEARISH")]

        result = validate(sentiment, bearish_news, assets)

        assert "SENTIMENT_MISMATCH" in result.flags
        assert "DIRECTION_CONFLICT" in result.flags
        assert len(result.flags) >= 2


class TestValidatedFalse:
    def test_any_flag_means_not_validated(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that any flag makes validated=False."""
        sentiment = make_sentiment(score=1.0, bias="BEARISH")
        assets = [make_asset_analysis(composite_score="BULLISH")]

        result = validate(sentiment, mock_news_items, assets)

        if result.flags:
            assert result.validated is False

    def test_no_flags_means_validated(self, make_sentiment, make_asset_analysis) -> None:
        """Verify that no flags makes validated=True."""
        now = datetime.now(timezone.utc)
        bullish_news = [
            {"title": "Markets rally on strong data", "summary": "", "source": "A", "published_at": now},
            {"title": "Bull market surge continues", "summary": "", "source": "B", "published_at": now},
        ]
        sentiment = make_sentiment(score=1.5, bias="BULLISH")
        assets = [make_asset_analysis(composite_score="BULLISH")]

        result = validate(sentiment, bullish_news, assets)

        assert result.validated is True
        assert result.flags == []


class TestKeywordSentiment:
    def test_bullish_keywords_positive_score(self) -> None:
        """Verify that bullish keywords produce positive score."""
        now = datetime.now(timezone.utc)
        news = [
            {"title": "Stock market rally continues", "summary": "", "source": "A", "published_at": now},
            {"title": "Tech surge to new records", "summary": "", "source": "B", "published_at": now},
        ]
        score = _keyword_sentiment(news)
        assert score > 0

    def test_bearish_keywords_negative_score(self) -> None:
        """Verify that bearish keywords produce negative score."""
        now = datetime.now(timezone.utc)
        news = [
            {"title": "Markets crash on fear", "summary": "", "source": "A", "published_at": now},
            {"title": "Stocks drop in panic sell-off", "summary": "", "source": "B", "published_at": now},
        ]
        score = _keyword_sentiment(news)
        assert score < 0

    def test_empty_news_returns_zero(self) -> None:
        """Verify that no news returns zero score."""
        assert _keyword_sentiment([]) == 0.0

    def test_validation_result_to_dict(self) -> None:
        """Verify serialization of ValidationResult."""
        result = ValidationResult(validated=False, flags=["SENTIMENT_MISMATCH"])
        d = result.to_dict()
        assert d["validated"] is False
        assert "SENTIMENT_MISMATCH" in d["flags"]
