"""Test suite for the economic_calendar module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from modules.economic_calendar import (
    CalendarData,
    EconomicEvent,
    _parse_ff_event,
    fetch_calendar,
)


def _make_event(
    title: str = "Non-Farm Payrolls",
    country: str = "USD",
    hours_from_now: float = 3.0,
    impact: str = "High",
    forecast: str = "180K",
    previous: str = "175K",
) -> dict:
    """Build a raw FF calendar event dict."""
    dt = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    return {
        "title": title,
        "country": country,
        "date": dt.isoformat(),
        "impact": impact,
        "forecast": forecast,
        "previous": previous,
    }


class TestParseEvent:
    def test_valid_event(self) -> None:
        raw = _make_event()
        event = _parse_ff_event(raw)
        assert event is not None
        assert event.title == "Non-Farm Payrolls"
        assert event.country == "USD"
        assert event.impact == "High"

    def test_missing_title_returns_none(self) -> None:
        raw = _make_event()
        raw["title"] = ""
        assert _parse_ff_event(raw) is None

    def test_missing_date_returns_none(self) -> None:
        raw = _make_event()
        raw["date"] = ""
        assert _parse_ff_event(raw) is None

    def test_impact_normalization(self) -> None:
        raw = _make_event(impact="high")
        event = _parse_ff_event(raw)
        assert event.impact == "High"

    def test_keyword_upgrade_to_high(self) -> None:
        """Events with known high-impact keywords get upgraded."""
        raw = _make_event(title="CPI Year-over-Year", impact="Medium")
        event = _parse_ff_event(raw)
        assert event.impact == "High"

    def test_fomc_upgraded(self) -> None:
        raw = _make_event(title="FOMC Statement", impact="low")
        event = _parse_ff_event(raw)
        assert event.impact == "High"

    def test_low_impact_stays_low(self) -> None:
        raw = _make_event(title="Building Permits", impact="Low")
        event = _parse_ff_event(raw)
        assert event.impact == "Low"


class TestEconomicEvent:
    def test_hours_away(self) -> None:
        dt = datetime.now(timezone.utc) + timedelta(hours=2.5)
        event = EconomicEvent("Test", "USD", dt, "High")
        assert 2.0 < event.hours_away < 3.0

    def test_is_today(self) -> None:
        dt = datetime.now(timezone.utc) + timedelta(hours=1)
        event = EconomicEvent("Test", "USD", dt, "High")
        assert event.is_today is True

    def test_is_not_today(self) -> None:
        dt = datetime.now(timezone.utc) + timedelta(days=2)
        event = EconomicEvent("Test", "USD", dt, "High")
        assert event.is_today is False

    def test_to_dict(self) -> None:
        dt = datetime.now(timezone.utc) + timedelta(hours=1)
        event = EconomicEvent("NFP", "USD", dt, "High", "180K", "175K")
        d = event.to_dict()
        assert d["title"] == "NFP"
        assert d["country"] == "USD"
        assert "hours_away" in d


class TestFetchCalendar:
    def test_filters_today_events(self) -> None:
        """Only today's events from relevant countries are included."""
        today_usd = _make_event(title="NFP", country="USD", hours_from_now=3)
        today_eur = _make_event(title="ECB Rate", country="EUR", hours_from_now=5)
        tomorrow = _make_event(title="GDP", country="USD", hours_from_now=30)
        today_jpy = _make_event(title="BOJ", country="JPY", hours_from_now=2)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [today_usd, today_eur, tomorrow, today_jpy]
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.economic_calendar.requests.get", return_value=mock_resp):
            result = fetch_calendar()

        # today_usd and today_eur should be included; tomorrow and JPY excluded
        assert len(result.events_today) == 2
        titles = {e.title for e in result.events_today}
        assert "NFP" in titles
        assert "ECB Rate" in titles

    def test_high_impact_filter(self) -> None:
        high = _make_event(title="FOMC", impact="High", hours_from_now=2)
        low = _make_event(title="Building Permits", impact="Low", hours_from_now=4)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [high, low]
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.economic_calendar.requests.get", return_value=mock_resp):
            result = fetch_calendar()

        assert len(result.high_impact_today) == 1
        assert result.high_impact_today[0].title == "FOMC"

    def test_regime_override_within_2h(self) -> None:
        """Regime override fires when high-impact event is within 2 hours."""
        imminent = _make_event(title="CPI", impact="High", hours_from_now=1.5)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [imminent]
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.economic_calendar.requests.get", return_value=mock_resp):
            result = fetch_calendar()

        assert result.regime_override is True
        assert "CPI" in result.override_reason
        assert result.hours_to_next is not None
        assert result.hours_to_next < 2.0

    def test_no_regime_override_beyond_2h(self) -> None:
        """No regime override when event is more than 2 hours away."""
        later = _make_event(title="NFP", impact="High", hours_from_now=4.0)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [later]
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.economic_calendar.requests.get", return_value=mock_resp):
            result = fetch_calendar()

        assert result.regime_override is False
        assert result.next_high_impact is not None

    def test_next_high_impact_is_soonest(self) -> None:
        """next_high_impact should be the soonest upcoming event."""
        later = _make_event(title="GDP", impact="High", hours_from_now=6)
        sooner = _make_event(title="CPI", impact="High", hours_from_now=3)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [later, sooner]
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.economic_calendar.requests.get", return_value=mock_resp):
            result = fetch_calendar()

        assert result.next_high_impact.title == "CPI"

    def test_past_events_not_in_next(self) -> None:
        """Past events should not be the next high-impact event."""
        past = _make_event(title="NFP", impact="High", hours_from_now=-2)
        future = _make_event(title="FOMC", impact="High", hours_from_now=5)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [past, future]
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.economic_calendar.requests.get", return_value=mock_resp):
            result = fetch_calendar()

        assert result.next_high_impact.title == "FOMC"

    def test_api_failure_returns_empty(self) -> None:
        """API failure should return empty CalendarData, not crash."""
        with patch("modules.economic_calendar.requests.get", side_effect=Exception("timeout")):
            result = fetch_calendar()

        assert len(result.events_today) == 0
        assert result.regime_override is False

    def test_empty_calendar(self) -> None:
        """Empty calendar returns clean CalendarData."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.economic_calendar.requests.get", return_value=mock_resp):
            result = fetch_calendar()

        assert len(result.events_today) == 0
        assert result.next_high_impact is None


class TestCalendarDataSerialization:
    def test_to_dict(self) -> None:
        dt = datetime.now(timezone.utc) + timedelta(hours=2)
        event = EconomicEvent("NFP", "USD", dt, "High", "180K", "175K")
        cd = CalendarData(
            events_today=[event],
            high_impact_today=[event],
            next_high_impact=event,
            hours_to_next=2.0,
        )
        d = cd.to_dict()
        assert len(d["events_today"]) == 1
        assert d["hours_to_next"] == 2.0
        assert d["next_high_impact"]["title"] == "NFP"
