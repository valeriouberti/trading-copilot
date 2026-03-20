"""Notification service — Telegram bot integration.

Sends trading signals, regime changes, and calendar alerts to Telegram.
Rate-limited: max 1 notification per asset per 15 minutes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import NotificationLog

logger = logging.getLogger(__name__)


def _format_number(value: float | None, decimals: int = 2) -> str:
    """Format a number with thousands separator."""
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}"


class TelegramNotifier:
    """Send formatted messages to a Telegram chat via python-telegram-bot."""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self._bot = None

    def _get_bot(self):
        """Lazy-init the bot instance."""
        if self._bot is None:
            from telegram import Bot
            self._bot = Bot(token=self.bot_token)
        return self._bot

    async def _send(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message. Returns True on success."""
        if not self.enabled or not self.bot_token or not self.chat_id:
            logger.debug("Telegram disabled or not configured — skipping")
            return False

        try:
            bot = self._get_bot()
            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except Exception as exc:
            from modules.exceptions import NotificationError
            logger.error("Telegram send failed: %s", exc)
            if "Unauthorized" in str(exc) or "chat not found" in str(exc).lower():
                from modules.exceptions import NotificationPermanent
                raise NotificationPermanent(
                    channel="telegram", detail=str(exc),
                ) from exc
            return False

    async def _check_rate_limit(
        self, session: AsyncSession, symbol: str | None, notif_type: str
    ) -> bool:
        """Return True if we should send (not rate-limited)."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        stmt = select(NotificationLog).where(
            NotificationLog.timestamp >= cutoff,
            NotificationLog.type == notif_type,
        )
        if symbol:
            stmt = stmt.where(NotificationLog.symbol == symbol)

        result = await session.execute(stmt)
        recent = result.scalars().first()
        return recent is None

    async def _log_notification(
        self,
        session: AsyncSession,
        notif_type: str,
        symbol: str | None,
        message: str,
        channel: str = "TELEGRAM",
    ) -> None:
        """Record the notification in the database."""
        entry = NotificationLog(
            type=notif_type,
            symbol=symbol,
            message=message[:500],
            channel=channel,
        )
        session.add(entry)
        await session.commit()

    async def send_signal(
        self,
        symbol: str,
        display_name: str,
        setup: dict,
        regime: str,
        regime_reason: str,
        sentiment: dict | None = None,
        calendar: dict | None = None,
        session: AsyncSession | None = None,
    ) -> bool:
        """Send a trade signal notification."""
        if not setup.get("tradeable"):
            return False

        if session and not await self._check_rate_limit(session, symbol, "SIGNAL"):
            logger.debug("Rate-limited: %s SIGNAL", symbol)
            return False

        direction = setup.get("direction", "?")
        arrow = "LONG" if direction == "LONG" else "SHORT"
        color = "🟢" if direction == "LONG" else "🔴"

        entry = _format_number(setup.get("entry_price"))
        sl = _format_number(setup.get("stop_loss"))
        tp = _format_number(setup.get("take_profit"))
        sl_dist = _format_number(setup.get("sl_distance"))
        tp_dist = _format_number(setup.get("tp_distance"))
        rr = setup.get("risk_reward", "1:2.0")
        qs = setup.get("quality_score", 0)

        # Sentiment info
        sent_score = ""
        if sentiment:
            score = sentiment.get("score")
            if score is not None:
                sent_score = f" ({score:+.1f} sentiment)"

        # Calendar info
        next_event = ""
        if calendar and calendar.get("events_today"):
            ev = calendar["events_today"][0]
            hours = ev.get("hours_away")
            if hours and hours > 0:
                h = int(hours)
                m = int((hours - h) * 60)
                next_event = f"\nNext event: {ev['title']} in {h}h {m}m"

        text = (
            f"{color} <b>{arrow} SIGNAL — {symbol}</b> ({display_name})\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Entry:  <code>{entry}</code>\n"
            f"🔴 SL:     <code>{sl}</code>  (-{sl_dist} pts)\n"
            f"🟢 TP:     <code>{tp}</code>  (+{tp_dist} pts)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ R:R      {rr}\n"
            f"📊 QS:      {qs}/5\n"
            f"🎯 Regime:  {regime}{sent_score}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
            f"{next_event}"
        )

        sent = await self._send(text)

        if sent and session:
            await self._log_notification(session, "SIGNAL", symbol, text)

        return sent

    async def send_regime_change(
        self,
        old_regime: str,
        new_regime: str,
        reason: str,
        session: AsyncSession | None = None,
    ) -> bool:
        """Send a regime change notification."""
        if session and not await self._check_rate_limit(session, None, "REGIME_CHANGE"):
            return False

        icon = {"LONG": "🟢", "SHORT": "🔴", "NEUTRAL": "⚪"}.get(new_regime, "⚪")

        text = (
            f"🔄 <b>REGIME CHANGE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"From: {old_regime}\n"
            f"To:   {icon} <b>{new_regime}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Reason: {reason}"
        )

        sent = await self._send(text)

        if sent and session:
            await self._log_notification(session, "REGIME_CHANGE", None, text)

        return sent

    async def send_calendar_alert(
        self,
        event: dict,
        session: AsyncSession | None = None,
    ) -> bool:
        """Send a calendar event alert (event within 2 hours)."""
        if session and not await self._check_rate_limit(session, None, "CALENDAR"):
            return False

        hours = event.get("hours_away", 0)
        h = int(hours)
        m = int((hours - h) * 60)

        text = (
            f"📅 <b>CALENDAR ALERT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Event: {event.get('title', 'Unknown')}\n"
            f"Country: {event.get('country', '?')}\n"
            f"Impact: {event.get('impact', '?')}\n"
            f"Time: in {h}h {m}m\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Forecast: {event.get('forecast', 'N/A')}\n"
            f"Previous: {event.get('previous', 'N/A')}"
        )

        sent = await self._send(text)

        if sent and session:
            await self._log_notification(session, "CALENDAR", None, text)

        return sent

    async def send_monitor_status(
        self,
        symbol: str,
        status: str,
    ) -> bool:
        """Send monitor start/stop notification."""
        icon = "▶️" if status == "STARTED" else "⏹️"
        text = f"{icon} Monitor <b>{status}</b> — {symbol}"
        return await self._send(text)

    async def send_test(self) -> bool:
        """Send a test message to verify configuration."""
        text = (
            "✅ <b>Trading Copilot — Test</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Telegram notifications are working!\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        return await self._send(text)


def get_notifier(config: dict) -> TelegramNotifier:
    """Create a TelegramNotifier from config dict (in-memory cache)."""
    tg = config.get("telegram", {})
    return TelegramNotifier(
        bot_token=tg.get("bot_token", ""),
        chat_id=str(tg.get("chat_id", "")),
        enabled=tg.get("enabled", False),
    )


async def get_notifier_from_db(session_factory) -> TelegramNotifier:
    """Create a TelegramNotifier from database settings."""
    from app.models.database import get_telegram_config

    tg = await get_telegram_config(session_factory)
    return TelegramNotifier(
        bot_token=tg.get("bot_token", ""),
        chat_id=str(tg.get("chat_id", "")),
        enabled=tg.get("enabled", False),
    )
