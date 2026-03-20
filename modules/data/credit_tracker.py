"""Twelve Data daily credit budget tracker.

Free tier: 800 API credits/day.  Each /price or /time_series call costs 1 credit.
This module tracks usage and enforces a daily budget so the monitor never
exceeds the free-tier allowance.

The tracker resets automatically at midnight UTC.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, timezone, datetime

logger = logging.getLogger(__name__)

DAILY_BUDGET = 800
# Reserve 50 credits for ad-hoc API/manual analysis calls
MONITOR_BUDGET = 750


class CreditTracker:
    """Thread-safe daily credit counter."""

    def __init__(self, daily_limit: int = MONITOR_BUDGET):
        self._limit = daily_limit
        self._used = 0
        self._date = date.today()
        self._lock = threading.Lock()

    def _maybe_reset(self) -> None:
        """Reset counter if the UTC day has rolled over."""
        today = datetime.now(timezone.utc).date()
        if today != self._date:
            logger.info(
                "Credit tracker day rollover: %s → %s (used %d/%d yesterday)",
                self._date, today, self._used, self._limit,
            )
            self._used = 0
            self._date = today

    def try_spend(self, credits: int = 1) -> bool:
        """Attempt to spend credits. Returns True if allowed, False if budget exhausted."""
        with self._lock:
            self._maybe_reset()
            if self._used + credits > self._limit:
                logger.warning(
                    "Credit budget exhausted: %d/%d used, %d requested",
                    self._used, self._limit, credits,
                )
                return False
            self._used += credits
            return True

    def spend(self, credits: int = 1) -> None:
        """Record credits spent (unconditional — use after a successful API call)."""
        with self._lock:
            self._maybe_reset()
            self._used += credits

    @property
    def remaining(self) -> int:
        with self._lock:
            self._maybe_reset()
            return max(0, self._limit - self._used)

    @property
    def used(self) -> int:
        with self._lock:
            self._maybe_reset()
            return self._used

    def stats(self) -> dict:
        with self._lock:
            self._maybe_reset()
            return {
                "date": str(self._date),
                "used": self._used,
                "limit": self._limit,
                "remaining": max(0, self._limit - self._used),
                "pct_used": round(self._used / self._limit * 100, 1) if self._limit else 0,
            }

    def max_assets(self, light_interval: int = 120, heavy_interval: int = 1800) -> int:
        """Estimate how many assets can be monitored for the rest of the day.

        Assumes trading day is ~12 hours (London open to NYSE close).
        """
        remaining = self.remaining
        now = datetime.now(timezone.utc)
        # Hours left until midnight UTC (rough)
        hours_left = max(1, 24 - now.hour - now.minute / 60)

        seconds_left = hours_left * 3600
        light_calls_per_asset = seconds_left / light_interval  # /price calls
        heavy_calls_per_asset = seconds_left / heavy_interval  # /time_series calls
        credits_per_asset = light_calls_per_asset + heavy_calls_per_asset

        if credits_per_asset <= 0:
            return 0
        return max(0, int(remaining / credits_per_asset))
