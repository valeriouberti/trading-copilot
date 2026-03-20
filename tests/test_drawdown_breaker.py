"""Tests for the drawdown circuit breaker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.circuit_breaker_drawdown import DrawdownCircuitBreaker


@pytest.fixture
def mock_session_factory():
    """Create a mock async session factory."""
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


class TestDrawdownCircuitBreaker:
    @pytest.mark.asyncio
    async def test_not_tripped_when_no_losses(self, mock_session_factory):
        factory, session = mock_session_factory
        # Return 0.0 pips (no trades)
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 0.0
        session.execute = AsyncMock(return_value=result_mock)

        breaker = DrawdownCircuitBreaker(factory, max_daily_loss=-100, max_weekly_loss=-250)
        assert not await breaker.is_tripped()

    @pytest.mark.asyncio
    async def test_tripped_on_daily_loss(self, mock_session_factory):
        factory, session = mock_session_factory
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = -150.0  # exceeds -100 limit
        session.execute = AsyncMock(return_value=result_mock)

        breaker = DrawdownCircuitBreaker(factory, max_daily_loss=-100, max_weekly_loss=-250)
        assert await breaker.is_tripped()

    @pytest.mark.asyncio
    async def test_tripped_on_weekly_loss(self, mock_session_factory):
        factory, session = mock_session_factory
        call_count = 0

        async def alternating_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Daily P&L: fine
                result.scalar_one.return_value = -50.0
            else:
                # Weekly P&L: exceeds limit
                result.scalar_one.return_value = -300.0
            return result

        session.execute = alternating_execute

        breaker = DrawdownCircuitBreaker(factory, max_daily_loss=-100, max_weekly_loss=-250)
        assert await breaker.is_tripped()

    @pytest.mark.asyncio
    async def test_not_tripped_within_limits(self, mock_session_factory):
        factory, session = mock_session_factory
        call_count = 0

        async def within_limits(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one.return_value = -50.0  # daily: within -100
            else:
                result.scalar_one.return_value = -200.0  # weekly: within -250
            return result

        session.execute = within_limits

        breaker = DrawdownCircuitBreaker(factory, max_daily_loss=-100, max_weekly_loss=-250)
        assert not await breaker.is_tripped()

    @pytest.mark.asyncio
    async def test_status_returns_correct_fields(self, mock_session_factory):
        factory, session = mock_session_factory
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count <= 2:
                # is_tripped calls daily then weekly
                result.scalar_one.return_value = -30.0
            elif call_count == 3:
                result.scalar_one.return_value = -30.0  # daily_pnl
            else:
                result.scalar_one.return_value = -120.0  # weekly_pnl
            return result

        session.execute = mock_execute

        breaker = DrawdownCircuitBreaker(factory, max_daily_loss=-100, max_weekly_loss=-250)
        status = await breaker.status()

        assert "tripped" in status
        assert "daily_pnl_pips" in status
        assert "weekly_pnl_pips" in status
        assert "max_daily_loss" in status
        assert "max_weekly_loss" in status
        assert status["max_daily_loss"] == -100
        assert status["max_weekly_loss"] == -250

    @pytest.mark.asyncio
    async def test_positive_pnl_not_tripped(self, mock_session_factory):
        factory, session = mock_session_factory
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 50.0  # positive P&L
        session.execute = AsyncMock(return_value=result_mock)

        breaker = DrawdownCircuitBreaker(factory, max_daily_loss=-100, max_weekly_loss=-250)
        assert not await breaker.is_tripped()

    @pytest.mark.asyncio
    async def test_exactly_at_limit_trips(self, mock_session_factory):
        factory, session = mock_session_factory
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = -100.0  # exactly at limit
        session.execute = AsyncMock(return_value=result_mock)

        breaker = DrawdownCircuitBreaker(factory, max_daily_loss=-100, max_weekly_loss=-250)
        assert await breaker.is_tripped()
