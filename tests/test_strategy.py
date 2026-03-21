"""Tests for the unified strategy module (modules.strategy).

Validates that regime classification, indicator labeling, composite scoring,
quality score, candle pattern detection, and SL/TP computation all produce
correct results — ensuring the live system and backtester share identical logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.strategy import (
    Regime,
    classify_regime,
    label_rsi,
    label_macd,
    label_ema_trend,
    label_bbands,
    label_stochastic,
    compute_composite,
    compute_quality_score,
    compute_key_levels,
    compute_sl_tp,
    compute_sl_tp_series,
    detect_candle_pattern,
    label_bar,
    IndicatorLabel,
    QualityScoreResult,
    SLTPResult,
    COMPOSITE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100, base: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.integers(1000, 10000, n).astype(float)

    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


def _make_ohlcv_with_indicators(n: int = 100) -> pd.DataFrame:
    """Build OHLCV + indicator columns matching what compute_indicators produces."""
    import pandas_ta as ta

    df = _make_ohlcv(n)

    rsi = ta.rsi(df["Close"], length=14)
    if rsi is not None:
        df["RSI"] = rsi

    macd = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    if macd is not None:
        df["MACD"] = macd.iloc[:, 0]
        df["MACD_hist"] = macd.iloc[:, 1]
        df["MACD_signal"] = macd.iloc[:, 2]

    bb = ta.bbands(df["Close"], length=20, std=2)
    if bb is not None:
        df["BB_upper"] = bb.iloc[:, 2]
        df["BB_middle"] = bb.iloc[:, 1]
        df["BB_lower"] = bb.iloc[:, 0]
        df["BB_bandwidth"] = ((bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1]) * 100

    stoch = ta.stoch(df["High"], df["Low"], df["Close"], k=14, d=3, smooth_k=3)
    if stoch is not None:
        df["STOCH_K"] = stoch.iloc[:, 0]
        df["STOCH_D"] = stoch.iloc[:, 1]

    ema20 = ta.ema(df["Close"], length=20)
    ema50 = ta.ema(df["Close"], length=50)
    if ema20 is not None:
        df["EMA20"] = ema20
    if ema50 is not None:
        df["EMA50"] = ema50

    adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    if adx_df is not None:
        df["ADX"] = adx_df.iloc[:, 0]
        df["DI_plus"] = adx_df.iloc[:, 1]
        df["DI_minus"] = adx_df.iloc[:, 2]

    atr = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    if atr is not None:
        df["ATR"] = atr

    return df


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

class TestClassifyRegime:
    def test_trending(self):
        assert classify_regime(30) == Regime.TRENDING
        assert classify_regime(25.1) == Regime.TRENDING

    def test_ranging(self):
        assert classify_regime(15) == Regime.RANGING
        assert classify_regime(19.9) == Regime.RANGING

    def test_neutral(self):
        assert classify_regime(22) == Regime.NEUTRAL
        assert classify_regime(20) == Regime.NEUTRAL
        assert classify_regime(25) == Regime.NEUTRAL

    def test_none(self):
        assert classify_regime(None) == Regime.NEUTRAL

    def test_nan(self):
        assert classify_regime(float("nan")) == Regime.NEUTRAL


# ---------------------------------------------------------------------------
# RSI labeling
# ---------------------------------------------------------------------------

class TestLabelRSI:
    def test_trending_bullish(self):
        lbl = label_rsi(60, Regime.TRENDING)
        assert lbl.label == "BULLISH"
        assert lbl.weight == 1.0

    def test_trending_bearish(self):
        lbl = label_rsi(40, Regime.TRENDING)
        assert lbl.label == "BEARISH"

    def test_trending_mild_bull(self):
        lbl = label_rsi(52, Regime.TRENDING)
        assert lbl.label == "BULLISH"
        assert lbl.weight == pytest.approx(0.4)

    def test_ranging_oversold(self):
        lbl = label_rsi(25, Regime.RANGING)
        assert lbl.label == "BULLISH"
        assert lbl.weight == 1.0

    def test_ranging_overbought(self):
        lbl = label_rsi(75, Regime.RANGING)
        assert lbl.label == "BEARISH"

    def test_ranging_neutral(self):
        lbl = label_rsi(50, Regime.RANGING)
        assert lbl.label == "NEUTRAL"

    def test_nan(self):
        lbl = label_rsi(float("nan"), Regime.TRENDING)
        assert lbl.label == "NEUTRAL"
        assert lbl.weight == 0.0


# ---------------------------------------------------------------------------
# MACD labeling
# ---------------------------------------------------------------------------

class TestLabelMACD:
    def test_positive(self):
        lbl = label_macd(1.5, None, Regime.NEUTRAL)
        assert lbl.label == "BULLISH"

    def test_negative(self):
        lbl = label_macd(-1.5, None, Regime.NEUTRAL)
        assert lbl.label == "BEARISH"

    def test_bullish_crossover(self):
        lbl = label_macd(0.5, -0.3, Regime.NEUTRAL)
        assert lbl.label == "BULLISH"
        assert "crossover" in lbl.detail.lower()

    def test_bearish_crossover(self):
        lbl = label_macd(-0.5, 0.3, Regime.NEUTRAL)
        assert lbl.label == "BEARISH"
        assert "crossover" in lbl.detail.lower()


# ---------------------------------------------------------------------------
# EMA Trend labeling
# ---------------------------------------------------------------------------

class TestLabelEMATrend:
    def test_bullish(self):
        lbl = label_ema_trend(105.0, 100.0)
        assert lbl.label == "BULLISH"

    def test_bearish(self):
        lbl = label_ema_trend(95.0, 100.0)
        assert lbl.label == "BEARISH"

    def test_bullish_price_above_both(self):
        lbl = label_ema_trend(105.0, 100.0, price=110.0)
        assert lbl.label == "BULLISH"
        assert "above both" in lbl.detail

    def test_neutral(self):
        lbl = label_ema_trend(100.0, 100.0)
        assert lbl.label == "NEUTRAL"


# ---------------------------------------------------------------------------
# BBands labeling
# ---------------------------------------------------------------------------

class TestLabelBBands:
    def test_trending_above_mid(self):
        lbl = label_bbands(105, 110, 90, 100, regime=Regime.TRENDING)
        assert lbl.label == "BULLISH"

    def test_trending_below_mid(self):
        lbl = label_bbands(95, 110, 90, 100, regime=Regime.TRENDING)
        assert lbl.label == "BEARISH"

    def test_ranging_above_upper(self):
        lbl = label_bbands(115, 110, 90, 100, regime=Regime.RANGING)
        assert lbl.label == "BEARISH"

    def test_ranging_below_lower(self):
        lbl = label_bbands(85, 110, 90, 100, regime=Regime.RANGING)
        assert lbl.label == "BULLISH"

    def test_squeeze(self):
        lbl = label_bbands(100, 102, 98, 100, bandwidth=3.0, regime=Regime.RANGING)
        assert lbl.label == "NEUTRAL"
        assert "squeeze" in lbl.detail.lower()


# ---------------------------------------------------------------------------
# Stochastic labeling
# ---------------------------------------------------------------------------

class TestLabelStochastic:
    def test_trending_bullish(self):
        lbl = label_stochastic(60, 55, regime=Regime.TRENDING)
        assert lbl.label == "BULLISH"

    def test_trending_bearish(self):
        lbl = label_stochastic(40, 45, regime=Regime.TRENDING)
        assert lbl.label == "BEARISH"

    def test_ranging_oversold(self):
        lbl = label_stochastic(15, 20, regime=Regime.RANGING)
        assert lbl.label == "BULLISH"

    def test_ranging_overbought(self):
        lbl = label_stochastic(85, 80, regime=Regime.RANGING)
        assert lbl.label == "BEARISH"

    def test_ranging_crossover_oversold(self):
        lbl = label_stochastic(25, 22, prev_k=18, prev_d=20, regime=Regime.RANGING)
        assert lbl.label == "BULLISH"
        assert "crossover" in lbl.detail.lower()


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

class TestComputeComposite:
    def _make_labels(self, bull=0, bear=0, neutral=0):
        """Helper to build a label list."""
        names = ["RSI", "MACD", "EMA_TREND", "BBANDS", "STOCH"]
        labels = []
        idx = 0
        for _ in range(bull):
            labels.append((names[idx % len(names)], IndicatorLabel("BULLISH", "", 1.0)))
            idx += 1
        for _ in range(bear):
            labels.append((names[idx % len(names)], IndicatorLabel("BEARISH", "", 1.0)))
            idx += 1
        for _ in range(neutral):
            labels.append((names[idx % len(names)], IndicatorLabel("NEUTRAL", "", 0.0)))
            idx += 1
        return labels

    def test_bullish_strong(self):
        labels = self._make_labels(bull=4, bear=1)
        direction, confidence = compute_composite(labels, Regime.NEUTRAL)
        assert direction == "BULLISH"
        assert confidence > 60

    def test_bearish_strong(self):
        labels = self._make_labels(bear=4, bull=1)
        direction, confidence = compute_composite(labels, Regime.NEUTRAL)
        assert direction == "BEARISH"

    def test_neutral_mixed(self):
        labels = self._make_labels(bull=2, bear=2, neutral=1)
        direction, _ = compute_composite(labels, Regime.NEUTRAL)
        assert direction == "NEUTRAL"

    def test_adx_filter_blocks(self):
        labels = self._make_labels(bull=5)
        # ADX < 15 should block signals (very low directional energy)
        direction, _ = compute_composite(labels, Regime.NEUTRAL, adx_filter=12)
        assert direction == "NEUTRAL"

    def test_adx_filter_allows_transition_zone(self):
        labels = self._make_labels(bull=5)
        # ADX 15-25 (transition zone) should NOT block signals
        direction, _ = compute_composite(labels, Regime.NEUTRAL, adx_filter=18)
        assert direction == "BULLISH"

    def test_threshold_60pct(self):
        # Exactly 3 out of 5 = 60% → should pass
        labels = self._make_labels(bull=3, bear=0, neutral=2)
        direction, _ = compute_composite(labels, Regime.NEUTRAL)
        assert direction == "BULLISH"


# ---------------------------------------------------------------------------
# Quality Score
# ---------------------------------------------------------------------------

class TestComputeQualityScore:
    def test_full_score(self):
        """Construct a scenario where all 5 QS components fire."""
        df = _make_ohlcv(100)
        bar = 99

        # Force volume spike
        df.loc[df.index[bar], "Volume"] = 999999

        # Build labels where 4+ agree
        labels = [
            ("RSI", IndicatorLabel("BULLISH", "", 1.0)),
            ("MACD", IndicatorLabel("BULLISH", "", 1.0)),
            ("EMA_TREND", IndicatorLabel("BULLISH", "", 1.0)),
            ("BBANDS", IndicatorLabel("BULLISH", "", 1.0)),
            ("STOCH", IndicatorLabel("BEARISH", "", 1.0)),
        ]

        qs = compute_quality_score(
            df, bar, "BULLISH",
            adx_value=30,
            labels=labels,
        )
        assert qs.confluence is True
        assert qs.strong_trend is True
        assert qs.volume_above_avg is True
        assert qs.total >= 3

    def test_empty_labels(self):
        df = _make_ohlcv(50)
        qs = compute_quality_score(df, 49, "NEUTRAL")
        assert qs.confluence is False
        assert qs.total >= 0


# ---------------------------------------------------------------------------
# Candle pattern detection
# ---------------------------------------------------------------------------

class TestDetectCandlePattern:
    def test_inside_bar(self):
        df = pd.DataFrame({
            "Open": [100, 101],
            "High": [110, 105],
            "Low": [90, 95],
            "Close": [105, 102],
        })
        assert detect_candle_pattern(df, 1, "BULLISH") == "INSIDE_BAR"

    def test_bullish_engulfing(self):
        df = pd.DataFrame({
            "Open": [105, 98],
            "High": [106, 108],
            "Low": [98, 97],
            "Close": [99, 107],
        })
        result = detect_candle_pattern(df, 1, "BULLISH")
        assert result == "ENGULFING"

    def test_bearish_engulfing(self):
        df = pd.DataFrame({
            "Open": [98, 107],
            "High": [108, 108],
            "Low": [97, 96],
            "Close": [106, 97],
        })
        result = detect_candle_pattern(df, 1, "BEARISH")
        assert result == "ENGULFING"

    def test_pin_bar_bullish(self):
        df = pd.DataFrame({
            "Open": [100, 101],
            "High": [105, 102],
            "Low": [95, 91],
            "Close": [103, 101.5],
        })
        result = detect_candle_pattern(df, 1, "BULLISH")
        assert result == "PIN_BAR"

    def test_no_pattern(self):
        df = pd.DataFrame({
            "Open": [100, 100],
            "High": [102, 102],
            "Low": [98, 98],
            "Close": [101, 101],
        })
        assert detect_candle_pattern(df, 1, "BULLISH") is None

    def test_bar_idx_out_of_range(self):
        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0], "Close": [1]})
        assert detect_candle_pattern(df, 0, "BULLISH") is None


# ---------------------------------------------------------------------------
# Key levels
# ---------------------------------------------------------------------------

class TestComputeKeyLevels:
    def test_basic_levels(self):
        df = _make_ohlcv(10)
        kl = compute_key_levels(df, 5)
        assert kl.pdh is not None
        assert kl.pdl is not None
        assert kl.pdc is not None
        assert kl.pp is not None

    def test_pivot_math(self):
        df = pd.DataFrame({
            "Open": [100, 100, 100],
            "High": [110, 120, 115],
            "Low": [90, 85, 88],
            "Close": [105, 100, 108],
        })
        kl = compute_key_levels(df, 2)
        # PP = (120 + 85 + 100) / 3 = 101.67
        assert kl.pp == pytest.approx(101.6667, rel=0.01)


# ---------------------------------------------------------------------------
# SL/TP computation
# ---------------------------------------------------------------------------

class TestComputeSLTP:
    def test_forex_defaults(self):
        result = compute_sl_tp(atr_value=0.005, asset_class="forex", adaptive=False)
        assert isinstance(result, SLTPResult)
        # Forex: SL = 1.2x ATR, TP = 3.0x ATR
        assert result.sl_distance == pytest.approx(0.005 * 1.2, rel=0.01)
        assert result.tp_distance == pytest.approx(0.005 * 3.0, rel=0.01)

    def test_index_defaults(self):
        result = compute_sl_tp(atr_value=50, asset_class="index", adaptive=False)
        # Index: SL = 2.0x ATR, TP = 4.0x ATR
        assert result.sl_distance == pytest.approx(100.0, rel=0.01)
        assert result.tp_distance == pytest.approx(200.0, rel=0.01)

    def test_commodity_defaults(self):
        result = compute_sl_tp(atr_value=2.0, asset_class="commodity", adaptive=False)
        assert result.sl_distance == pytest.approx(3.0, rel=0.01)
        assert result.tp_distance == pytest.approx(7.0, rel=0.01)

    def test_stock_defaults(self):
        result = compute_sl_tp(atr_value=5.0, asset_class="stock", adaptive=False)
        assert result.sl_distance == pytest.approx(9.0, rel=0.01)
        assert result.tp_distance == pytest.approx(15.0, rel=0.01)

    def test_adaptive_with_series(self):
        atr_series = pd.Series([10.0] * 25)  # Flat ATR
        result = compute_sl_tp(
            atr_value=10.0, atr_series=atr_series,
            asset_class="index", adaptive=True,
        )
        assert result.atr_percentile == pytest.approx(1.0, rel=0.01)

    def test_override(self):
        result = compute_sl_tp(
            atr_value=10.0, asset_class="index", adaptive=False,
            sl_override=1.0, tp_override=2.0,
        )
        assert result.sl_distance == pytest.approx(10.0, rel=0.01)
        assert result.tp_distance == pytest.approx(20.0, rel=0.01)

    def test_risk_reward_string(self):
        result = compute_sl_tp(atr_value=10, asset_class="index", adaptive=False)
        # R:R = 200/100 = 2.0
        assert result.risk_reward == "1:2.0"


class TestComputeSLTPSeries:
    def test_output_shape(self):
        atr = pd.Series([10.0] * 60)
        sl, tp = compute_sl_tp_series(atr, asset_class="index", adaptive=False)
        assert len(sl) == 60
        assert len(tp) == 60

    def test_values_positive(self):
        atr = pd.Series([5.0] * 60)
        sl, tp = compute_sl_tp_series(atr, asset_class="forex", adaptive=False)
        assert (sl > 0).all()
        assert (tp > 0).all()


# ---------------------------------------------------------------------------
# label_bar (integration)
# ---------------------------------------------------------------------------

class TestLabelBar:
    def test_returns_regime_and_labels(self):
        df = _make_ohlcv_with_indicators(100)
        # Pick a bar after warmup where indicators are computed
        bar = 80
        regime, labels, adx_val = label_bar(df, bar)
        assert isinstance(regime, Regime)
        assert isinstance(labels, list)
        assert len(labels) > 0
        for name, lbl in labels:
            assert lbl.label in ("BULLISH", "BEARISH", "NEUTRAL")

    def test_early_bar_has_no_crash(self):
        """Bars before warmup should produce empty or minimal labels (no crash)."""
        df = _make_ohlcv_with_indicators(100)
        regime, labels, adx_val = label_bar(df, 5)
        assert isinstance(regime, Regime)


# ---------------------------------------------------------------------------
# Composite + QS integration (round-trip)
# ---------------------------------------------------------------------------

class TestStrategyIntegration:
    def test_full_pipeline(self):
        """Run the full labeling→composite→QS pipeline on synthetic data."""
        df = _make_ohlcv_with_indicators(200)

        for i in range(60, 200):
            regime, labels, adx_val = label_bar(df, i)
            direction, confidence = compute_composite(labels, regime, adx_filter=adx_val)
            qs = compute_quality_score(
                df, i, direction,
                adx_value=adx_val,
                labels=labels,
            )
            assert direction in ("BULLISH", "BEARISH", "NEUTRAL")
            assert 0 <= qs.total <= 5
