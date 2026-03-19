"""Test suite per il modulo report."""

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
    """Validatore HTML semplice che raccoglie errori di parsing."""

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
        """Verifica che il report HTML venga creato nel percorso corretto."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            assert os.path.exists(path)
            assert path.endswith(".html")

    def test_filename_format(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verifica che il nome file segua il formato report_YYYYMMDD_HHMM.html."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            filename = os.path.basename(path)
            assert re.match(r"report_\d{8}_\d{4}\.html", filename)


class TestReportHTMLValid:
    def test_html_parses_without_errors(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verifica che l'HTML generato sia valido e parsabile."""
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
        """Verifica la presenza del DOCTYPE HTML."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html_content = f.read()

        assert html_content.strip().startswith("<!DOCTYPE html>")


class TestReportContainsSections:
    def test_all_sections_present(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verifica che tutte e 7 le sezioni siano presenti nel report."""
        sentiment = make_sentiment(risk_events=["Fed meeting domani"])
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        # 1. Header
        assert "Trading Assistant Report" in html
        # 2. Sentiment card
        assert "Sentiment Macro" in html
        # 3. Key drivers
        assert "Key Drivers" in html
        # 4. Risk events
        assert "RISK EVENTS" in html or "Nessun evento di rischio" in html
        # 5. Assets table
        assert "Analisi Assets" in html
        # 6. Raw news
        assert "Notizie Raw" in html
        # 7. Footer
        assert "Nessun consiglio finanziario" in html

    def test_risk_events_shown_when_present(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verifica che i risk events vengano mostrati quando presenti."""
        sentiment = make_sentiment(risk_events=["Fed meeting domani", "CPI release"])
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        assert "Fed meeting domani" in html
        assert "CPI release" in html


class TestSentimentColors:
    def test_positive_score_green(self) -> None:
        """Verifica che score +2 produca un colore verde."""
        color = _sentiment_color(2.0)
        assert color == "#22c55e"

    def test_negative_score_red(self) -> None:
        """Verifica che score -2 produca un colore rosso."""
        color = _sentiment_color(-2.0)
        assert color == "#ef4444"

    def test_neutral_score_grey(self) -> None:
        """Verifica che score 0 produca un colore grigio."""
        color = _sentiment_color(0.0)
        assert color == "#9ca3af"

    def test_color_in_html(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verifica che il colore del sentiment appaia nell'HTML."""
        sentiment = make_sentiment(score=2.0)
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        assert "#22c55e" in html  # Green for +2


class TestSignalColors:
    def test_bullish_green(self) -> None:
        """Verifica colore verde per segnale BULLISH."""
        assert _signal_color("BULLISH") == "#22c55e"

    def test_bearish_red(self) -> None:
        """Verifica colore rosso per segnale BEARISH."""
        assert _signal_color("BEARISH") == "#ef4444"

    def test_neutral_yellow(self) -> None:
        """Verifica colore giallo per segnale NEUTRAL."""
        assert _signal_color("NEUTRAL") == "#eab308"


class TestDisclaimer:
    def test_disclaimer_present(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verifica che il disclaimer legale sia presente nel footer."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(sentiment, assets, mock_news_items, tmpdir)
            with open(path, encoding="utf-8") as f:
                html = f.read()

        assert "Nessun consiglio finanziario" in html


class TestTerminalSummary:
    def test_summary_contains_asset_info(self, make_sentiment, make_asset_analysis, capsys) -> None:
        """Verifica che il summary terminale contenga le info sugli asset."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        print_terminal_summary(sentiment, assets, 10)

        captured = capsys.readouterr()
        assert "NASDAQ 100 Futures" in captured.out
        assert "TRADING ASSISTANT" in captured.out

    def test_summary_contains_sentiment(self, make_sentiment, make_asset_analysis, capsys) -> None:
        """Verifica che il summary contenga il sentiment score e bias."""
        sentiment = make_sentiment(score=1.5, bias="BULLISH")
        assets = [make_asset_analysis()]

        print_terminal_summary(sentiment, assets, 5)

        captured = capsys.readouterr()
        assert "+1.5" in captured.out
        assert "BULLISH" in captured.out

    def test_summary_contains_disclaimer(self, make_sentiment, make_asset_analysis, capsys) -> None:
        """Verifica che il summary contenga il disclaimer."""
        sentiment = make_sentiment()
        assets = [make_asset_analysis()]

        print_terminal_summary(sentiment, assets, 5)

        captured = capsys.readouterr()
        assert "Nessun consiglio finanziario" in captured.out


class TestActionHint:
    def test_bullish_long(self) -> None:
        """Verifica hint LONG quando tecnici e bias concordano bullish."""
        assert _action_hint("BULLISH", "BULLISH") == "Cercare LONG"

    def test_bearish_short(self) -> None:
        """Verifica hint SHORT quando tecnici e bias concordano bearish."""
        assert _action_hint("BEARISH", "BEARISH") == "Cercare SHORT"

    def test_conflict(self) -> None:
        """Verifica hint cautela quando tecnici e bias sono in conflitto."""
        assert "Conflitto" in _action_hint("BULLISH", "BEARISH")
        assert "Conflitto" in _action_hint("BEARISH", "BULLISH")

    def test_neutral(self) -> None:
        """Verifica hint attesa per segnale neutro."""
        assert _action_hint("NEUTRAL", "NEUTRAL") == "Attendere"


class TestMarketSession:
    def test_returns_string(self) -> None:
        """Verifica che get_market_session restituisca una stringa."""
        session = get_market_session()
        assert isinstance(session, str)
        assert len(session) > 0


class TestAssetWithError:
    def test_error_asset_rendered(self, make_sentiment, make_asset_analysis, mock_news_items) -> None:
        """Verifica che un asset con errore venga mostrato nel report."""
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
