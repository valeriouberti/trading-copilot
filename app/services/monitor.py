"""Background price monitor — split heavy/light architecture.

Uses APScheduler to run two types of jobs per monitored asset:

**Heavy analysis** (every 30 min, ~1 credit):
  Full pipeline via ``analyze_single_asset()`` — indicators, scoring,
  quality score, SL/TP.  Result is cached for 30 min.

**Light poll** (every 120 s, ~1 credit):
  Calls Twelve Data ``/price`` for a single quote, merges the fresh
  price into the cached heavy analysis, and re-runs signal detection.

Credit budget: 800/day free tier → ~256 credits/asset/day → max 3 assets.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import signal
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.models.database import MonitorSession, Signal
from app.services.analyzer import analyze_single_asset
from app.services.cache import AnalysisCache
from app.services.signal_detector import check_entry_conditions
from modules.data.credit_tracker import CreditTracker
from modules.data.twelvedata_provider import TwelveDataProvider

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

GRACEFUL_SHUTDOWN_TIMEOUT = 30  # seconds

# Scheduling defaults
HEAVY_INTERVAL = 1800  # 30 min
LIGHT_INTERVAL = 120   # 2 min
MAX_ASSETS = 3          # hard cap for free-tier budget


class AssetMonitor:
    """Manages background monitoring jobs for one or more assets."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.scheduler = AsyncIOScheduler()
        self._started = False
        self._drawdown_breaker = None
        self._cache = AnalysisCache()
        self._credit_tracker = CreditTracker()
        self._td_provider = TwelveDataProvider()
        self._active_symbols: set[str] = set()

    def _get_drawdown_breaker(self):
        """Lazy-init drawdown circuit breaker."""
        if self._drawdown_breaker is None:
            from modules.circuit_breaker_drawdown import DrawdownCircuitBreaker
            self._drawdown_breaker = DrawdownCircuitBreaker(
                self.app.state.session_factory,
            )
        return self._drawdown_breaker

    def ensure_running(self) -> None:
        """Start the scheduler if not already running."""
        if not self._started:
            self.scheduler.start()
            self._started = True

    async def start(self, symbol: str) -> dict:
        """Start monitoring an asset with heavy + light jobs.

        Returns the monitor status dict.
        """
        self.ensure_running()

        # Enforce asset cap
        if symbol not in self._active_symbols and len(self._active_symbols) >= MAX_ASSETS:
            return {
                "symbol": symbol,
                "status": "REJECTED",
                "reason": f"Max {MAX_ASSETS} assets (credit budget). "
                          f"Stop another asset first.",
            }

        heavy_id = f"heavy_{symbol}"
        light_id = f"light_{symbol}"

        # Remove existing jobs before re-adding
        for jid in (heavy_id, light_id):
            if self.scheduler.get_job(jid):
                self.scheduler.remove_job(jid)

        # Heavy analysis: every 30 min, run immediately on start
        self.scheduler.add_job(
            self._heavy_analysis,
            trigger="interval",
            seconds=HEAVY_INTERVAL,
            id=heavy_id,
            args=[symbol],
            replace_existing=True,
            max_instances=1,
            next_run_time=datetime.now(timezone.utc),  # run now
        )

        # Light poll: every 120 s (starts after a short delay to let heavy finish first)
        self.scheduler.add_job(
            self._light_poll,
            trigger="interval",
            seconds=LIGHT_INTERVAL,
            id=light_id,
            args=[symbol],
            replace_existing=True,
            max_instances=1,
        )

        self._active_symbols.add(symbol)

        # Persist to DB
        await self._upsert_session(symbol, LIGHT_INTERVAL, "ACTIVE")

        logger.info(
            "Monitor started: %s (heavy=%ds, light=%ds)",
            symbol, HEAVY_INTERVAL, LIGHT_INTERVAL,
        )
        return {
            "symbol": symbol,
            "status": "ACTIVE",
            "heavy_interval": HEAVY_INTERVAL,
            "light_interval": LIGHT_INTERVAL,
        }

    async def stop(self, symbol: str) -> dict:
        """Stop monitoring an asset."""
        for prefix in ("heavy_", "light_"):
            jid = f"{prefix}{symbol}"
            if self.scheduler.get_job(jid):
                self.scheduler.remove_job(jid)

        self._active_symbols.discard(symbol)
        self._cache.invalidate(symbol)

        await self._upsert_session(symbol, status="STOPPED")

        logger.info("Monitor stopped: %s", symbol)
        return {"symbol": symbol, "status": "STOPPED"}

    async def get_status(self) -> list[dict]:
        """Return status of all monitored assets."""
        session_factory = self.app.state.session_factory
        async with session_factory() as session:
            result = await session.execute(select(MonitorSession))
            rows = result.scalars().all()

        statuses = []
        for row in rows:
            light_job = self.scheduler.get_job(f"light_{row.symbol}")
            statuses.append({
                "symbol": row.symbol,
                "status": "ACTIVE" if light_job else row.status,
                "interval_seconds": row.interval_seconds,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "last_check": row.last_check.isoformat() if row.last_check else None,
                "last_price": row.last_price,
            })
        return statuses

    def get_budget(self) -> dict:
        """Return credit budget status."""
        stats = self._credit_tracker.stats()
        stats["active_assets"] = len(self._active_symbols)
        stats["max_assets"] = MAX_ASSETS
        stats["assets"] = sorted(self._active_symbols)
        return stats

    async def restore_from_db(self) -> None:
        """Restore ACTIVE monitors from the database (called at startup)."""
        session_factory = self.app.state.session_factory
        async with session_factory() as session:
            result = await session.execute(
                select(MonitorSession).where(MonitorSession.status == "ACTIVE")
            )
            rows = result.scalars().all()

        for row in rows:
            logger.info("Restoring monitor: %s", row.symbol)
            await self.start(row.symbol)

    async def shutdown(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._started:
            logger.info(
                "Shutting down monitor (waiting up to %ds for running jobs)...",
                GRACEFUL_SHUTDOWN_TIMEOUT,
            )
            self.scheduler.shutdown(wait=True)
            self._started = False
            logger.info("Monitor shutdown complete")

    def install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()

        def _handle_signal(sig: signal.Signals) -> None:
            logger.info("Received %s — initiating graceful shutdown", sig.name)
            loop.create_task(self.shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal, sig)
            except NotImplementedError:
                pass  # Windows

    # ─── Heavy analysis (full pipeline, every 30 min) ─────────────

    async def _heavy_analysis(self, symbol: str) -> None:
        """Run full analysis pipeline, cache the result."""
        if not self._credit_tracker.try_spend(1):
            logger.warning("Skipping heavy analysis for %s — budget exhausted", symbol)
            return

        try:
            config = self.app.state.config

            from app.models.database import get_all_assets
            assets = await get_all_assets(self.app.state.session_factory)
            asset = next(
                (a for a in assets if a["symbol"] == symbol),
                {"symbol": symbol, "display_name": symbol},
            )

            analysis = await analyze_single_asset(
                symbol=symbol,
                config=config,
                skip_polymarket=True,
                asset=asset,
            )

            # Cache the full analysis for 30 min
            self._cache.set(symbol, "heavy_analysis", analysis)

            # Extract SL/TP distances for price merging
            setup = analysis.get("setup", {})
            entry = setup.get("entry_price")
            sl = setup.get("stop_loss")
            tp = setup.get("take_profit")
            if entry and sl:
                self._cache.set(symbol, "sl_distance", abs(entry - sl), ttl=HEAVY_INTERVAL)
            if entry and tp:
                self._cache.set(symbol, "tp_distance", abs(entry - tp), ttl=HEAVY_INTERVAL)

            price = None
            if analysis.get("analysis") and analysis["analysis"].get("price"):
                price = analysis["analysis"]["price"].get("current")

            # Run signal detection on fresh analysis
            detection = check_entry_conditions(analysis)
            await self._update_check(symbol, price, detection)
            await self._handle_detection(symbol, price, analysis, detection)

            logger.info(
                "Heavy analysis done: %s price=%s credits_remaining=%d",
                symbol, price, self._credit_tracker.remaining,
            )

        except Exception as exc:
            self._handle_error(symbol, "heavy", exc)

    # ─── Light poll (quote only, every 120 s) ─────────────────────

    async def _light_poll(self, symbol: str) -> None:
        """Fetch latest price, merge into cached analysis, check signals."""
        cached = self._cache.get(symbol, "heavy_analysis")
        if cached is None:
            logger.debug("Light poll skipped for %s — no cached analysis yet", symbol)
            return

        if not self._credit_tracker.try_spend(1):
            logger.warning("Skipping light poll for %s — budget exhausted", symbol)
            return

        try:
            # Fetch just the price (1 credit)
            price = await asyncio.to_thread(self._td_provider.fetch_quote, symbol)
            if price is None:
                logger.debug("Light poll: no price returned for %s", symbol)
                return

            # Merge fresh price into a copy of the cached analysis
            merged = self._merge_price(cached, symbol, price)

            # Run signal detection on merged data
            detection = check_entry_conditions(merged)
            await self._update_check(symbol, price, detection)

            # Broadcast price update
            await self._broadcast_price(symbol, price, merged)

            # Handle signal if fired
            await self._handle_detection(symbol, price, merged, detection)

        except Exception as exc:
            self._handle_error(symbol, "light", exc)

    def _merge_price(self, cached: dict, symbol: str, price: float) -> dict:
        """Create a copy of cached analysis with the fresh price merged in.

        Updates:
        - analysis.price.current
        - setup.entry_price (set to current price)
        - setup.stop_loss / take_profit (recomputed from cached distances)
        """
        merged = copy.deepcopy(cached)

        # Update current price
        analysis = merged.get("analysis", {})
        price_data = analysis.get("price", {})
        price_data["current"] = price
        analysis["price"] = price_data
        merged["analysis"] = analysis

        # Update entry/SL/TP using cached distances
        setup = merged.get("setup", {})
        setup["entry_price"] = price

        sl_dist = self._cache.get(symbol, "sl_distance")
        tp_dist = self._cache.get(symbol, "tp_distance")
        direction = merged.get("regime", "NEUTRAL")

        if sl_dist:
            if direction == "LONG":
                setup["stop_loss"] = price - sl_dist
                if tp_dist:
                    setup["take_profit"] = price + tp_dist
            elif direction == "SHORT":
                setup["stop_loss"] = price + sl_dist
                if tp_dist:
                    setup["take_profit"] = price - tp_dist

        merged["setup"] = setup
        return merged

    # ─── Shared helpers ───────────────────────────────────────────

    async def _handle_detection(
        self, symbol: str, price: float | None, analysis: dict, detection: Any
    ) -> None:
        """If signal fired → check breaker → save → notify."""
        if not detection.fired:
            return

        breaker = self._get_drawdown_breaker()
        if await breaker.is_tripped():
            logger.warning(
                "SIGNAL BLOCKED by drawdown breaker: %s %s @ %s",
                symbol, detection.direction, detection.entry,
            )
            detection.fired = False
            detection.reason = "DRAWDOWN BREAKER: daily/weekly loss limit reached"
            await self._update_check(symbol, price, detection)
            return

        logger.info(
            "SIGNAL FIRED: %s %s @ %s",
            symbol, detection.direction, detection.entry,
        )

        await self._save_signal(detection, analysis)

        signal_msg = {
            "type": "signal",
            "symbol": symbol,
            "direction": detection.direction,
            "entry": detection.entry,
            "sl": detection.sl,
            "tp": detection.tp,
            "quality_score": detection.quality_score,
            "mtf": detection.mtf_alignment,
            "regime": detection.regime,
            "timestamp": detection.timestamp,
        }
        try:
            from app.api.websocket import broadcast
            await broadcast(signal_msg)
        except Exception as ws_exc:
            logger.warning("WebSocket broadcast failed: %s", ws_exc)

        try:
            await self._notify_telegram(symbol, analysis, detection)
        except Exception as tg_exc:
            logger.warning("Telegram notification failed: %s", tg_exc)

    async def _broadcast_price(self, symbol: str, price: float, analysis: dict) -> None:
        """Broadcast a price_update message via WebSocket."""
        from app.api.websocket import broadcast
        await broadcast({
            "type": "price_update",
            "symbol": symbol,
            "price": price,
            "change_pct": (
                analysis.get("analysis", {}).get("price", {}).get("change_pct")
            ),
            "regime": analysis.get("regime", "NEUTRAL"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _handle_error(self, symbol: str, job_type: str, exc: Exception) -> None:
        """Log errors from poll/analysis jobs."""
        from modules.exceptions import TransientError
        if isinstance(exc, TransientError):
            logger.warning("Monitor %s transient error for %s: %s", job_type, symbol, exc)
        else:
            logger.error(
                "Monitor %s failed for %s: %s", job_type, symbol, exc, exc_info=True
            )

    async def _upsert_session(
        self,
        symbol: str,
        interval_seconds: int | None = None,
        status: str = "ACTIVE",
    ) -> None:
        """Insert or update a MonitorSession row."""
        session_factory = self.app.state.session_factory
        async with session_factory() as session:
            result = await session.execute(
                select(MonitorSession).where(MonitorSession.symbol == symbol)
            )
            row = result.scalars().first()

            if row:
                values: dict = {"status": status}
                if interval_seconds is not None:
                    values["interval_seconds"] = interval_seconds
                if status == "ACTIVE":
                    values["started_at"] = datetime.now(timezone.utc)
                await session.execute(
                    update(MonitorSession)
                    .where(MonitorSession.symbol == symbol)
                    .values(**values)
                )
            else:
                row = MonitorSession(
                    symbol=symbol,
                    interval_seconds=interval_seconds or LIGHT_INTERVAL,
                    status=status,
                )
                session.add(row)

            await session.commit()

    async def _update_check(self, symbol: str, price: float | None, detection) -> None:
        """Update last_check and last_price in the MonitorSession."""
        session_factory = self.app.state.session_factory
        async with session_factory() as session:
            values: dict[str, Any] = {
                "last_check": datetime.now(timezone.utc),
            }
            if price is not None:
                values["last_price"] = price
            if detection:
                values["last_signal"] = json.dumps(detection.to_dict())

            await session.execute(
                update(MonitorSession)
                .where(MonitorSession.symbol == symbol)
                .values(**values)
            )
            await session.commit()

    async def _save_signal(self, detection, analysis: dict) -> None:
        """Persist a fired signal to the signals table."""
        session_factory = self.app.state.session_factory
        async with session_factory() as session:
            sentiment = analysis.get("sentiment") or {}
            technicals = analysis.get("analysis", {}).get("technicals", {})

            sig = Signal(
                timestamp=datetime.now(timezone.utc),
                symbol=detection.symbol,
                direction=detection.direction or "NEUTRAL",
                entry_price=detection.entry or 0,
                stop_loss=detection.sl or 0,
                take_profit=detection.tp or 0,
                quality_score=detection.quality_score,
                mtf_alignment=detection.mtf_alignment,
                regime=detection.regime,
                sentiment_score=sentiment.get("score"),
                composite_score=technicals.get("composite_score"),
                confidence_pct=technicals.get("confidence_pct"),
                session=detection.conditions[-3].detail.split("=")[1]
                if len(detection.conditions) >= 3
                else None,
            )
            session.add(sig)
            await session.commit()

    async def _notify_telegram(self, symbol: str, analysis: dict, detection) -> None:
        """Send signal to Telegram if configured."""
        try:
            from app.services.notifier import get_notifier_from_db

            session_factory = self.app.state.session_factory
            notifier = await get_notifier_from_db(session_factory)
            if not notifier.enabled:
                return
            async with session_factory() as db_session:
                await notifier.send_signal(
                    symbol=symbol,
                    display_name=analysis.get("display_name", symbol),
                    setup=analysis.get("setup", {}),
                    regime=analysis.get("regime", "NEUTRAL"),
                    regime_reason=analysis.get("regime_reason", ""),
                    sentiment=analysis.get("sentiment"),
                    calendar=analysis.get("calendar"),
                    session=db_session,
                )
        except Exception as exc:
            logger.error("Telegram notification failed for %s: %s", symbol, exc)
