"""Test suite for the news_fetcher module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import feedparser
import pytest

from modules.news_fetcher import _deduplicate, _fetch_single_feed, _parse_entry_date, fetch_news


class TestParseValidRSS:
    def test_parse_valid_rss(self, mock_rss_feed_xml: str) -> None:
        """Verify that feedparser correctly parses a valid RSS XML."""
        feed = feedparser.parse(mock_rss_feed_xml)
        assert len(feed.entries) == 3
        assert feed.entries[0].title == "S&P 500 closes at record high on strong earnings"
        assert "description" in feed.entries[0] or "summary" in feed.entries[0]

    def test_parsed_entries_have_required_keys(self, mock_rss_feed_xml: str) -> None:
        """Verify that each entry has the required keys after parsing."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=16)).timestamp()
        with patch("modules.news_fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = feedparser.parse(mock_rss_feed_xml)
            articles = _fetch_single_feed("http://test.com/rss", "TestSource", cutoff)

        for article in articles:
            assert "title" in article
            assert "summary" in article
            assert "source" in article
            assert "published_at" in article


class TestFilterByHours:
    def test_recent_articles_kept(self) -> None:
        """Verify that recent articles are kept."""
        now = datetime.now(timezone.utc)
        feeds = [{"url": "http://test.com/rss", "name": "Test"}]

        fake_entry_recent = MagicMock()
        fake_entry_recent.get = lambda k, d="": {
            "title": "Recent article",
            "summary": "Summary",
            "published": (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
        }.get(k, d)
        fake_entry_recent.title = "Recent article"

        fake_entry_old = MagicMock()
        fake_entry_old.get = lambda k, d="": {
            "title": "Old article",
            "summary": "Old summary",
            "published": (now - timedelta(hours=20)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
        }.get(k, d)
        fake_entry_old.title = "Old article"

        fake_feed = MagicMock()
        fake_feed.bozo = False
        fake_feed.entries = [fake_entry_recent, fake_entry_old]

        with patch("modules.news_fetcher.feedparser.parse", return_value=fake_feed):
            articles = fetch_news(feeds, lookback_hours=16)

        titles = [a["title"] for a in articles]
        assert "Recent article" in titles
        assert "Old article" not in titles

    def test_old_articles_excluded(self) -> None:
        """Verify that articles beyond lookback are excluded."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=4)).timestamp()

        fake_entry = MagicMock()
        fake_entry.get = lambda k, d="": {
            "title": "Very old news",
            "summary": "",
            "published": (now - timedelta(hours=20)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
        }.get(k, d)

        fake_feed = MagicMock()
        fake_feed.bozo = False
        fake_feed.entries = [fake_entry]

        with patch("modules.news_fetcher.feedparser.parse", return_value=fake_feed):
            articles = _fetch_single_feed("http://test.com", "Test", cutoff)

        assert len(articles) == 0


class TestDeduplication:
    def test_similar_titles_deduplicated(self) -> None:
        """Verify that 90% similar titles are deduplicated."""
        now = datetime.now(timezone.utc)
        articles = [
            {"title": "S&P 500 closes at record high on strong tech earnings", "summary": "", "source": "A", "published_at": now},
            {"title": "S&P 500 closes at record high on strong technology earnings", "summary": "", "source": "B", "published_at": now},
        ]
        result = _deduplicate(articles)
        assert len(result) == 1

    def test_different_titles_kept(self) -> None:
        """Verify that different titles are not deduplicated."""
        now = datetime.now(timezone.utc)
        articles = [
            {"title": "Tech stocks rally on earnings", "summary": "", "source": "A", "published_at": now},
            {"title": "Oil prices crash on demand fears", "summary": "", "source": "B", "published_at": now},
        ]
        result = _deduplicate(articles)
        assert len(result) == 2


class TestNetworkRetry:
    def test_retry_on_failure_then_success(self) -> None:
        """Verify that retry works after network errors."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=16)).timestamp()

        good_entry = MagicMock()
        good_entry.get = lambda k, d="": {
            "title": "Good article",
            "summary": "Summary",
            "published": (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
        }.get(k, d)

        good_feed = MagicMock()
        good_feed.bozo = False
        good_feed.entries = [good_entry]

        call_count = 0

        def side_effect(url):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                bad = MagicMock()
                bad.bozo = True
                bad.entries = []
                bad.bozo_exception = ConnectionError("Network error")
                return bad
            return good_feed

        with patch("modules.news_fetcher.feedparser.parse", side_effect=side_effect):
            with patch("modules.news_fetcher.time.sleep"):
                articles = _fetch_single_feed("http://test.com", "Test", cutoff)

        assert len(articles) == 1
        assert call_count == 3

    def test_total_failure_returns_empty(self) -> None:
        """Verify that 3 failed attempts return empty list without exceptions."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=16)).timestamp()

        bad_feed = MagicMock()
        bad_feed.bozo = True
        bad_feed.entries = []
        bad_feed.bozo_exception = ConnectionError("Total failure")

        with patch("modules.news_fetcher.feedparser.parse", return_value=bad_feed):
            with patch("modules.news_fetcher.time.sleep"):
                articles = _fetch_single_feed("http://test.com", "Test", cutoff)

        assert articles == []


class TestEdgeCases:
    def test_empty_feed(self) -> None:
        """Verify that a feed without entries returns empty list."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=16)).timestamp()
        empty_feed = MagicMock()
        empty_feed.bozo = False
        empty_feed.entries = []

        with patch("modules.news_fetcher.feedparser.parse", return_value=empty_feed):
            articles = _fetch_single_feed("http://test.com", "Test", cutoff)

        assert articles == []

    def test_missing_summary_field(self) -> None:
        """Verify that an entry without summary does not crash."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=16)).timestamp()

        entry = MagicMock()
        entry.get = lambda k, d="": {
            "title": "Article without summary",
            "published": (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000"),
        }.get(k, d)

        feed = MagicMock()
        feed.bozo = False
        feed.entries = [entry]

        with patch("modules.news_fetcher.feedparser.parse", return_value=feed):
            articles = _fetch_single_feed("http://test.com", "Test", cutoff)

        assert len(articles) == 1
        assert articles[0]["summary"] == ""

    def test_parse_entry_date_missing(self) -> None:
        """Verify that an entry without date returns None."""
        entry = MagicMock()
        entry.get = lambda k, d=None: None
        assert _parse_entry_date(entry) is None
