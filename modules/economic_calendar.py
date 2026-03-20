"""Economic calendar module.

Fetches high-impact economic events from Forex Factory and provides
regime override logic when events are imminent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Countries relevant to our assets (USD-denominated futures + EURUSD)
_RELEVANT_COUNTRIES = {"USD", "EUR", "ALL"}

# High-impact event keywords (for fallback classification)
_HIGH_IMPACT_KEYWORDS = {
    "nonfarm", "non-farm", "nfp", "fomc", "federal funds rate",
    "cpi", "consumer price", "gdp", "retail sales", "pmi",
    "unemployment", "jobless claims", "pce", "core pce",
    "ecb", "interest rate decision", "monetary policy",
    "payrolls", "inflation", "trade balance",
}


@dataclass
class EconomicEvent:
    """A single economic calendar event."""
    title: str
    country: str
    datetime_utc: datetime
    impact: str          # "High", "Medium", "Low"
    forecast: str = ""
    previous: str = ""

    @property
    def hours_away(self) -> float:
        """Hours until event from now."""
        delta = self.datetime_utc - datetime.now(timezone.utc)
        return delta.total_seconds() / 3600

    @property
    def is_today(self) -> bool:
        """Whether event is today (UTC)."""
        now = datetime.now(timezone.utc)
        return self.datetime_utc.date() == now.date()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "country": self.country,
            "datetime_utc": self.datetime_utc.isoformat(),
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
            "hours_away": round(self.hours_away, 1),
        }


@dataclass
class CalendarData:
    """Processed economic calendar data for the report."""
    events_today: list[EconomicEvent] = field(default_factory=list)
    high_impact_today: list[EconomicEvent] = field(default_factory=list)
    next_high_impact: EconomicEvent | None = None
    hours_to_next: float | None = None
    regime_override: bool = False
    override_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "events_today": [e.to_dict() for e in self.events_today],
            "high_impact_today": [e.to_dict() for e in self.high_impact_today],
            "next_high_impact": self.next_high_impact.to_dict() if self.next_high_impact else None,
            "hours_to_next": self.hours_to_next,
            "regime_override": self.regime_override,
            "override_reason": self.override_reason,
        }


def fetch_calendar() -> CalendarData:
    """Fetch this week's economic calendar and process it.

    Returns CalendarData with today's events, high-impact filter,
    and regime override flag if a high-impact event is within 2 hours.
    """
    result = CalendarData()

    try:
        raw_events = _fetch_ff_calendar()
    except Exception as exc:
        logger.warning("Economic calendar fetch failed: %s", exc)
        return result

    now = datetime.now(timezone.utc)

    # Filter for today's events from relevant countries
    for event in raw_events:
        if not event.is_today:
            continue
        if event.country not in _RELEVANT_COUNTRIES:
            continue
        result.events_today.append(event)
        if event.impact == "High":
            result.high_impact_today.append(event)

    # Find next upcoming high-impact event
    upcoming = [
        e for e in result.high_impact_today
        if e.datetime_utc > now
    ]
    if upcoming:
        upcoming.sort(key=lambda e: e.datetime_utc)
        result.next_high_impact = upcoming[0]
        result.hours_to_next = round(upcoming[0].hours_away, 1)

        # Regime override if high-impact event within 2 hours
        if result.hours_to_next <= 2.0:
            result.regime_override = True
            hours_min = result.hours_to_next
            if hours_min < 1:
                time_str = f"{int(hours_min * 60)}m"
            else:
                time_str = f"{hours_min:.1f}h"
            result.override_reason = (
                f"High-impact event in {time_str}: "
                f"{result.next_high_impact.title} ({result.next_high_impact.country})"
            )

    return result


def _fetch_ff_calendar() -> list[EconomicEvent]:
    """Fetch and parse Forex Factory calendar JSON."""
    resp = requests.get(_FF_CALENDAR_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    events: list[EconomicEvent] = []
    for item in data:
        try:
            event = _parse_ff_event(item)
            if event:
                events.append(event)
        except Exception as exc:
            logger.debug("Skipping calendar event: %s", exc)
            continue

    logger.info("Parsed %d economic events from Forex Factory", len(events))
    return events


def _parse_ff_event(item: dict) -> EconomicEvent | None:
    """Parse a single Forex Factory event dict into an EconomicEvent."""
    title = item.get("title", "").strip()
    country = item.get("country", "").strip().upper()
    impact = item.get("impact", "").strip()
    forecast = item.get("forecast", "") or ""
    previous = item.get("previous", "") or ""
    date_str = item.get("date", "")

    if not title or not date_str:
        return None

    # Parse datetime — FF uses ISO format with timezone
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

    # Normalize impact (FF sometimes uses different casing)
    impact_map = {"high": "High", "medium": "Medium", "low": "Low"}
    impact = impact_map.get(impact.lower(), impact)

    # Upgrade impact if title contains known high-impact keywords
    if impact != "High":
        title_lower = title.lower()
        if any(kw in title_lower for kw in _HIGH_IMPACT_KEYWORDS):
            impact = "High"

    return EconomicEvent(
        title=title,
        country=country,
        datetime_utc=dt,
        impact=impact,
        forecast=forecast,
        previous=previous,
    )
