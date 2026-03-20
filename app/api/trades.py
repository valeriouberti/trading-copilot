"""Trade journal & analytics API endpoints."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select, update

from app.models.database import Signal, Trade
from app.models.engine import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────

class TradeCreate(BaseModel):
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    quality_score: int = 0
    regime: Optional[str] = None
    sentiment_score: Optional[float] = None
    notes: Optional[str] = None
    signal_id: Optional[int] = None


class TradeUpdate(BaseModel):
    exit_price: Optional[float] = None
    outcome_pips: Optional[float] = None
    r_multiple: Optional[float] = None
    notes: Optional[str] = None


class SignalOutcome(BaseModel):
    outcome: str  # TP_HIT, SL_HIT, MANUAL
    outcome_price: Optional[float] = None


# ── Trade CRUD ────────────────────────────────────────────────

@router.get("/trades")
async def list_trades(
    request: Request,
    symbol: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    quality_score: Optional[int] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    """List trades with optional filters."""
    async for session in get_db(request):
        stmt = select(Trade).order_by(desc(Trade.timestamp))

        if symbol:
            stmt = stmt.where(Trade.symbol == symbol)
        if direction:
            stmt = stmt.where(Trade.direction == direction.upper())
        if quality_score is not None:
            stmt = stmt.where(Trade.quality_score == quality_score)

        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()

        # Also get total count for pagination
        count_stmt = select(func.count(Trade.id))
        if symbol:
            count_stmt = count_stmt.where(Trade.symbol == symbol)
        if direction:
            count_stmt = count_stmt.where(Trade.direction == direction.upper())
        if quality_score is not None:
            count_stmt = count_stmt.where(Trade.quality_score == quality_score)
        total = (await session.execute(count_stmt)).scalar() or 0

        return {
            "trades": [_trade_to_dict(t) for t in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.post("/trades", status_code=201)
async def create_trade(request: Request, body: TradeCreate):
    """Record a new trade."""
    async for session in get_db(request):
        # Auto-compute outcome if exit_price provided
        outcome_pips = 0.0
        r_multiple = 0.0
        if body.exit_price is not None:
            if body.direction.upper() == "LONG":
                outcome_pips = body.exit_price - body.entry_price
            else:
                outcome_pips = body.entry_price - body.exit_price

            if body.stop_loss:
                sl_dist = abs(body.entry_price - body.stop_loss)
                if sl_dist > 0:
                    r_multiple = round(outcome_pips / sl_dist, 2)

        trade = Trade(
            signal_id=body.signal_id,
            timestamp=datetime.now(timezone.utc),
            symbol=body.symbol.upper(),
            direction=body.direction.upper(),
            entry_price=body.entry_price,
            exit_price=body.exit_price,
            stop_loss=body.stop_loss,
            take_profit=body.take_profit,
            quality_score=body.quality_score,
            regime=body.regime,
            sentiment_score=body.sentiment_score,
            outcome_pips=round(outcome_pips, 2),
            r_multiple=r_multiple,
            notes=body.notes,
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)
        return _trade_to_dict(trade)


@router.put("/trades/{trade_id}")
async def update_trade(request: Request, trade_id: int, body: TradeUpdate):
    """Update an existing trade (typically to close it with exit_price)."""
    async for session in get_db(request):
        result = await session.execute(select(Trade).where(Trade.id == trade_id))
        trade = result.scalars().first()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")

        if body.exit_price is not None:
            trade.exit_price = body.exit_price
            if trade.direction == "LONG":
                trade.outcome_pips = round(body.exit_price - trade.entry_price, 2)
            else:
                trade.outcome_pips = round(trade.entry_price - body.exit_price, 2)
            if trade.stop_loss:
                sl_dist = abs(trade.entry_price - trade.stop_loss)
                if sl_dist > 0:
                    trade.r_multiple = round(trade.outcome_pips / sl_dist, 2)

        if body.outcome_pips is not None:
            trade.outcome_pips = body.outcome_pips
        if body.r_multiple is not None:
            trade.r_multiple = body.r_multiple
        if body.notes is not None:
            trade.notes = body.notes

        await session.commit()
        await session.refresh(trade)
        return _trade_to_dict(trade)


@router.delete("/trades/{trade_id}")
async def delete_trade(request: Request, trade_id: int):
    """Delete a trade by ID."""
    async for session in get_db(request):
        result = await session.execute(select(Trade).where(Trade.id == trade_id))
        trade = result.scalars().first()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")

        await session.delete(trade)
        await session.commit()
        return {"message": "Trade deleted", "id": trade_id}


# ── Analytics ─────────────────────────────────────────────────

@router.get("/trades/analytics")
async def trade_analytics(request: Request):
    """Compute performance analytics across all trades."""
    async for session in get_db(request):
        result = await session.execute(
            select(Trade).where(Trade.exit_price.isnot(None)).order_by(Trade.timestamp)
        )
        trades = result.scalars().all()

        if not trades:
            return {"message": "No closed trades yet", "total_trades": 0}

        wins = [t for t in trades if t.outcome_pips and t.outcome_pips > 0]
        losses = [t for t in trades if t.outcome_pips and t.outcome_pips <= 0]

        total = len(trades)
        win_count = len(wins)
        win_rate = round(win_count / total * 100, 1) if total else 0

        gross_profit = sum(t.outcome_pips for t in wins) if wins else 0
        gross_loss = abs(sum(t.outcome_pips for t in losses)) if losses else 0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

        r_multiples = [t.r_multiple for t in trades if t.r_multiple is not None]
        avg_r = round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0

        # Max drawdown (cumulative P&L)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        equity_curve = []
        for t in trades:
            cumulative += t.outcome_pips or 0
            equity_curve.append({
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                "cumulative_pnl": round(cumulative, 2),
                "symbol": t.symbol,
            })
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        best = max(trades, key=lambda t: t.outcome_pips or 0)
        worst = min(trades, key=lambda t: t.outcome_pips or 0)

        # Breakdowns
        by_regime = _breakdown(trades, "regime")
        by_qs = _breakdown_qs(trades)
        by_direction = _breakdown(trades, "direction")
        by_symbol = _breakdown(trades, "symbol")

        # Rolling win rate (last 20 trades)
        rolling = []
        for i in range(len(trades)):
            window = trades[max(0, i - 19):i + 1]
            w = sum(1 for t in window if t.outcome_pips and t.outcome_pips > 0)
            rolling.append({
                "index": i + 1,
                "win_rate": round(w / len(window) * 100, 1),
                "timestamp": trades[i].timestamp.isoformat() if trades[i].timestamp else None,
            })

        # R-multiple distribution buckets
        r_dist = {"< -2": 0, "-2 to -1": 0, "-1 to 0": 0, "0 to 1": 0, "1 to 2": 0, "> 2": 0}
        for r in r_multiples:
            if r < -2:
                r_dist["< -2"] += 1
            elif r < -1:
                r_dist["-2 to -1"] += 1
            elif r < 0:
                r_dist["-1 to 0"] += 1
            elif r < 1:
                r_dist["0 to 1"] += 1
            elif r < 2:
                r_dist["1 to 2"] += 1
            else:
                r_dist["> 2"] += 1

        # Insights
        insights = _generate_insights(trades, wins, losses, by_regime, by_qs, by_direction)

        return {
            "total_trades": total,
            "win_count": win_count,
            "loss_count": len(losses),
            "win_rate": win_rate,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "net_pnl": round(gross_profit - gross_loss, 2),
            "profit_factor": profit_factor,
            "avg_r_multiple": avg_r,
            "max_drawdown": round(max_dd, 2),
            "best_trade": _trade_to_dict(best),
            "worst_trade": _trade_to_dict(worst),
            "by_regime": by_regime,
            "by_quality_score": by_qs,
            "by_direction": by_direction,
            "by_symbol": by_symbol,
            "equity_curve": equity_curve,
            "rolling_win_rate": rolling,
            "r_distribution": r_dist,
            "insights": insights,
        }


# ── Signal history ────────────────────────────────────────────

@router.get("/signals")
async def list_signals(
    request: Request,
    symbol: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    """List generated signals with optional filters."""
    async for session in get_db(request):
        stmt = select(Signal).order_by(desc(Signal.timestamp))

        if symbol:
            stmt = stmt.where(Signal.symbol == symbol)
        if direction:
            stmt = stmt.where(Signal.direction == direction.upper())
        if outcome:
            stmt = stmt.where(Signal.outcome == outcome.upper())

        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()

        count_stmt = select(func.count(Signal.id))
        if symbol:
            count_stmt = count_stmt.where(Signal.symbol == symbol)
        if direction:
            count_stmt = count_stmt.where(Signal.direction == direction.upper())
        if outcome:
            count_stmt = count_stmt.where(Signal.outcome == outcome.upper())
        total = (await session.execute(count_stmt)).scalar() or 0

        return {
            "signals": [_signal_to_dict(s) for s in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.put("/signals/{signal_id}/outcome")
async def update_signal_outcome(request: Request, signal_id: int, body: SignalOutcome):
    """Update the outcome of a signal (TP_HIT, SL_HIT, MANUAL)."""
    async for session in get_db(request):
        result = await session.execute(select(Signal).where(Signal.id == signal_id))
        sig = result.scalars().first()
        if not sig:
            raise HTTPException(status_code=404, detail="Signal not found")

        sig.outcome = body.outcome.upper()
        if body.outcome_price is not None:
            sig.outcome_price = body.outcome_price
            if sig.direction == "LONG":
                sig.outcome_pips = round(body.outcome_price - sig.entry_price, 2)
            else:
                sig.outcome_pips = round(sig.entry_price - body.outcome_price, 2)

        await session.commit()
        return _signal_to_dict(sig)


@router.get("/signals/analytics")
async def signal_analytics(request: Request):
    """Compute theoretical win rate of all generated signals."""
    async for session in get_db(request):
        result = await session.execute(select(Signal).order_by(Signal.timestamp))
        signals = result.scalars().all()

        total = len(signals)
        resolved = [s for s in signals if s.outcome in ("TP_HIT", "SL_HIT")]
        pending = [s for s in signals if s.outcome == "PENDING"]

        tp_hits = [s for s in resolved if s.outcome == "TP_HIT"]
        sl_hits = [s for s in resolved if s.outcome == "SL_HIT"]

        theoretical_wr = (
            round(len(tp_hits) / len(resolved) * 100, 1) if resolved else 0
        )

        return {
            "total_signals": total,
            "resolved": len(resolved),
            "pending": len(pending),
            "tp_hits": len(tp_hits),
            "sl_hits": len(sl_hits),
            "theoretical_win_rate": theoretical_wr,
        }


@router.post("/trades/import-csv")
async def import_csv(request: Request):
    """Import trades from trade_log.csv into the database."""
    import os
    csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "trade_log.csv")
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="trade_log.csv not found")

    imported = 0
    async for session in get_db(request):
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    trade = Trade(
                        timestamp=datetime.fromisoformat(row.get("timestamp", datetime.now(timezone.utc).isoformat())),
                        symbol=row.get("symbol", "UNKNOWN"),
                        direction=row.get("direction", "LONG"),
                        entry_price=float(row.get("entry_price", 0)),
                        exit_price=float(row["exit_price"]) if row.get("exit_price") else None,
                        stop_loss=float(row["stop_loss"]) if row.get("stop_loss") else None,
                        take_profit=float(row["take_profit"]) if row.get("take_profit") else None,
                        quality_score=int(row.get("quality_score", 0)),
                        regime=row.get("regime"),
                        outcome_pips=float(row.get("outcome_pips", 0)),
                        r_multiple=float(row.get("r_multiple", 0)),
                        notes=row.get("notes", ""),
                    )
                    session.add(trade)
                    imported += 1
                except (ValueError, KeyError) as exc:
                    logger.warning("Skipping CSV row: %s", exc)

        await session.commit()

    return {"imported": imported, "source": csv_path}


# ── Helpers ───────────────────────────────────────────────────

def _trade_to_dict(t: Trade) -> dict:
    return {
        "id": t.id,
        "signal_id": t.signal_id,
        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
        "symbol": t.symbol,
        "direction": t.direction,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "stop_loss": t.stop_loss,
        "take_profit": t.take_profit,
        "quality_score": t.quality_score,
        "regime": t.regime,
        "sentiment_score": t.sentiment_score,
        "outcome_pips": t.outcome_pips,
        "r_multiple": t.r_multiple,
        "notes": t.notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _signal_to_dict(s: Signal) -> dict:
    return {
        "id": s.id,
        "timestamp": s.timestamp.isoformat() if s.timestamp else None,
        "symbol": s.symbol,
        "direction": s.direction,
        "entry_price": s.entry_price,
        "stop_loss": s.stop_loss,
        "take_profit": s.take_profit,
        "quality_score": s.quality_score,
        "mtf_alignment": s.mtf_alignment,
        "regime": s.regime,
        "sentiment_score": s.sentiment_score,
        "composite_score": s.composite_score,
        "confidence_pct": s.confidence_pct,
        "session": s.session,
        "outcome": s.outcome,
        "outcome_price": s.outcome_price,
        "outcome_pips": s.outcome_pips,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _breakdown(trades: list[Trade], field: str) -> dict:
    """Compute win rate breakdown by a given field."""
    groups: dict[str, list] = {}
    for t in trades:
        key = getattr(t, field, None) or "N/A"
        groups.setdefault(key, []).append(t)

    result = {}
    for key, group in groups.items():
        total = len(group)
        wins = sum(1 for t in group if t.outcome_pips and t.outcome_pips > 0)
        result[key] = {
            "total": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "avg_pips": round(sum(t.outcome_pips or 0 for t in group) / total, 2) if total else 0,
        }
    return result


def _breakdown_qs(trades: list[Trade]) -> dict:
    """Win rate breakdown by quality score."""
    groups: dict[int, list] = {}
    for t in trades:
        qs = t.quality_score or 0
        groups.setdefault(qs, []).append(t)

    result = {}
    for qs, group in sorted(groups.items()):
        total = len(group)
        wins = sum(1 for t in group if t.outcome_pips and t.outcome_pips > 0)
        result[f"QS {qs}"] = {
            "total": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total else 0,
        }
    return result


def _generate_insights(
    trades: list, wins: list, losses: list,
    by_regime: dict, by_qs: dict, by_direction: dict,
) -> list[str]:
    """Generate automatic insights from trade data."""
    insights = []

    # QS comparison
    qs_keys = sorted(by_qs.keys())
    if len(qs_keys) >= 2:
        best_qs = max(qs_keys, key=lambda k: by_qs[k]["win_rate"])
        worst_qs = min(qs_keys, key=lambda k: by_qs[k]["win_rate"])
        if by_qs[best_qs]["win_rate"] > by_qs[worst_qs]["win_rate"] + 10:
            insights.append(
                f"Trades with {best_qs} have {by_qs[best_qs]['win_rate']}% win rate "
                f"vs {by_qs[worst_qs]['win_rate']}% with {worst_qs}"
            )

    # Regime comparison
    for regime, stats in by_regime.items():
        if stats["total"] >= 5 and stats["win_rate"] >= 65:
            insights.append(
                f"{regime} regime trades: {stats['win_rate']}% win rate ({stats['total']} trades)"
            )

    # Direction comparison
    if "LONG" in by_direction and "SHORT" in by_direction:
        long_wr = by_direction["LONG"]["win_rate"]
        short_wr = by_direction["SHORT"]["win_rate"]
        if abs(long_wr - short_wr) > 15:
            better = "LONG" if long_wr > short_wr else "SHORT"
            insights.append(
                f"{better} trades outperform: {max(long_wr, short_wr)}% vs {min(long_wr, short_wr)}%"
            )

    if not insights:
        insights.append("Not enough data for insights yet (need more closed trades)")

    return insights
