"""Test suite for the report module."""

from __future__ import annotations

import os
import re
import tempfile
from html.parser import HTMLParser
from io import StringIO
from typing import Any

import pytest

from modules.report import (
    generate_report,
    get_market_session,
    print_terminal_summary,
    _sentiment_color,
    _signal_color,
    _action_hint,
)


class _HTMLValidator(HTMLParser):
    """Simple HTML validator that collects parsing errors."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        self.tags.append(f"/{tag}")

    def error(self, message: str) -> None:
        self.errors.append(message)


class TestReportCreatesFile:
    def test_file_created(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that the HTML report is created at the correct path."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            assert os.path.exists(path)
            assert path.endswith(".html")

    def test_filename_format(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that the filename follows the format report_YYYYMMDD_HHMM.html."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            filename = os.path.basename(path)
            assert re.match(r"report_\d{8}_\d{4}\.html", filename)


class TestReportHTMLValid:
    def test_html_parses_without_errors(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that the generated HTML is valid and parseable."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html_content = f.read()

        validator = _HTMLValidator()
        validator.feed(html_content)
        assert len(validator.errors) == 0

    def test_html_has_doctype(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify the presence of DOCTYPE HTML."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html_content = f.read()

        assert html_content.strip().startswith("<!DOCTYPE html>")


class TestReportContainsSections:
    def test_all_sections_present(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that all 7 sections are present in the report."""
        sentiment = make_sentiment(risk_events=["Fed meeting tomorrow"])
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        # 1. Header
        assert "Trading Assistant Report" in html
        # 2. Sentiment card
        assert "Macro Sentiment" in html
        # 3. Key drivers
        assert "Key Drivers" in html
        # 4. Risk events
        assert "RISK EVENTS" in html or "No particular risk events" in html
        # 5. Assets table
        assert "Asset Analysis" in html
        # 6. Raw news
        assert "Raw News" in html
        # 7. Footer
        assert "Not financial advice" in html

    def test_risk_events_shown_when_present(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that risk events are displayed when present."""
        sentiment = make_sentiment(risk_events=["Fed meeting tomorrow", "CPI release"])
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        assert "Fed meeting tomorrow" in html
        assert "CPI release" in html


class TestSentimentColors:
    def test_positive_score_green(self) -> None:
        """Verify that +2 score produces green color."""
        color = _sentiment_color(2.0)
        assert color == "#22c55e"

    def test_negative_score_red(self) -> None:
        """Verify that -2 score produces red color."""
        color = _sentiment_color(-2.0)
        assert color == "#ef4444"

    def test_neutral_score_grey(self) -> None:
        """Verify that 0 score produces grey color."""
        color = _sentiment_color(0.0)
        assert color == "#9ca3af"

    def test_color_in_html(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that the sentiment color appears in HTML."""
        sentiment = make_sentiment(score=2.0)
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        assert "#22c55e" in html  # Green for +2


class TestSignalColors:
    def test_bullish_green(self) -> None:
        """Verify green color for BULLISH signal."""
        assert _signal_color("BULLISH") == "#22c55e"

    def test_bearish_red(self) -> None:
        """Verify red color for BEARISH signal."""
        assert _signal_color("BEARISH") == "#ef4444"

    def test_neutral_yellow(self) -> None:
        """Verify yellow color for NEUTRAL signal."""
        assert _signal_color("NEUTRAL") == "#eab308"


class TestDisclaimer:
    def test_disclaimer_present(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that the legal disclaimer is present in the footer."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        assert "Not financial advice" in html


class TestTerminalSummary:
    def test_summary_contains_asset_info(self, make_sentiment, make_asset_analysis, capsys) -> None:
        """Verify that the terminal summary contains asset info."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        print_terminal_summary(sentiment, assets, 10)

        captured = capsys.readouterr()
        assert "NASDAQ 100 Futures" in captured.out
        assert "TRADING ASSISTANT" in captured.out

    def test_summary_contains_sentiment(self, make_sentiment, make_asset_analysis, capsys) -> None:
        """Verify that the summary contains sentiment score and bias."""
        sentiment = make_sentiment(score=1.5, bias="BULLISH")
        assets = [make_asset_analysis()]

        print_terminal_summary(sentiment, assets, 5)

        captured = capsys.readouterr()
        assert "+1.5" in captured.out
        assert "BULLISH" in captured.out

    def test_summary_contains_disclaimer(self, make_sentiment, make_asset_analysis, capsys) -> None:
        """Verify that the summary contains the disclaimer."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        print_terminal_summary(sentiment, assets, 5)

        captured = capsys.readouterr()
        assert "Not financial advice" in captured.out


class TestActionHint:
    def test_bullish_long(self) -> None:
        """Verify LONG hint when technicals and bias agree bullish."""
        assert _action_hint("BULLISH", "BULLISH") == "Look for LONG"

    def test_bearish_short(self) -> None:
        """Verify SHORT hint when technicals and bias agree bearish."""
        assert _action_hint("BEARISH", "BEARISH") == "Look for SHORT"

    def test_conflict(self) -> None:
        """Verify caution hint when technicals and bias conflict."""
        assert "Conflict" in _action_hint("BULLISH", "BEARISH")
        assert "Conflict" in _action_hint("BEARISH", "BULLISH")

    def test_neutral(self) -> None:
        """Verify wait hint for neutral signal."""
        assert _action_hint("NEUTRAL", "NEUTRAL") == "Wait"


class TestMarketSession:
    def test_returns_string(self) -> None:
        """Verify that get_market_session returns a string."""
        session = get_market_session()
        assert isinstance(session, str)
        assert len(session) > 0


class TestAssetWithError:
    def test_error_asset_rendered(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verify that an asset with error is displayed in the report."""
        sentiment = make_sentiment()
        assets = [
            make_asset_analysis(),
            make_asset_analysis(symbol="ERR=F", display_name="Error Asset", error="Connection failed"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        assert "Error Asset" in html
        assert "Connection failed" in html
