"""Unified trading strategy module — single source of truth.

Shared by both the live system (price_data.py, analyzer.py) and the VBT
backtester (vbt_backtester.py). Contains regime classification, indicator
labeling, composite scoring, quality score, and SL/TP computation.

Dependencies: pandas, pandas_ta, numpy only. No live data pipeline imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

class Regime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    NEUTRAL = "NEUTRAL"


def classify_regime(adx: float | None) -> Regime:
    """Classify market regime from ADX value.

    - ADX > 25  → TRENDING (strong directional momentum)
    - ADX < 20  → RANGING  (mean-reverting, choppy)
    - 20–25     → NEUTRAL  (transition zone)
    """
    if adx is None or pd.isna(adx):
        return Regime.NEUTRAL
    if adx > 25:
        return Regime.TRENDING
    if adx < 20:
        return Regime.RANGING
    return Regime.NEUTRAL


# ---------------------------------------------------------------------------
# Indicator labeling — regime-aware
# ---------------------------------------------------------------------------

@dataclass
class IndicatorLabel:
    """Result of labeling a single indicator."""
    label: str        # "BULLISH", "BEARISH", "NEUTRAL"
    detail: str       # Human-readable explanation
    weight: float     # Contribution weight (after regime adjustment)


def label_rsi(value: float, regime: Regime) -> IndicatorLabel:
    """Label RSI with regime-aware interpretation.

    TRENDING: RSI > 55 = bullish momentum, < 45 = bearish momentum
    RANGING:  RSI < 30 = oversold (bullish), > 70 = overbought (bearish)
    """
    if pd.isna(value):
        return IndicatorLabel("NEUTRAL", "RSI N/A", 0.0)

    base_weight = 1.0

    if regime == Regime.TRENDING:
        # Trend confirmation
        if value > 55:
            return IndicatorLabel("BULLISH", f"RSI {value:.1f} — bullish momentum", base_weight)
        elif value < 45:
            return IndicatorLabel("BEARISH", f"RSI {value:.1f} — bearish momentum", base_weight)
        elif value > 50:
            return IndicatorLabel("BULLISH", f"RSI {value:.1f} — mild bullish", base_weight * 0.4)
        elif value < 50:
            return IndicatorLabel("BEARISH", f"RSI {value:.1f} — mild bearish", base_weight * 0.4)
        return IndicatorLabel("NEUTRAL", f"RSI {value:.1f} — neutral", 0.0)
    else:
        # Mean reversion (RANGING or NEUTRAL)
        if value < 30:
            return IndicatorLabel("BULLISH", f"RSI {value:.1f} — oversold", base_weight)
        elif value > 70:
            return IndicatorLabel("BEARISH", f"RSI {value:.1f} — overbought", base_weight)
        elif value < 40:
            return IndicatorLabel("BULLISH", f"RSI {value:.1f} — bearish momentum", base_weight * 0.5)
        elif value > 60:
            return IndicatorLabel("BEARISH", f"RSI {value:.1f} — bullish momentum", base_weight * 0.5)
        else:
            return IndicatorLabel("NEUTRAL", f"RSI {value:.1f} — neutral", 0.0)


def label_macd(hist: float, prev_hist: float | None = None, regime: Regime = Regime.NEUTRAL) -> IndicatorLabel:
    """Label MACD histogram (always momentum-oriented)."""
    if pd.isna(hist):
        return IndicatorLabel("NEUTRAL", "MACD N/A", 0.0)

    base_weight = 1.0

    if prev_hist is not None and not pd.isna(prev_hist):
        if hist > 0 and prev_hist <= 0:
            return IndicatorLabel("BULLISH", "MACD bullish crossover", base_weight)
        elif hist < 0 and prev_hist >= 0:
            return IndicatorLabel("BEARISH", "MACD bearish crossover", base_weight)

    if hist > 0:
        return IndicatorLabel("BULLISH", f"MACD positive ({hist:.2f})", base_weight)
    elif hist < 0:
        return IndicatorLabel("BEARISH", f"MACD negative ({hist:.2f})", base_weight)
    return IndicatorLabel("NEUTRAL", "MACD neutral", 0.0)


def label_ema_trend(ema20: float, ema50: float, price: float | None = None, regime: Regime = Regime.NEUTRAL) -> IndicatorLabel:
    """Label EMA20 vs EMA50 trend (always momentum-oriented)."""
    if pd.isna(ema20) or pd.isna(ema50):
        return IndicatorLabel("NEUTRAL", "EMA N/A", 0.0)

    base_weight = 1.0

    if ema20 > ema50:
        if price is not None and not pd.isna(price) and price > ema20:
            return IndicatorLabel("BULLISH", f"EMA20 ({ema20:.2f}) > EMA50 ({ema50:.2f}), price above both", base_weight)
        return IndicatorLabel("BULLISH", f"EMA20 ({ema20:.2f}) > EMA50 ({ema50:.2f})", base_weight)
    elif ema20 < ema50:
        if price is not None and not pd.isna(price) and price < ema20:
            return IndicatorLabel("BEARISH", f"EMA20 ({ema20:.2f}) < EMA50 ({ema50:.2f}), price below both", base_weight)
        return IndicatorLabel("BEARISH", f"EMA20 ({ema20:.2f}) < EMA50 ({ema50:.2f})", base_weight)
    return IndicatorLabel("NEUTRAL", f"EMA20 ≈ EMA50 ({ema20:.2f})", 0.0)


def label_bbands(
    close: float,
    bb_upper: float,
    bb_lower: float,
    bb_middle: float,
    bandwidth: float | None = None,
    regime: Regime = Regime.NEUTRAL,
) -> IndicatorLabel:
    """Label Bollinger Bands with regime-dependent interpretation."""
    if any(pd.isna(v) for v in [close, bb_upper, bb_lower, bb_middle]):
        return IndicatorLabel("NEUTRAL", "BBands N/A", 0.0)

    base_weight = 1.0

    if regime == Regime.TRENDING:
        # Trend confirmation: above/below middle band
        if close > bb_middle:
            return IndicatorLabel("BULLISH", f"Above mid BB ({bb_middle:.2f})", base_weight * 0.8)
        else:
            return IndicatorLabel("BEARISH", f"Below mid BB ({bb_middle:.2f})", base_weight * 0.8)
    else:
        # Mean reversion
        if bandwidth is not None and not pd.isna(bandwidth) and bandwidth < 4.0:
            return IndicatorLabel("NEUTRAL", f"BB squeeze (bw {bandwidth:.1f}%) — breakout pending", 0.0)
        if close > bb_upper:
            return IndicatorLabel("BEARISH", f"Above upper BB ({bb_upper:.2f}) — overextended", base_weight)
        elif close < bb_lower:
            return IndicatorLabel("BULLISH", f"Below lower BB ({bb_lower:.2f}) — oversold", base_weight)
        elif close > bb_middle:
            return IndicatorLabel("BULLISH", f"Above mid BB ({bb_middle:.2f})", base_weight * 0.3)
        else:
            return IndicatorLabel("BEARISH", f"Below mid BB ({bb_middle:.2f})", base_weight * 0.3)


def label_stochastic(
    k_val: float,
    d_val: float,
    prev_k: float | None = None,
    prev_d: float | None = None,
    regime: Regime = Regime.NEUTRAL,
) -> IndicatorLabel:
    """Label Stochastic oscillator with regime-dependent interpretation."""
    if pd.isna(k_val) or pd.isna(d_val):
        return IndicatorLabel("NEUTRAL", "Stoch N/A", 0.0)

    base_weight = 1.0

    # Crossover detection (used in ranging mode)
    k_cross_up = False
    k_cross_down = False
    if prev_k is not None and prev_d is not None and not pd.isna(prev_k) and not pd.isna(prev_d):
        k_cross_up = prev_k <= prev_d and k_val > d_val
        k_cross_down = prev_k >= prev_d and k_val < d_val

    if regime == Regime.TRENDING:
        # Trend confirmation
        if k_val > 50:
            return IndicatorLabel("BULLISH", f"Stoch %K {k_val:.1f} — bullish trend", base_weight * 0.8)
        else:
            return IndicatorLabel("BEARISH", f"Stoch %K {k_val:.1f} — bearish trend", base_weight * 0.8)
    else:
        # Mean reversion
        if k_cross_up and k_val < 30:
            return IndicatorLabel("BULLISH", f"Stoch %K {k_val:.1f} — oversold + bullish crossover", base_weight)
        elif k_cross_down and k_val > 70:
            return IndicatorLabel("BEARISH", f"Stoch %K {k_val:.1f} — overbought + bearish crossover", base_weight)
        elif k_val < 20:
            return IndicatorLabel("BULLISH", f"Stoch %K {k_val:.1f} — oversold", base_weight)
        elif k_val > 80:
            return IndicatorLabel("BEARISH", f"Stoch %K {k_val:.1f} — overbought", base_weight)
        elif k_cross_up:
            return IndicatorLabel("BULLISH", f"Stoch %K {k_val:.1f} — bullish crossover", base_weight * 0.5)
        elif k_cross_down:
            return IndicatorLabel("BEARISH", f"Stoch %K {k_val:.1f} — bearish crossover", base_weight * 0.5)
        elif k_val > d_val:
            return IndicatorLabel("BULLISH", f"Stoch %K {k_val:.1f} / %D {d_val:.1f}", base_weight * 0.3)
        elif k_val < d_val:
            return IndicatorLabel("BEARISH", f"Stoch %K {k_val:.1f} / %D {d_val:.1f}", base_weight * 0.3)
        return IndicatorLabel("NEUTRAL", f"Stoch %K {k_val:.1f} / %D {d_val:.1f}", 0.0)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

# Indicator classification for weight adjustment
MOMENTUM_INDICATORS = {"MACD", "EMA_TREND"}
MEAN_REVERSION_INDICATORS = {"RSI", "BBANDS"}

# Threshold: 60% agreement required for a directional signal
COMPOSITE_THRESHOLD = 0.60


def compute_composite(
    labels: list[tuple[str, IndicatorLabel]],
    regime: Regime = Regime.NEUTRAL,
    adx_filter: float | None = None,
) -> tuple[str, float]:
    """Compute composite directional score from labeled indicators.

    Args:
        labels: List of (indicator_name, IndicatorLabel) pairs.
        regime: Current market regime.
        adx_filter: If provided, only signal when ADX > this value.

    Returns:
        (direction, confidence_pct) — direction is BULLISH/BEARISH/NEUTRAL,
        confidence_pct is 0-100.
    """
    bullish_weight = 0.0
    bearish_weight = 0.0
    total_weight = 0.0

    for name, lbl in labels:
        # Apply regime-based weight multiplier
        if name in MOMENTUM_INDICATORS:
            regime_mult = 1.5 if regime == Regime.TRENDING else (0.7 if regime == Regime.RANGING else 1.0)
        elif name in MEAN_REVERSION_INDICATORS:
            regime_mult = 0.7 if regime == Regime.TRENDING else (1.5 if regime == Regime.RANGING else 1.0)
        else:
            regime_mult = 1.0

        w = lbl.weight * regime_mult
        total_weight += regime_mult  # Use full weight for denominator (even if label is neutral)

        if lbl.label == "BULLISH":
            bullish_weight += w
        elif lbl.label == "BEARISH":
            bearish_weight += w

    if total_weight <= 0:
        return "NEUTRAL", 50.0

    bull_pct = bullish_weight / total_weight
    bear_pct = bearish_weight / total_weight

    # ADX directional energy filter
    if adx_filter is not None and adx_filter <= 20:
        return "NEUTRAL", 50.0

    if bull_pct >= COMPOSITE_THRESHOLD:
        return "BULLISH", round(bull_pct * 100, 1)
    elif bear_pct >= COMPOSITE_THRESHOLD:
        return "BEARISH", round(bear_pct * 100, 1)
    return "NEUTRAL", 50.0


# ---------------------------------------------------------------------------
# Quality Score from OHLCV
# ---------------------------------------------------------------------------

@dataclass
class QualityScoreResult:
    """Setup quality score (0-5)."""
    total: int = 0
    confluence: bool = False
    strong_trend: bool = False
    near_key_level: bool = False
    candle_pattern: bool = False
    volume_above_avg: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "confluence": self.confluence,
            "strong_trend": self.strong_trend,
            "near_key_level": self.near_key_level,
            "candle_pattern": self.candle_pattern,
            "volume_above_avg": self.volume_above_avg,
        }


def detect_candle_pattern(df: pd.DataFrame, bar_idx: int, direction: str) -> str | None:
    """Detect candle patterns on a specific bar.

    Args:
        df: OHLCV DataFrame.
        bar_idx: Integer position of the bar to check.
        direction: "BULLISH" or "BEARISH".

    Returns:
        Pattern name ("ENGULFING", "PIN_BAR", "INSIDE_BAR") or None.
    """
    if bar_idx < 1 or bar_idx >= len(df):
        return None

    last = df.iloc[bar_idx]
    prev = df.iloc[bar_idx - 1]

    o, h, l, c = float(last["Open"]), float(last["High"]), float(last["Low"]), float(last["Close"])
    po, ph, pl, pc = float(prev["Open"]), float(prev["High"]), float(prev["Low"]), float(prev["Close"])

    body = abs(c - o)
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l
    total_range = h - l

    # Inside bar
    if h < ph and l > pl:
        return "INSIDE_BAR"

    if total_range <= 0 or body <= 0:
        return None

    # Bullish engulfing
    if direction == "BULLISH" and c > o and pc < po and c > po and o < pc:
        return "ENGULFING"

    # Bearish engulfing
    if direction == "BEARISH" and c < o and pc > po and c < po and o > pc:
        return "ENGULFING"

    # Bullish pin bar
    if direction == "BULLISH" and lower_wick > body * 2 and lower_wick > upper_wick * 2:
        return "PIN_BAR"

    # Bearish pin bar
    if direction == "BEARISH" and upper_wick > body * 2 and upper_wick > lower_wick * 2:
        return "PIN_BAR"

    return None


def _psych_step(price: float) -> float:
    """Determine psychological level step size based on price magnitude."""
    if price < 2:
        return 0.01
    elif price < 20:
        return 0.5
    elif price < 200:
        return 10
    elif price < 2000:
        return 50
    elif price < 6000:
        return 100
    elif price < 25000:
        return 500
    else:
        return 1000


@dataclass
class KeyLevelsResult:
    """Key support/resistance levels."""
    pdh: float | None = None
    pdl: float | None = None
    pdc: float | None = None
    pp: float | None = None
    r1: float | None = None
    r2: float | None = None
    s1: float | None = None
    s2: float | None = None
    nearest_level: float | None = None
    nearest_level_name: str = ""
    nearest_level_dist_pct: float | None = None


def compute_key_levels(df: pd.DataFrame, bar_idx: int) -> KeyLevelsResult:
    """Compute key S/R levels from OHLCV data up to bar_idx.

    Calculates pivot points (PP, R1, R2, S1, S2) and PDH/PDL/PDC
    from the bar preceding bar_idx.
    """
    result = KeyLevelsResult()

    if bar_idx < 2 or bar_idx >= len(df):
        return result

    prev = df.iloc[bar_idx - 1]
    current_price = float(df.iloc[bar_idx]["Close"])

    result.pdh = float(prev["High"])
    result.pdl = float(prev["Low"])
    result.pdc = float(prev["Close"])

    result.pp = (result.pdh + result.pdl + result.pdc) / 3
    result.r1 = 2 * result.pp - result.pdl
    result.r2 = result.pp + (result.pdh - result.pdl)
    result.s1 = 2 * result.pp - result.pdh
    result.s2 = result.pp - (result.pdh - result.pdl)

    # Find nearest level
    levels = [
        ("PDH", result.pdh), ("PDL", result.pdl), ("PDC", result.pdc),
        ("PP", result.pp), ("R1", result.r1), ("R2", result.r2),
        ("S1", result.s1), ("S2", result.s2),
    ]
    levels = [(n, v) for n, v in levels if v is not None]

    # Add psychological levels
    step = _psych_step(current_price)
    psych_below = float(math.floor(current_price / step) * step)
    psych_above = psych_below + step
    if abs(current_price - psych_below) < step * 0.001:
        psych_below -= step
    levels.append(("Psych", psych_below))
    levels.append(("Psych", psych_above))

    if levels and current_price > 0:
        closest_name, closest_val = min(levels, key=lambda nv: abs(nv[1] - current_price))
        result.nearest_level = closest_val
        result.nearest_level_name = closest_name
        result.nearest_level_dist_pct = round(((current_price - closest_val) / current_price) * 100, 2)

    return result


def compute_quality_score(
    df: pd.DataFrame,
    bar_idx: int,
    composite_dir: str,
    adx_value: float | None = None,
    labels: list[tuple[str, IndicatorLabel]] | None = None,
    key_levels: KeyLevelsResult | None = None,
) -> QualityScoreResult:
    """Compute quality score (0-5) from OHLCV data.

    All 5 components are computable from OHLCV:
    1. Confluence: 4+ labeled indicators agree with composite
    2. Strong trend: ADX > 25
    3. Near key level: price within 0.5% of S/R
    4. Candle pattern: engulfing, pin bar, or inside bar
    5. Volume above avg: last bar vol > 20-day average
    """
    qs = QualityScoreResult()

    if bar_idx < 1 or bar_idx >= len(df):
        return qs

    # 1. Confluence
    if labels and composite_dir in ("BULLISH", "BEARISH"):
        count = sum(1 for _, lbl in labels if lbl.label == composite_dir)
        if count >= 4:
            qs.confluence = True

    # 2. Strong trend
    if adx_value is not None and not pd.isna(adx_value) and adx_value > 25:
        qs.strong_trend = True

    # 3. Near key level
    if key_levels is None:
        key_levels = compute_key_levels(df, bar_idx)
    if key_levels.nearest_level_dist_pct is not None:
        if abs(key_levels.nearest_level_dist_pct) < 0.5 and composite_dir != "NEUTRAL":
            qs.near_key_level = True

    # 4. Candle pattern
    if detect_candle_pattern(df, bar_idx, composite_dir):
        qs.candle_pattern = True

    # 5. Volume above 20-day average
    if "Volume" in df.columns and bar_idx >= 20:
        vol_window = df["Volume"].iloc[bar_idx - 20:bar_idx]
        vol_avg = float(vol_window.mean())
        last_vol = float(df["Volume"].iloc[bar_idx])
        if vol_avg > 0 and last_vol > vol_avg:
            qs.volume_above_avg = True

    qs.total = sum([
        qs.confluence, qs.strong_trend, qs.near_key_level,
        qs.candle_pattern, qs.volume_above_avg,
    ])

    return qs


# ---------------------------------------------------------------------------
# SL/TP computation — per-class defaults with adaptive ATR percentile
# ---------------------------------------------------------------------------

# Per-class SL/TP defaults (ATR multipliers)
_CLASS_SL_TP: dict[str, dict[str, float]] = {
    "forex":     {"sl_atr_mult": 1.2, "tp_atr_mult": 3.0},
    "commodity": {"sl_atr_mult": 1.5, "tp_atr_mult": 3.5},
    "index":     {"sl_atr_mult": 2.0, "tp_atr_mult": 4.0},
    "stock":     {"sl_atr_mult": 1.8, "tp_atr_mult": 3.0},
}

# Fallback
_DEFAULT_SL_TP = {"sl_atr_mult": 1.5, "tp_atr_mult": 3.0}


@dataclass
class SLTPResult:
    """Stop-loss and take-profit computation result."""
    sl_distance: float       # Always positive
    tp_distance: float       # Always positive
    sl_multiplier: float
    tp_multiplier: float
    atr_percentile: float
    risk_reward: str         # e.g. "1:2.5"


def compute_sl_tp(
    atr_value: float,
    atr_series: pd.Series | None = None,
    asset_class: str = "index",
    adaptive: bool = True,
    sl_override: float | None = None,
    tp_override: float | None = None,
) -> SLTPResult:
    """Compute SL/TP distances using per-class defaults and optional ATR-adaptive adjustment.

    Args:
        atr_value: Current ATR value.
        atr_series: Recent ATR series for percentile computation. If None, adaptive is disabled.
        asset_class: One of "forex", "commodity", "index", "stock".
        adaptive: Whether to adjust SL/TP based on ATR percentile.
        sl_override: Override SL ATR multiplier (bypasses per-class default).
        tp_override: Override TP ATR multiplier (bypasses per-class default).

    Returns:
        SLTPResult with distances (always positive) and metadata.
    """
    params = _CLASS_SL_TP.get(asset_class, _DEFAULT_SL_TP)
    sl_mult = sl_override if sl_override is not None else params["sl_atr_mult"]
    tp_mult = tp_override if tp_override is not None else params["tp_atr_mult"]

    atr_percentile = 1.0

    if adaptive and atr_series is not None:
        clean_atr = atr_series.dropna()
        if len(clean_atr) >= 20:
            recent = clean_atr.tail(20)
            atr_avg = float(recent.mean())
            if atr_avg > 0:
                atr_percentile = atr_value / atr_avg

            # Adaptive: adjust multipliers based on volatility regime
            if atr_percentile < 0.8:
                # Low vol — tighten SL (but keep R:R)
                adj = 1.0
            elif atr_percentile > 1.5:
                # High vol — widen SL
                adj = 2.0
            else:
                # Linear interpolation
                adj = 1.0 + (atr_percentile - 0.8) / (1.5 - 0.8) * (2.0 - 1.0)

            # Scale multipliers by adaptive factor relative to base
            base_ratio = tp_mult / sl_mult if sl_mult > 0 else 2.0
            sl_mult = sl_mult * (adj / 1.5)  # Normalize around midpoint
            sl_mult = max(sl_mult, params.get("sl_atr_mult", 1.5) * 0.5)  # Floor
            tp_mult = sl_mult * base_ratio

    sl_distance = abs(atr_value * sl_mult)
    tp_distance = abs(atr_value * tp_mult)
    rr = tp_distance / sl_distance if sl_distance > 0 else 0.0

    return SLTPResult(
        sl_distance=sl_distance,
        tp_distance=tp_distance,
        sl_multiplier=round(sl_mult, 3),
        tp_multiplier=round(tp_mult, 3),
        atr_percentile=round(atr_percentile, 3),
        risk_reward=f"1:{rr:.1f}",
    )


def compute_sl_tp_series(
    atr: pd.Series,
    asset_class: str = "index",
    adaptive: bool = True,
    sl_override: float | None = None,
    tp_override: float | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Vectorized SL/TP distance computation for backtesting.

    Returns (sl_distance, tp_distance) as Series — always positive values.
    """
    params = _CLASS_SL_TP.get(asset_class, _DEFAULT_SL_TP)
    sl_mult = sl_override if sl_override is not None else params["sl_atr_mult"]
    tp_mult = tp_override if tp_override is not None else params["tp_atr_mult"]

    if adaptive and len(atr.dropna()) > 20:
        # ATR percentile: current ATR / rolling 50-bar mean
        atr_pctile = atr.rolling(50, min_periods=20).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )
        # Adaptive: low vol → wider SL, high vol → tighter SL
        sl_multiplier = sl_mult * (1.0 + (0.5 - atr_pctile).clip(-0.5, 0.5))
        tp_multiplier = sl_multiplier * (tp_mult / sl_mult)
    else:
        sl_multiplier = pd.Series(sl_mult, index=atr.index)
        tp_multiplier = pd.Series(tp_mult, index=atr.index)

    sl_distance = (atr * sl_multiplier).abs()
    tp_distance = (atr * tp_multiplier).abs()

    return sl_distance, tp_distance


# ---------------------------------------------------------------------------
# Backtester helper: label all indicators for a single bar
# ---------------------------------------------------------------------------

def label_bar(df: pd.DataFrame, i: int) -> tuple[Regime, list[tuple[str, IndicatorLabel]], float | None]:
    """Label all indicators for bar i of a DataFrame with indicator columns.

    Expects columns: RSI, MACD_hist, EMA20, EMA50, BB_upper, BB_lower,
    BB_middle, BB_bandwidth, STOCH_K, STOCH_D, ADX, ATR, Close.

    Returns:
        (regime, labels, adx_value) where labels is [(name, IndicatorLabel), ...].
    """
    row = df.iloc[i]
    close = float(row["Close"])

    adx = row.get("ADX")
    if adx is not None and pd.isna(adx):
        adx = None
    adx_val = float(adx) if adx is not None else None

    regime = classify_regime(adx_val)
    labels: list[tuple[str, IndicatorLabel]] = []

    # RSI
    rsi = row.get("RSI")
    if rsi is not None and not pd.isna(rsi):
        labels.append(("RSI", label_rsi(float(rsi), regime)))

    # MACD
    macd_hist = row.get("MACD_hist")
    prev_hist = df.iloc[i - 1].get("MACD_hist") if i > 0 else None
    if macd_hist is not None and not pd.isna(macd_hist):
        ph = float(prev_hist) if prev_hist is not None and not pd.isna(prev_hist) else None
        labels.append(("MACD", label_macd(float(macd_hist), ph, regime)))

    # EMA Trend
    ema20 = row.get("EMA20")
    ema50 = row.get("EMA50")
    if ema20 is not None and ema50 is not None and not pd.isna(ema20) and not pd.isna(ema50):
        labels.append(("EMA_TREND", label_ema_trend(float(ema20), float(ema50), close, regime)))

    # Bollinger Bands
    bb_upper = row.get("BB_upper")
    bb_lower = row.get("BB_lower")
    bb_mid = row.get("BB_middle")
    bb_bw = row.get("BB_bandwidth")
    if all(v is not None and not pd.isna(v) for v in [bb_upper, bb_lower, bb_mid]):
        bw = float(bb_bw) if bb_bw is not None and not pd.isna(bb_bw) else None
        labels.append(("BBANDS", label_bbands(close, float(bb_upper), float(bb_lower), float(bb_mid), bw, regime)))

    # Stochastic
    stoch_k = row.get("STOCH_K")
    stoch_d = row.get("STOCH_D")
    if stoch_k is not None and stoch_d is not None and not pd.isna(stoch_k) and not pd.isna(stoch_d):
        prev_k = float(df.iloc[i - 1]["STOCH_K"]) if i > 0 and not pd.isna(df.iloc[i - 1].get("STOCH_K", np.nan)) else None
        prev_d = float(df.iloc[i - 1]["STOCH_D"]) if i > 0 and not pd.isna(df.iloc[i - 1].get("STOCH_D", np.nan)) else None
        labels.append(("STOCH", label_stochastic(float(stoch_k), float(stoch_d), prev_k, prev_d, regime)))

    return regime, labels, adx_val
