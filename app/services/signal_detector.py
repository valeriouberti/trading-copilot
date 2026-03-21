"""Signal detection engine — checks entry conditions for real-time monitoring.

Evaluates a snapshot of price data + cached analysis to determine whether
ALL entry conditions are met.  When they are → SIGNAL FIRED.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from modules.strategy import is_commission_viable

logger = logging.getLogger(__name__)


@dataclass
class ConditionResult:
    """Result of a single condition check."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class DetectionResult:
    """Full result of signal detection for one asset."""

    symbol: str
    timestamp: str
    fired: bool = False
    direction: str | None = None
    entry: float | None = None
    sl: float | None = None
    tp: float | None = None
    quality_score: int = 0
    mtf_alignment: str | None = None
    regime: str = "NEUTRAL"
    conditions: list[ConditionResult] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "fired": self.fired,
            "direction": self.direction,
            "entry": self.entry,
            "sl": self.sl,
            "tp": self.tp,
            "quality_score": self.quality_score,
            "mtf": self.mtf_alignment,
            "regime": self.regime,
            "conditions": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.conditions
            ],
            "reason": self.reason,
        }


def _get_signal_value(signals: dict, name: str) -> Any:
    """Extract a signal's value from the signals dict."""
    key = name.lower().replace(" ", "_")
    sig = signals.get(key)
    if sig:
        return sig.get("value"), sig.get("label", "NEUTRAL")
    return None, "NEUTRAL"


def check_entry_conditions(
    analysis_data: dict,
) -> DetectionResult:
    """Check all entry conditions against a full analysis result.

    Parameters
    ----------
    analysis_data : dict
        The result from ``analyze_single_asset()`` — the same JSON the API returns.

    Returns
    -------
    DetectionResult
        Includes whether the signal fired and all individual condition results.
    """
    symbol = analysis_data.get("symbol", "?")
    result = DetectionResult(
        symbol=symbol,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    conditions: list[ConditionResult] = []

    # Unpack nested data
    tech = analysis_data.get("analysis", {})
    technicals = tech.get("technicals", {})
    signals = technicals.get("signals", {})
    setup = analysis_data.get("setup", {})
    regime = analysis_data.get("regime", "NEUTRAL")
    calendar = analysis_data.get("calendar")

    # ─── Condition 1: Regime must be LONG ──────────────────────────
    regime_ok = regime == "LONG"
    conditions.append(ConditionResult(
        name="Directional Regime",
        passed=regime_ok,
        detail=f"Regime={regime}",
    ))

    if not regime_ok:
        result.conditions = conditions
        result.regime = regime
        if regime in ("SHORT", "BEARISH"):
            result.reason = "Regime is bearish — sell if holding"
        else:
            result.reason = f"Regime is {regime}"
        return result

    direction = "LONG"

    # ─── Condition 2: EMA trend alignment (BULLISH) ───────────────
    ema_val, ema_label = _get_signal_value(signals, "EMA Trend")
    ema_ok = ema_label == "BULLISH"
    conditions.append(ConditionResult(
        name="EMA Trend",
        passed=ema_ok,
        detail=f"EMA={ema_label}",
    ))

    # ─── Condition 3: RSI not overbought ──────────────────────────
    rsi_val, rsi_label = _get_signal_value(signals, "RSI")
    rsi_ok = False
    rsi_detail = "No RSI data"
    if rsi_val is not None:
        rsi_ok = rsi_val < 75
        rsi_detail = f"RSI={rsi_val:.1f} (< 75 required)"
    conditions.append(ConditionResult(
        name="RSI Not Overbought",
        passed=rsi_ok,
        detail=rsi_detail,
    ))

    # ─── Condition 4: Quality Score >= 4 ──────────────────────────
    qs = setup.get("quality_score", 0)
    qs_ok = qs >= 4
    conditions.append(ConditionResult(
        name="Quality Score >= 4",
        passed=qs_ok,
        detail=f"QS={qs}/5",
    ))

    # ─── Condition 5: MTF Aligned ─────────────────────────────────
    mtf = technicals.get("mtf", {})
    mtf_align = mtf.get("alignment") if mtf else None
    mtf_ok = mtf_align == "ALIGNED"
    conditions.append(ConditionResult(
        name="MTF Aligned",
        passed=mtf_ok,
        detail=f"MTF={mtf_align or 'N/A'}",
    ))

    # ─── Condition 6: Commission viable ───────────────────────────
    tp_distance = setup.get("tp_distance", 0)
    entry_price = setup.get("entry_price", 0)
    comm_ok = False
    comm_detail = "No entry/TP data"
    if entry_price and tp_distance:
        comm_ok = is_commission_viable(
            entry_price=entry_price,
            tp_distance=tp_distance,
        )
        comm_detail = (
            f"entry={entry_price:.2f}, tp_dist={tp_distance:.4f}, "
            f"viable={comm_ok}"
        )
    conditions.append(ConditionResult(
        name="Commission Viable",
        passed=comm_ok,
        detail=comm_detail,
    ))

    # ─── Condition 7: No high-impact calendar today (soft) ────────
    cal_ok = True
    cal_detail = "No high-impact events today"
    if calendar and calendar.get("events_today"):
        high_impact = [
            ev for ev in calendar["events_today"]
            if ev.get("impact", "").upper() == "HIGH"
        ]
        if high_impact:
            # Soft warning — still passes, but detail notes the event
            titles = ", ".join(ev.get("title", "Event") for ev in high_impact)
            cal_detail = f"WARNING: high-impact today — {titles}"
            logger.info("Calendar warning for %s: %s", symbol, cal_detail)
    conditions.append(ConditionResult(
        name="No High-Impact Calendar Today",
        passed=cal_ok,
        detail=cal_detail,
    ))

    # ─── Aggregate ────────────────────────────────────────────────
    all_passed = all(c.passed for c in conditions)
    failed = [c for c in conditions if not c.passed]

    result.conditions = conditions
    result.fired = all_passed
    result.direction = direction
    result.quality_score = qs
    result.mtf_alignment = mtf_align
    result.regime = regime

    if all_passed:
        result.entry = setup.get("entry_price")
        result.sl = setup.get("stop_loss")
        result.tp = setup.get("take_profit")
        result.reason = "ALL CONDITIONS MET"
    else:
        result.reason = "; ".join(f"{c.name}: {c.detail}" for c in failed)

    return result
