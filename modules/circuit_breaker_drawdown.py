"""Drawdown circuit breaker — pauses signal generation after excessive losses.

Monitors realised P&L from the Trade table and suspends signal firing
when drawdown exceeds configurable daily or weekly thresholds.

Usage::

    breaker = DrawdownCircuitBreaker(session_factory)
    if await breaker.is_tripped():
        # do NOT fire signals — breaker is open
        ...
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func

logger = logging.getLogger(__name__)

# Defaults — can be overridden via env or config
DEFAULT_MAX_DAILY_LOSS_PIPS = -100.0   # max daily drawdown in pips
DEFAULT_MAX_WEEKLY_LOSS_PIPS = -250.0  # max weekly drawdown in pips


class DrawdownCircuitBreaker:
    """Monitors trade drawdown and blocks signal generation when limits hit."""

    def __init__(
        self,
        session_factory: Any,
        max_daily_loss: float = DEFAULT_MAX_DAILY_LOSS_PIPS,
        max_weekly_loss: float = DEFAULT_MAX_WEEKLY_LOSS_PIPS,
    ):
        self._session_factory = session_factory
        self.max_daily_loss = max_daily_loss
        self.max_weekly_loss = max_weekly_loss

    async def _sum_pips(self, since: datetime) -> float:
        """Sum outcome_pips from trades since a given timestamp."""
        from app.models.database import Trade

        async with self._session_factory() as session:
            result = await session.execute(
                select(func.coalesce(func.sum(Trade.outcome_pips), 0.0)).where(
                    Trade.timestamp >= since,
                    Trade.outcome_pips.isnot(None),
                )
            )
            return float(result.scalar_one())

    async def daily_pnl(self) -> float:
        """Return total pips for today (UTC)."""
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self._sum_pips(start_of_day)

    async def weekly_pnl(self) -> float:
        """Return total pips for the current week (Monday-based, UTC)."""
        now = datetime.now(timezone.utc)
        start_of_week = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        return await self._sum_pips(start_of_week)

    async def is_tripped(self) -> bool:
        """Return True if drawdown breaker should block signals."""
        daily = await self.daily_pnl()
        if daily <= self.max_daily_loss:
            logger.warning(
                "DRAWDOWN BREAKER TRIPPED — daily P&L %.1f pips <= limit %.1f",
                daily, self.max_daily_loss,
            )
            return True

        weekly = await self.weekly_pnl()
        if weekly <= self.max_weekly_loss:
            logger.warning(
                "DRAWDOWN BREAKER TRIPPED — weekly P&L %.1f pips <= limit %.1f",
                weekly, self.max_weekly_loss,
            )
            return True

        return False

    async def status(self) -> dict[str, Any]:
        """Return current breaker status for the dashboard."""
        daily = await self.daily_pnl()
        weekly = await self.weekly_pnl()
        tripped = (
            daily <= self.max_daily_loss
            or weekly <= self.max_weekly_loss
        )
        return {
            "tripped": tripped,
            "daily_pnl_pips": round(daily, 1),
            "weekly_pnl_pips": round(weekly, 1),
            "max_daily_loss": self.max_daily_loss,
            "max_weekly_loss": self.max_weekly_loss,
        }
