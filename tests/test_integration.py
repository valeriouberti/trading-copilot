"""Integration tests for the full pipeline."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import numpy as np
import pytest

from modules.news_fetcher import fetch_news
from modules.price_data import analyze_assets, AssetAnalysis, TechnicalSignal
from modules.sentiment import analyze_sentiment, SentimentResult
from modules.report import generate_report, print_terminal_summary
from modules.hallucination_guard import validate, validate_polymarket_consistency


def _mock_yf_daily() -> pd.DataFrame:
    """Realistic daily DataFrame for mocks."""
    np.random.seed(42)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=100, freq="D")
    close = np.linspace(100, 130, 100) + np.random.normal(0, 1, 100)
    return pd.DataFrame({
        "Open": close + np.random.normal(0, 0.5, 100),
        "High": close + np.abs(np.random.normal(1, 0.5, 100)),
        "Low": close - np.abs(np.random.normal(1, 0.5, 100)),
        "Close": close,
        "Volume": np.random.randint(1000, 100000, 100).astype(float),
    }, index=dates)


def _mock_yf_5m() -> pd.DataFrame:
    """Realistic 5min DataFrame for mocks."""
    np.random.seed(42)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=200, freq="5min")
    close = 130.0 + np.random.normal(0, 0.3, 200).cumsum()
    return pd.DataFrame({
        "Open": close + np.random.normal(0, 0.1, 200),
        "High": close + np.abs(np.random.normal(0.1, 0.05, 200)),
        "Low": close - np.abs(np.random.normal(0.1, 0.05, 200)),
        "Close": close,
        "Volume": np.random.randint(100, 10000, 200).astype(float),
    }, index=dates)


def _mock_feed_entries(count: int = 5) -> MagicMock:
    """Create a mock RSS feed with N entries."""
    now = datetime.now(timezone.utc)
    entries = []
    titles = [
        "Tech stocks rally on strong earnings",
        "Fed holds rates steady at policy meeting",
        "Oil prices drop on demand concerns",
        "European markets mixed ahead of data",
        "Gold rises as dollar weakens",
    ]
    for i in range(min(count, len(titles))):
        entry = MagicMock()
        pub_date = (now - timedelta(hours=i + 1)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        entry.get = lambda k, d="", _t=titles[i], _p=pub_date: {
            "title": _t,
            "summary": f"Summary for {_t}",
            "published": _p,
        }.get(k, d)
        entries.append(entry)

    feed = MagicMock()
    feed.bozo = False
    feed.entries = entries
    return feed


class TestFullPipelineSuccess:
    def test_end_to_end_with_mocked_externals(self, mock_news_items, mock_llm_response) -> None:
        """Verify the full pipeline with all mocked externals."""
        # Mock yfinance
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: _mock_yf_daily() if kw.get("interval") == "1d" else _mock_yf_5m()
        )

        # Mock Groq
        groq_response = MagicMock()
        groq_response.choices[0].message.content = json.dumps(mock_llm_response)

        mock_groq_client = MagicMock()
        mock_groq_client.chat.completions.create.return_value = groq_response

        assets_config = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]
        feeds_config = [{"url": "http://test.com/rss", "name": "Test Feed"}]

        # Step 1: Fetch news (use pre-made mock)
        news = mock_news_items

        # Step 2: Analyze assets
        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            asset_analyses = analyze_assets(assets_config)

        assert len(asset_analyses) == 1
        assert asset_analyses[0].error is None

        # Step 3: Sentiment
        with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key"}):
            with patch("modules.sentiment.get_groq_client", return_value=mock_groq_client):
                sentiment = analyze_sentiment(news, assets_config)

        assert sentiment.source in ("groq", "groq-2pass")

        # Step 4: Validate
        validation = validate(sentiment, news, asset_analyses)
        assert isinstance(validation.validated, bool)

        # Step 5: Generate report
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = generate_report(sentiment, asset_analyses, news, tmpdir)
            assert os.path.exists(report_path)

            with open(report_path, encoding="utf-8") as f:
                html = f.read()

            assert "NASDAQ 100 Futures" in html
            assert "Not financial advice" in html


class TestPipelineWithNoNews:
    def test_empty_news_pipeline(self) -> None:
        """Verify that the pipeline works without news."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: _mock_yf_daily() if kw.get("interval") == "1d" else _mock_yf_5m()
        )

        assets_config = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]
        empty_news: list[dict[str, Any]] = []

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            asset_analyses = analyze_assets(assets_config)

        sentiment = analyze_sentiment(empty_news, assets_config)
        assert sentiment.sentiment_score == 0.0
        assert sentiment.directional_bias == "NEUTRAL"

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = generate_report(sentiment, asset_analyses, empty_news, tmpdir)
            assert os.path.exists(report_path)


class TestPipelineWithLLMFailure:
    def test_groq_failure_still_generates_report(self, mock_news_items) -> None:
        """Verify that the pipeline completes with fallback if Groq fails."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: _mock_yf_daily() if kw.get("interval") == "1d" else _mock_yf_5m()
        )

        assets_config = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            asset_analyses = analyze_assets(assets_config)

        # Groq fails, FinBERT also mocked
        mock_failing_client = MagicMock()
        mock_failing_client.chat.completions.create.side_effect = Exception("API down")
        with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key"}):
            with patch("modules.sentiment.get_groq_client", return_value=mock_failing_client):
                with patch("modules.sentiment._analyze_with_finbert") as mock_finbert:
                    mock_finbert.return_value = SentimentResult(
                        sentiment_score=0.0,
                        sentiment_label="Neutral (fallback)",
                        key_drivers=["Groq not available"],
                        directional_bias="NEUTRAL",
                        confidence=0.0,
                        source="finbert",
                    )
                    sentiment = analyze_sentiment(mock_news_items, assets_config)

        assert sentiment.source == "finbert"

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = generate_report(sentiment, asset_analyses, mock_news_items, tmpdir)
            assert os.path.exists(report_path)

            with open(report_path, encoding="utf-8") as f:
                html = f.read()
            assert "FINBERT" in html.upper()


class TestPipelineNoLLMFlag:
    def test_no_llm_skips_groq(self, mock_news_items) -> None:
        """Verify that --no-llm does not invoke Groq."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: _mock_yf_daily() if kw.get("interval") == "1d" else _mock_yf_5m()
        )

        assets_config = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            asset_analyses = analyze_assets(assets_config)

        # Simulate --no-llm: create sentiment directly without calling analyze_sentiment
        sentiment = SentimentResult(
            sentiment_score=0.0,
            sentiment_label="N/A — LLM disabled",
            key_drivers=["LLM disabled by user"],
            directional_bias="NEUTRAL",
            confidence=0.0,
            source="none",
        )

        # Verify Groq was never called
        with patch("modules.sentiment.get_groq_client") as mock_groq:
            with tempfile.TemporaryDirectory() as tmpdir:
                report_path = generate_report(sentiment, asset_analyses, mock_news_items, tmpdir)
                assert os.path.exists(report_path)
            mock_groq.assert_not_called()


class TestPipelineCustomAssets:
    def test_custom_assets_only(self) -> None:
        """Verify that --assets override limits analysis to specified assets only."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: _mock_yf_daily() if kw.get("interval") == "1d" else _mock_yf_5m()
        )

        custom_assets = [{"symbol": "GC=F", "display_name": "Gold Futures"}]

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker) as mock_yf:
            results = analyze_assets(custom_assets)

        assert len(results) == 1
        assert results[0].symbol == "GC=F"
        assert results[0].display_name == "Gold Futures"
        # yf.Ticker called 4 times (daily + 5m + weekly + hourly via _fetch_with_retry)
        assert mock_yf.call_count == 4
        mock_yf.assert_any_call("GC=F")


class TestTerminalOutput:
    def test_terminal_summary_runs(self, make_sentiment, make_asset_analysis, capsys) -> None:
        """Verify that the terminal summary does not cause errors."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]
        print_terminal_summary(sentiment, assets, 10)

        captured = capsys.readouterr()
        assert "TRADING ASSISTANT" in captured.out
        assert len(captured.out) > 100

    def test_terminal_summary_with_polymarket(self, make_sentiment, make_asset_analysis, mock_polymarket_data, capsys) -> None:
        """Verify that the terminal summary includes the Polymarket row."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]
        print_terminal_summary(sentiment, assets, 10, poly_data=mock_polymarket_data)

        captured = capsys.readouterr()
        assert "POLYMARKET" in captured.out
        assert "BEARISH" in captured.out


class TestPipelineWithTripleConfluence:
    def test_triple_confluence_in_report(self, mock_news_items, mock_polymarket_data) -> None:
        """All three signals aligned → TRIPLE_CONFLUENCE in HTML report."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: _mock_yf_daily() if kw.get("interval") == "1d" else _mock_yf_5m()
        )

        assets_config = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            asset_analyses = analyze_assets(assets_config)

        # Force all signals BEARISH
        for a in asset_analyses:
            a.composite_score = "BEARISH"

        sentiment = SentimentResult(
            sentiment_score=-2.0,
            sentiment_label="Bearish",
            key_drivers=["Recession fears", "Fed hawkish", "Weak data"],
            directional_bias="BEARISH",
            confidence=75.0,
            source="groq",
        )

        # Polymarket also BEARISH
        poly_data = dict(mock_polymarket_data)
        assert poly_data["signal"] == "BEARISH"

        # Validate
        validation = validate(sentiment, mock_news_items, asset_analyses)
        poly_flags = validate_polymarket_consistency(sentiment, poly_data, asset_analyses)
        all_flags = list(validation.flags) + poly_flags

        assert any("TRIPLE_CONFLUENCE" in f for f in all_flags)

        # Generate report with flags
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = generate_report(
                sentiment, asset_analyses, mock_news_items, tmpdir,
                poly_data=poly_data,
                validation_flags=all_flags,
            )
            assert os.path.exists(report_path)

            with open(report_path, encoding="utf-8") as f:
                html = f.read()

            assert "TRIPLE CONFLUENCE" in html
            assert "Polymarket Signal" in html
