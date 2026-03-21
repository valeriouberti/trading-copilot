"""ETF Swing Trader — cron-based scheduler.

Replaces the old 2-minute Twelve Data polling with three daily cron jobs
running in the Europe/Rome timezone:

  08:00  morning_briefing  — full analysis of all 8 ETFs, rank, Telegram briefing
  13:00  midday_check      — check open positions (price vs SL/TP, max hold)
  17:00  closing_check     — position check + end-of-day summary

On startup the scheduler checks if today's morning briefing was missed
(no NotificationLog entry) and runs it immediately if before 17:30 CET.
"""

from __future__ import annotations

import asyncio
import logging
import math
import signal
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.models.database import (
    NotificationLog,
    Position,
    Signal,
    get_all_assets,
    get_open_positions,
)
from app.services.analyzer import analyze_single_asset
from app.services.signal_detector import check_entry_conditions

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")
GRACEFUL_SHUTDOWN_TIMEOUT = 30


class ETFScheduler:
    """Manages the three daily cron jobs for ETF swing trading."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.scheduler = AsyncIOScheduler(timezone=ROME_TZ)
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register cron jobs and start the scheduler."""
        if self._started:
            return

        self.scheduler.add_job(
            self._morning_briefing,
            CronTrigger(hour=8, minute=0, timezone=ROME_TZ),
            id="morning_briefing",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.add_job(
            self._position_check,
            CronTrigger(hour=13, minute=0, timezone=ROME_TZ),
            id="midday_check",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.add_job(
            self._position_check,
            CronTrigger(hour=17, minute=0, timezone=ROME_TZ),
            id="closing_check",
            replace_existing=True,
            max_instances=1,
        )

        self.scheduler.start()
        self._started = True
        logger.info("ETF Scheduler started — jobs at 08:00 / 13:00 / 17:00 CET")

    async def startup_catchup(self) -> None:
        """If the morning briefing was missed today, run it now (before 17:30)."""
        now_rome = datetime.now(ROME_TZ)

        # Only catch up between 08:00 and 17:30
        if now_rome.hour < 8 or (now_rome.hour >= 17 and now_rome.minute > 30):
            return

        # Check if we already sent a briefing today
        session_factory = self.app.state.session_factory
        today_start = now_rome.replace(hour=0, minute=0, second=0, microsecond=0)
        async with session_factory() as session:
            result = await session.execute(
                select(NotificationLog).where(
                    NotificationLog.type == "DAILY_BRIEFING",
                    NotificationLog.timestamp >= today_start,
                )
            )
            existing = result.scalars().first()

        if existing is None:
            logger.info("Morning briefing missed today — running catch-up (technicals only)")
            await self._morning_briefing(skip_llm=True, skip_polymarket=True)

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
            logger.info("ETF Scheduler stopped")

    async def shutdown(self) -> None:
        """Graceful async shutdown."""
        self.stop()

    def install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()

        def _handle(sig: signal.Signals) -> None:
            logger.info("Received %s — shutting down scheduler", sig.name)
            loop.create_task(self.shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle, sig)
            except NotImplementedError:
                pass  # Windows

    def get_schedule(self) -> list[dict[str, str]]:
        """Return scheduled job info for the API."""
        jobs = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "next_run": next_run.isoformat() if next_run else "paused",
            })
        return jobs

    # ------------------------------------------------------------------
    # Public trigger (for "Analyze Now" button / API)
    # ------------------------------------------------------------------

    async def run_morning_briefing(self) -> dict[str, Any]:
        """Run the morning briefing on demand. Returns the briefing data."""
        return await self._morning_briefing()

    # ------------------------------------------------------------------
    # Morning briefing (08:00 CET)
    # ------------------------------------------------------------------

    async def _morning_briefing(self, skip_llm: bool = False, skip_polymarket: bool = False) -> dict[str, Any]:
        """Analyze all ETFs, rank, send Telegram daily briefing."""
        logger.info("=== MORNING BRIEFING START (skip_llm=%s, skip_poly=%s) ===", skip_llm, skip_polymarket)
        config = self.app.state.config
        session_factory = self.app.state.session_factory

        assets = await get_all_assets(session_factory)
        if not assets:
            logger.warning("No assets configured — skipping briefing")
            return {"status": "no_assets"}

        analyses = await self._analyze_all(assets, config, skip_llm=skip_llm, skip_polymarket=skip_polymarket)

        # Classify each: BUY / SELL_IF_HOLDING / HOLD
        buy_signals: list[dict] = []
        sell_signals: list[dict] = []
        hold_signals: list[dict] = []

        for a in analyses:
            regime = a.get("regime", "NEUTRAL")
            setup = a.get("setup", {})
            detection = check_entry_conditions(a)
            symbol = a.get("symbol", "?")

            if detection.fired and regime == "LONG":
                buy_signals.append({
                    "symbol": symbol,
                    "display_name": a.get("display_name", symbol),
                    "quality_score": setup.get("quality_score", 0),
                    "entry_price": setup.get("entry_price"),
                    "stop_loss": setup.get("stop_loss"),
                    "take_profit": setup.get("take_profit"),
                    "regime": regime,
                    "risk_reward": setup.get("risk_reward", "1:2.0"),
                })
            elif regime in ("SHORT", "BEARISH"):
                sell_signals.append({
                    "symbol": symbol,
                    "display_name": a.get("display_name", symbol),
                    "reason": a.get("regime_reason", "Bearish momentum"),
                })
            else:
                hold_signals.append({
                    "symbol": symbol,
                    "display_name": a.get("display_name", symbol),
                })

        # Rank BUY signals by quality score descending
        buy_signals.sort(key=lambda x: x.get("quality_score", 0), reverse=True)

        # Get open positions
        open_positions = await get_open_positions(session_factory)

        # Send Telegram briefing
        briefing_data = {
            "buy": buy_signals,
            "sell": sell_signals,
            "hold": hold_signals,
            "open_positions": open_positions,
            "analyses": analyses,
        }

        await self._send_daily_briefing(briefing_data)

        # Save signals to DB for BUY entries
        for sig in buy_signals:
            await self._save_buy_signal(sig, analyses)

        logger.info(
            "=== MORNING BRIEFING DONE === BUY:%d SELL:%d HOLD:%d",
            len(buy_signals), len(sell_signals), len(hold_signals),
        )
        return briefing_data

    # ------------------------------------------------------------------
    # Position check (13:00, 17:00 CET)
    # ------------------------------------------------------------------

    async def _position_check(self) -> None:
        """Check open positions: price vs SL/TP, max hold days."""
        logger.info("=== POSITION CHECK START ===")
        session_factory = self.app.state.session_factory
        positions = await get_open_positions(session_factory)

        if not positions:
            logger.info("No open positions to check")
            return

        from modules.strategy import MAX_HOLD_DAYS, should_force_exit

        for pos in positions:
            symbol = pos["symbol"]
            try:
                current_price = await self._fetch_current_price(symbol)
                if current_price is None:
                    continue

                entry_price = pos["entry_price"]
                sl = pos.get("stop_loss")
                tp = pos.get("take_profit")
                entry_date = datetime.fromisoformat(pos["entry_date"])
                now = datetime.now(timezone.utc)

                reason = None

                # Check stop loss
                if sl and current_price <= sl:
                    reason = f"Stop-loss hit ({current_price:.2f} <= {sl:.2f})"

                # Check take profit
                elif tp and current_price >= tp:
                    reason = f"Take-profit reached ({current_price:.2f} >= {tp:.2f})"

                # Check max hold period
                elif should_force_exit(entry_date, now):
                    days = (now - entry_date).days
                    reason = f"Max hold exceeded ({days}/{MAX_HOLD_DAYS} days)"

                if reason:
                    await self._send_sell_alert(pos, current_price, reason)
                    logger.info("SELL ALERT: %s — %s", symbol, reason)

            except Exception as exc:
                logger.error("Position check failed for %s: %s", symbol, exc)

        logger.info("=== POSITION CHECK DONE ===")

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    async def _analyze_all(
        self, assets: list[dict], config: dict,
        skip_llm: bool = False,
        skip_polymarket: bool = False,
    ) -> list[dict[str, Any]]:
        """Run analyze_single_asset for all ETFs in parallel.

        Args:
            skip_llm: If True, skip LLM sentiment calls (technicals only).
            skip_polymarket: If True, skip Polymarket data fetch + LLM classification.
        """
        tasks = [
            analyze_single_asset(
                symbol=asset["symbol"],
                config=config,
                asset=asset,
                skip_llm=skip_llm,
                skip_polymarket=skip_polymarket,
            )
            for asset in assets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        analyses: list[dict[str, Any]] = []
        for asset, result in zip(assets, results):
            if isinstance(result, Exception):
                logger.error("Analysis failed for %s: %s", asset["symbol"], result)
                continue
            analyses.append(result)
        return analyses

    async def _fetch_current_price(self, symbol: str) -> float | None:
        """Fetch the latest price for a symbol via yfinance."""
        try:
            import yfinance as yf

            ticker = await asyncio.to_thread(yf.Ticker, symbol)
            info = await asyncio.to_thread(lambda: ticker.fast_info)
            price = getattr(info, "last_price", None)
            if price is None:
                price = getattr(info, "previous_close", None)
            return float(price) if price else None
        except Exception as exc:
            logger.warning("Price fetch failed for %s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Signal persistence
    # ------------------------------------------------------------------

    async def _save_buy_signal(self, sig: dict, analyses: list[dict]) -> None:
        """Save a BUY signal to the signals table."""
        session_factory = self.app.state.session_factory

        # Find matching analysis for sentiment data
        analysis = next(
            (a for a in analyses if a.get("symbol") == sig["symbol"]),
            {},
        )
        sentiment = analysis.get("sentiment") or {}
        technicals = analysis.get("analysis", {}).get("technicals", {})

        async with session_factory() as session:
            db_signal = Signal(
                timestamp=datetime.now(timezone.utc),
                symbol=sig["symbol"],
                direction="LONG",
                entry_price=sig.get("entry_price") or 0,
                stop_loss=sig.get("stop_loss") or 0,
                take_profit=sig.get("take_profit") or 0,
                quality_score=sig.get("quality_score", 0),
                regime="LONG",
                sentiment_score=sentiment.get("score"),
                composite_score=technicals.get("composite_score"),
                confidence_pct=technicals.get("confidence_pct"),
            )
            session.add(db_signal)
            await session.commit()

    # ------------------------------------------------------------------
    # Telegram notifications
    # ------------------------------------------------------------------

    async def _get_notifier(self):
        """Get the TelegramNotifier from DB settings."""
        from app.services.notifier import get_notifier_from_db
        return await get_notifier_from_db(self.app.state.session_factory)

    async def _send_daily_briefing(self, briefing: dict) -> None:
        """Format and send the daily ETF briefing via Telegram."""
        try:
            notifier = await self._get_notifier()
            if not notifier.enabled:
                return

            today = datetime.now(ROME_TZ).strftime("%d %b %Y")
            lines = [f"<b>DAILY ETF BRIEFING — {today}</b>", "━━━━━━━━━━━━━━━━━━━━━━"]

            # BUY signals
            buy = briefing.get("buy", [])
            if buy:
                lines.append("\n<b>BUY:</b>")
                for i, s in enumerate(buy, 1):
                    entry = s.get("entry_price")
                    sl = s.get("stop_loss")
                    tp = s.get("take_profit")
                    qs = s.get("quality_score", 0)
                    rr = s.get("risk_reward", "1:2.0")

                    sl_pct = abs((sl - entry) / entry * 100) if entry and sl else 0
                    tp_pct = abs((tp - entry) / entry * 100) if entry and tp else 0

                    lines.append(
                        f"{i}. <b>{s['symbol']}</b> ({s['display_name']}) — QS {qs}/5\n"
                        f"   Entry ~{entry:.2f} | SL {sl:.2f} (-{sl_pct:.1f}%) | TP {tp:.2f} (+{tp_pct:.1f}%)\n"
                        f"   R:R {rr} | Regime: LONG"
                    )

                    # Position size hint
                    if entry and entry > 0:
                        shares = math.floor(1500.0 / entry)
                        lines.append(f"   ~{shares} shares at €{entry:.2f} (€1,500)")
            else:
                lines.append("\n<b>BUY:</b> None today")

            # SELL IF HOLDING
            sell = briefing.get("sell", [])
            if sell:
                lines.append("\n<b>SELL IF HOLDING:</b>")
                for s in sell:
                    lines.append(f"  {s['symbol']} — {s.get('reason', 'bearish momentum')}")

            # HOLD
            hold = briefing.get("hold", [])
            if hold:
                syms = ", ".join(s["symbol"] for s in hold)
                lines.append(f"\n<b>HOLD (no action):</b>\n  {syms}")

            # Open positions
            positions = briefing.get("open_positions", [])
            max_pos = 2
            lines.append(f"\n<b>Open positions: {len(positions)}/{max_pos}</b>")
            if positions:
                for p in positions:
                    entry_date = p.get("entry_date", "")
                    days = 0
                    if entry_date:
                        try:
                            ed = datetime.fromisoformat(entry_date)
                            days = (datetime.now(timezone.utc) - ed).days
                        except (ValueError, TypeError):
                            pass
                    lines.append(f"  {p['symbol']}: entry {p['entry_price']:.2f} (day {days}/10)")

            text = "\n".join(lines)
            await notifier._send(text)

            # Log the notification
            session_factory = self.app.state.session_factory
            async with session_factory() as session:
                session.add(NotificationLog(
                    type="DAILY_BRIEFING",
                    message=text[:500],
                    channel="TELEGRAM",
                ))
                await session.commit()

        except Exception as exc:
            logger.error("Failed to send daily briefing: %s", exc)

    async def _send_sell_alert(
        self, position: dict, current_price: float, reason: str
    ) -> None:
        """Send a SELL alert for an open position."""
        try:
            notifier = await self._get_notifier()
            if not notifier.enabled:
                return

            entry = position["entry_price"]
            shares = position.get("shares", 0)
            pnl = (current_price - entry) * shares - 5.90  # round-trip commission
            pnl_pct = ((current_price - entry) / entry * 100) if entry else 0

            entry_date = position.get("entry_date", "")
            days = 0
            if entry_date:
                try:
                    ed = datetime.fromisoformat(entry_date)
                    days = (datetime.now(timezone.utc) - ed).days
                except (ValueError, TypeError):
                    pass

            text = (
                f"🔔 <b>SELL ALERT — {position['symbol']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Reason: {reason}\n"
                f"Entry: {entry:.2f} | Current: {current_price:.2f}\n"
                f"P&amp;L: {pnl:+.2f} EUR ({pnl_pct:+.1f}%) — {days} days held\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Action: Close on Fineco</b>"
            )

            await notifier._send(text)

            session_factory = self.app.state.session_factory
            async with session_factory() as session:
                session.add(NotificationLog(
                    type="SELL_ALERT",
                    symbol=position["symbol"],
                    message=text[:500],
                    channel="TELEGRAM",
                ))
                await session.commit()

        except Exception as exc:
            logger.error("Failed to send sell alert: %s", exc)
