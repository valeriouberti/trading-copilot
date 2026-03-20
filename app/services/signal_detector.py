"""Signal detection engine — checks entry conditions for real-time monitoring.

Evaluates a snapshot of price data + cached analysis to determine whether
ALL entry conditions are met.  When they are → SIGNAL FIRED.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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


def _check_session_quality() -> tuple[bool, str]:
    """Check if we're in a high-quality trading session (London/NYSE open).

    London: 08:00-12:00 UTC
    NYSE:   14:30-18:00 UTC
    """
    now = datetime.now(timezone.utc)
    hour = now.hour
    minute = now.minute
    t = hour * 60 + minute

    # London session: 08:00 - 12:00 UTC
    if 480 <= t <= 720:
        return True, "LONDON"
    # NYSE session: 14:30 - 18:00 UTC
    if 870 <= t <= 1080:
        return True, "NYSE"
    # Overlap (best): 14:30 - 16:30 UTC
    if 870 <= t <= 990:
        return True, "OVERLAP"

    return False, "DEAD_ZONE"


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

    # ─── Condition 1: Regime is directional ───────────────────────
    regime_ok = regime in ("LONG", "SHORT")
    conditions.append(ConditionResult(
        name="Directional Regime",
        passed=regime_ok,
        detail=f"Regime={regime}",
    ))

    if not regime_ok:
        result.conditions = conditions
        result.reason = f"Regime is {regime}"
        return result

    direction = regime

    # ─── Condition 2: EMA trend alignment ─────────────────────────
    ema_val, ema_label = _get_signal_value(signals, "EMA Trend")
    ema_ok = (
        (direction == "LONG" and ema_label == "BULLISH")
        or (direction == "SHORT" and ema_label == "BEARISH")
    )
    conditions.append(ConditionResult(
        name="EMA Trend",
        passed=ema_ok,
        detail=f"EMA={ema_label}, direction={direction}",
    ))

    # ─── Condition 3: VWAP confirmation ───────────────────────────
    vwap_val, vwap_label = _get_signal_value(signals, "VWAP")
    price_data = tech.get("price", {})
    current_price = price_data.get("current", 0)

    vwap_ok = False
    if vwap_val and current_price:
        if direction == "LONG":
            vwap_ok = current_price > vwap_val
        else:
            vwap_ok = current_price < vwap_val
    conditions.append(ConditionResult(
        name="VWAP Position",
        passed=vwap_ok,
        detail=f"Price={current_price:.2f}, VWAP={vwap_val}" if vwap_val else "No VWAP data",
    ))

    # ─── Condition 4: RSI not extreme ─────────────────────────────
    rsi_val, rsi_label = _get_signal_value(signals, "RSI")
    rsi_ok = True
    rsi_detail = "No RSI data"
    if rsi_val is not None:
        # For LONG: RSI should not be overbought (>75)
        # For SHORT: RSI should not be oversold (<25)
        if direction == "LONG":
            rsi_ok = rsi_val < 75
        else:
            rsi_ok = rsi_val > 25
        rsi_detail = f"RSI={rsi_val:.1f}"
    conditions.append(ConditionResult(
        name="RSI Not Extreme",
        passed=rsi_ok,
        detail=rsi_detail,
    ))

    # ─── Condition 5: Quality Score >= 4 ──────────────────────────
    qs = setup.get("quality_score", 0)
    qs_ok = qs >= 4
    conditions.append(ConditionResult(
        name="Quality Score >= 4",
        passed=qs_ok,
        detail=f"QS={qs}/5",
    ))

    # ─── Condition 6: MTF Aligned ─────────────────────────────────
    mtf = technicals.get("mtf", {})
    mtf_align = mtf.get("alignment") if mtf else None
    mtf_ok = mtf_align in ("ALIGNED", None)
    conditions.append(ConditionResult(
        name="MTF Aligned",
        passed=mtf_ok,
        detail=f"MTF={mtf_align or 'N/A'}",
    ))

    # ─── Condition 7: Session quality ─────────────────────────────
    session_ok, session_name = _check_session_quality()
    conditions.append(ConditionResult(
        name="Session Quality",
        passed=session_ok,
        detail=f"Session={session_name}",
    ))

    # ─── Condition 8: No calendar event within 2 hours ────────────
    cal_ok = True
    cal_detail = "No events nearby"
    if calendar and calendar.get("events_today"):
        for ev in calendar["events_today"]:
            hours_away = ev.get("hours_away")
            if hours_away is not None and 0 < hours_away < 2:
                cal_ok = False
                cal_detail = f"{ev.get('title', 'Event')} in {hours_away:.1f}h"
                break
    conditions.append(ConditionResult(
        name="No Imminent Calendar",
        passed=cal_ok,
        detail=cal_detail,
    ))

    # ─── Condition 9: Setup is tradeable ──────────────────────────
    tradeable = setup.get("tradeable", False)
    conditions.append(ConditionResult(
        name="Setup Tradeable",
        passed=tradeable,
        detail=setup.get("reason", "?"),
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
