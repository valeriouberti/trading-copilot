"""Background price monitor — polls assets and triggers signal detection.

Uses APScheduler to run periodic jobs.  Each monitored asset gets its own
job that:
  1. Runs the full analysis pipeline (via analyzer.py)
  2. Passes the result to the signal detector
  3. If a signal fires → broadcasts via WebSocket + Telegram
  4. Persists state in the MonitorSession table

The monitor is a singleton bound to the FastAPI app.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.models.database import MonitorSession, Signal
from app.services.analyzer import analyze_single_asset
from app.services.signal_detector import check_entry_conditions

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class AssetMonitor:
    """Manages background monitoring jobs for one or more assets."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.scheduler = AsyncIOScheduler()
        self._started = False

    def ensure_running(self) -> None:
        """Start the scheduler if not already running."""
        if not self._started:
            self.scheduler.start()
            self._started = True

    async def start(self, symbol: str, interval_seconds: int = 60) -> dict:
        """Start monitoring an asset.

        Returns the monitor status dict.
        """
        self.ensure_running()

        job_id = f"monitor_{symbol}"

        # If already running, update interval
        existing = self.scheduler.get_job(job_id)
        if existing:
            self.scheduler.reschedule_job(
                job_id, trigger="interval", seconds=interval_seconds
            )
        else:
            self.scheduler.add_job(
                self._poll_asset,
                trigger="interval",
                seconds=interval_seconds,
                id=job_id,
                args=[symbol],
                replace_existing=True,
                max_instances=1,
            )

        # Persist to DB
        await self._upsert_session(symbol, interval_seconds, "ACTIVE")

        logger.info("Monitor started: %s every %ds", symbol, interval_seconds)
        return {"symbol": symbol, "status": "ACTIVE", "interval": interval_seconds}

    async def stop(self, symbol: str) -> dict:
        """Stop monitoring an asset."""
        job_id = f"monitor_{symbol}"
        job = self.scheduler.get_job(job_id)
        if job:
            self.scheduler.remove_job(job_id)

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
            job = self.scheduler.get_job(f"monitor_{row.symbol}")
            statuses.append({
                "symbol": row.symbol,
                "status": "ACTIVE" if job else row.status,
                "interval_seconds": row.interval_seconds,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "last_check": row.last_check.isoformat() if row.last_check else None,
                "last_price": row.last_price,
            })
        return statuses

    async def restore_from_db(self) -> None:
        """Restore ACTIVE monitors from the database (called at startup)."""
        session_factory = self.app.state.session_factory
        async with session_factory() as session:
            result = await session.execute(
                select(MonitorSession).where(MonitorSession.status == "ACTIVE")
            )
            rows = result.scalars().all()

        for row in rows:
            logger.info("Restoring monitor: %s (every %ds)", row.symbol, row.interval_seconds)
            await self.start(row.symbol, row.interval_seconds)

    async def shutdown(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False

    # ─── Internal ─────────────────────────────────────────────────

    async def _poll_asset(self, symbol: str) -> None:
        """Single poll cycle for one asset."""
        try:
            config = self.app.state.config

            # Run full analysis
            analysis = await analyze_single_asset(
                symbol=symbol,
                config=config,
                skip_polymarket=True,  # skip for speed on frequent polls
            )

            price = None
            if analysis.get("analysis") and analysis["analysis"].get("price"):
                price = analysis["analysis"]["price"].get("current")

            # Run signal detection
            detection = check_entry_conditions(analysis)

            # Update DB state
            await self._update_check(symbol, price, detection)

            # Broadcast price update via WebSocket
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

            # If signal fired → broadcast + Telegram
            if detection.fired:
                logger.info(
                    "SIGNAL FIRED: %s %s @ %s",
                    symbol, detection.direction, detection.entry,
                )

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
                await broadcast(signal_msg)

                # Persist signal to DB
                await self._save_signal(detection, analysis)

                # Send Telegram notification
                await self._notify_telegram(symbol, analysis, detection)

        except Exception as exc:
            logger.error("Monitor poll failed for %s: %s", symbol, exc, exc_info=True)

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
                    interval_seconds=interval_seconds or 60,
                    status=status,
                )
                session.add(row)

            await session.commit()

    async def _update_check(self, symbol: str, price: float | None, detection) -> None:
        """Update last_check and last_price in the MonitorSession."""
        session_factory = self.app.state.session_factory
        async with session_factory() as session:
            values = {
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
            from app.services.notifier import get_notifier

            config = self.app.state.config
            notifier = get_notifier(config)
            if not notifier.enabled:
                return

            session_factory = self.app.state.session_factory
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
