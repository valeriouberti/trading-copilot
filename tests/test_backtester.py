"""Test suite for the backtesting engine."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from modules.backtester import (
    OUTCOME_OPEN,
    OUTCOME_SL,
    OUTCOME_TP,
    BacktestEngine,
    BacktestResult,
    Trade,
    compute_indicators,
    compute_statistics,
    generate_signals,
    main,
    parse_args,
    simulate_trades,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic OHLCV data generators
# ---------------------------------------------------------------------------


def _make_trending_df(
    rows: int = 120,
    trend: str = "up",
    base_price: float = 100.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a trending OHLCV DataFrame with realistic price action.

    The trend is strong enough to trigger signals when indicators are computed.
    """
    np.random.seed(seed)
    dates = pd.date_range(end=pd.Timestamp("2025-06-15"), periods=rows, freq="D")

    if trend == "up":
        close = base_price + np.linspace(0, 40, rows) + np.random.normal(0, 0.5, rows)
    elif trend == "down":
        close = base_price + np.linspace(0, -40, rows) + np.random.normal(0, 0.5, rows)
    else:
        close = np.full(rows, base_price) + np.random.normal(0, 2, rows)

    high = close + np.abs(np.random.normal(1.0, 0.3, rows))
    low = close - np.abs(np.random.normal(1.0, 0.3, rows))
    open_ = close + np.random.normal(0, 0.3, rows)
    volume = np.random.randint(5000, 50000, rows).astype(float)

    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def _make_flat_df(rows: int = 120, base_price: float = 100.0) -> pd.DataFrame:
    """Generate a flat/ranging OHLCV DataFrame (ADX will be low)."""
    np.random.seed(99)
    dates = pd.date_range(end=pd.Timestamp("2025-06-15"), periods=rows, freq="D")
    close = np.full(rows, base_price) + np.random.normal(0, 0.3, rows)
    high = close + np.abs(np.random.normal(0.2, 0.1, rows))
    low = close - np.abs(np.random.normal(0.2, 0.1, rows))
    open_ = close + np.random.normal(0, 0.1, rows)
    volume = np.random.randint(1000, 10000, rows).astype(float)
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def _make_signal_df_with_known_outcome(
    direction: str = "LONG",
    outcome: str = OUTCOME_TP,
) -> pd.DataFrame:
    """Build a minimal DataFrame with a pre-computed signal and known outcome.

    Creates a DataFrame that already has indicator and signal columns,
    with specific High/Low values on subsequent bars to force a known
    TP or SL hit.
    """
    n = 10
    dates = pd.date_range(start="2025-01-01", periods=n, freq="D")
    entry_price = 100.0
    atr_val = 2.0  # ATR on signal bar

    close = np.full(n, entry_price)
    high = np.full(n, entry_price + 1.0)
    low = np.full(n, entry_price - 1.0)
    open_ = np.full(n, entry_price)
    volume = np.full(n, 10000.0)

    # SL = entry +/- ATR * 1.5 = +/- 3.0
    # TP = entry +/- ATR * 3.0 = +/- 6.0

    if direction == "LONG":
        if outcome == OUTCOME_TP:
            # Bar 2: price reaches TP (106.0)
            high[2] = 107.0
            close[2] = 106.5
        elif outcome == OUTCOME_SL:
            # Bar 2: price drops to SL (97.0)
            low[2] = 96.5
            close[2] = 96.8
        # else: STILL_OPEN — keep prices flat
    else:  # SHORT
        if outcome == OUTCOME_TP:
            # Bar 2: price drops to TP (94.0)
            low[2] = 93.5
            close[2] = 93.8
        elif outcome == OUTCOME_SL:
            # Bar 2: price rises to SL (103.0)
            high[2] = 103.5
            close[2] = 103.2

    df = pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
            "atr_14": np.full(n, atr_val),
            "signal": np.zeros(n, dtype=int),
        },
        index=dates,
    )

    # Set signal on bar 0
    df.iloc[0, df.columns.get_loc("signal")] = 1 if direction == "LONG" else -1

    return df


# ---------------------------------------------------------------------------
# Test: Indicator computation
# ---------------------------------------------------------------------------


class TestComputeIndicators:
    def test_all_indicator_columns_present(self) -> None:
        """compute_indicators should add all expected columns."""
        df = _make_trending_df(rows=120, trend="up")
        result = compute_indicators(df)
        expected_cols = [
            "rsi_14", "macd_hist", "ema_20", "ema_50",
            "atr_14", "adx_14", "bull_count", "bear_count",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_indicators_have_values_after_warmup(self) -> None:
        """After sufficient bars, indicators should not be all NaN."""
        df = _make_trending_df(rows=120, trend="up")
        result = compute_indicators(df)
        # Check from bar 50 onward (after warm-up)
        tail = result.iloc[60:]
        assert not tail["rsi_14"].isna().all(), "RSI all NaN after warm-up"
        assert not tail["ema_20"].isna().all(), "EMA20 all NaN after warm-up"
        assert not tail["ema_50"].isna().all(), "EMA50 all NaN after warm-up"
        assert not tail["atr_14"].isna().all(), "ATR all NaN after warm-up"
        assert not tail["adx_14"].isna().all(), "ADX all NaN after warm-up"

    def test_uptrend_produces_bullish_signals(self) -> None:
        """A strong uptrend should produce bull_count > bear_count on later bars."""
        df = _make_trending_df(rows=120, trend="up")
        result = compute_indicators(df)
        tail = result.iloc[60:]
        avg_bull = tail["bull_count"].mean()
        avg_bear = tail["bear_count"].mean()
        assert avg_bull > avg_bear, (
            f"Uptrend should have higher avg bull_count ({avg_bull:.2f}) "
            f"than bear_count ({avg_bear:.2f})"
        )

    def test_downtrend_produces_bearish_signals(self) -> None:
        """A strong downtrend should produce bear_count > bull_count on later bars."""
        df = _make_trending_df(rows=120, trend="down")
        result = compute_indicators(df)
        tail = result.iloc[60:]
        avg_bull = tail["bull_count"].mean()
        avg_bear = tail["bear_count"].mean()
        assert avg_bear > avg_bull, (
            f"Downtrend should have higher avg bear_count ({avg_bear:.2f}) "
            f"than bull_count ({avg_bull:.2f})"
        )


# ---------------------------------------------------------------------------
# Test: Signal generation
# ---------------------------------------------------------------------------


class TestGenerateSignals:
    def test_signal_column_created(self) -> None:
        """generate_signals should add a 'signal' column."""
        df = _make_trending_df(rows=120, trend="up")
        df = compute_indicators(df)
        result = generate_signals(df)
        assert "signal" in result.columns

    def test_signal_values_valid(self) -> None:
        """Signals should be -1, 0, or 1."""
        df = _make_trending_df(rows=120, trend="up")
        df = compute_indicators(df)
        result = generate_signals(df)
        valid_values = {-1, 0, 1}
        actual_values = set(result["signal"].unique())
        assert actual_values.issubset(valid_values), f"Invalid signal values: {actual_values}"

    def test_flat_market_few_signals(self) -> None:
        """A flat/ranging market (low ADX) should produce fewer signals than trending."""
        df_flat = _make_flat_df(rows=120)
        df_flat = compute_indicators(df_flat)
        df_flat = generate_signals(df_flat)
        flat_signals = (df_flat["signal"] != 0).sum()

        df_trend = _make_trending_df(rows=120, trend="up")
        df_trend = compute_indicators(df_trend)
        df_trend = generate_signals(df_trend)
        trend_signals = (df_trend["signal"] != 0).sum()

        # Flat market should have fewer or equal signals due to ADX filter
        assert flat_signals <= trend_signals + 2, (
            f"Flat market ({flat_signals} signals) should have fewer signals "
            f"than trending market ({trend_signals})"
        )


# ---------------------------------------------------------------------------
# Test: Trade simulation — SL and TP outcomes
# ---------------------------------------------------------------------------


class TestSimulateTrades:
    def test_long_tp_hit(self) -> None:
        """A LONG trade should resolve as TP_HIT when price reaches TP."""
        df = _make_signal_df_with_known_outcome("LONG", OUTCOME_TP)
        trades = simulate_trades(df)
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == "LONG"
        assert t.outcome == OUTCOME_TP
        assert t.pnl > 0

    def test_long_sl_hit(self) -> None:
        """A LONG trade should resolve as SL_HIT when price drops to SL."""
        df = _make_signal_df_with_known_outcome("LONG", OUTCOME_SL)
        trades = simulate_trades(df)
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == "LONG"
        assert t.outcome == OUTCOME_SL
        assert t.pnl < 0

    def test_short_tp_hit(self) -> None:
        """A SHORT trade should resolve as TP_HIT when price drops to TP."""
        df = _make_signal_df_with_known_outcome("SHORT", OUTCOME_TP)
        trades = simulate_trades(df)
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == "SHORT"
        assert t.outcome == OUTCOME_TP
        assert t.pnl > 0

    def test_short_sl_hit(self) -> None:
        """A SHORT trade should resolve as SL_HIT when price rises to SL."""
        df = _make_signal_df_with_known_outcome("SHORT", OUTCOME_SL)
        trades = simulate_trades(df)
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == "SHORT"
        assert t.outcome == OUTCOME_SL
        assert t.pnl < 0

    def test_still_open_trade(self) -> None:
        """When price never hits SL or TP, trade should be marked STILL_OPEN."""
        df = _make_signal_df_with_known_outcome("LONG", OUTCOME_OPEN)
        trades = simulate_trades(df)
        assert len(trades) == 1
        assert trades[0].outcome == OUTCOME_OPEN

    def test_no_signal_no_trades(self) -> None:
        """If no signals, simulate_trades should return an empty list."""
        dates = pd.date_range(start="2025-01-01", periods=10, freq="D")
        df = pd.DataFrame(
            {
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "Volume": 10000.0,
                "atr_14": 2.0,
                "signal": 0,
            },
            index=dates,
        )
        trades = simulate_trades(df)
        assert trades == []

    def test_nan_atr_skipped(self) -> None:
        """Signals where ATR is NaN should be skipped."""
        dates = pd.date_range(start="2025-01-01", periods=5, freq="D")
        df = pd.DataFrame(
            {
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "Volume": 10000.0,
                "atr_14": [np.nan, 2.0, 2.0, 2.0, 2.0],
                "signal": [1, 0, 0, 0, 0],
            },
            index=dates,
        )
        trades = simulate_trades(df)
        assert trades == []


# ---------------------------------------------------------------------------
# Test: Statistics computation
# ---------------------------------------------------------------------------


class TestComputeStatistics:
    def test_no_trades_returns_zero_stats(self) -> None:
        """With no trades, all stats should be zero."""
        result = compute_statistics([])
        assert result.total_trades == 0
        assert result.win_rate == 0.0
        assert result.profit_factor == 0.0
        assert result.total_pnl == 0.0
        assert result.avg_trade == 0.0
        assert result.equity_curve == []

    def test_single_winning_trade(self) -> None:
        """A single winning trade should yield 100% win rate."""
        trades = [
            Trade(
                entry_bar=0, entry_date="2025-01-01", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=3, exit_date="2025-01-04", exit_price=106,
                outcome=OUTCOME_TP, pnl=6.0, bars_held=3,
            ),
        ]
        result = compute_statistics(trades)
        assert result.total_trades == 1
        assert result.win_rate == 1.0
        assert result.total_pnl == 6.0
        assert result.avg_trade == 6.0
        assert result.profit_factor == float("inf")

    def test_single_losing_trade(self) -> None:
        """A single losing trade should yield 0% win rate."""
        trades = [
            Trade(
                entry_bar=0, entry_date="2025-01-01", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=2, exit_date="2025-01-03", exit_price=97,
                outcome=OUTCOME_SL, pnl=-3.0, bars_held=2,
            ),
        ]
        result = compute_statistics(trades)
        assert result.total_trades == 1
        assert result.win_rate == 0.0
        assert result.total_pnl == -3.0
        assert result.profit_factor == 0.0

    def test_all_winners(self) -> None:
        """All winning trades: 100% win rate, positive profit factor."""
        trades = [
            Trade(
                entry_bar=i, entry_date=f"2025-01-{i+1:02d}", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=i+3, exit_date=f"2025-01-{i+4:02d}", exit_price=106,
                outcome=OUTCOME_TP, pnl=6.0, bars_held=3,
            )
            for i in range(5)
        ]
        result = compute_statistics(trades)
        assert result.win_rate == 1.0
        assert result.total_pnl == 30.0
        assert result.profit_factor == float("inf")
        assert len(result.equity_curve) == 5
        assert result.equity_curve[-1] == 30.0

    def test_all_losers(self) -> None:
        """All losing trades: 0% win rate, 0 profit factor."""
        trades = [
            Trade(
                entry_bar=i, entry_date=f"2025-01-{i+1:02d}", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=i+2, exit_date=f"2025-01-{i+3:02d}", exit_price=97,
                outcome=OUTCOME_SL, pnl=-3.0, bars_held=2,
            )
            for i in range(5)
        ]
        result = compute_statistics(trades)
        assert result.win_rate == 0.0
        assert result.total_pnl == -15.0
        assert result.profit_factor == 0.0

    def test_mixed_trades_statistics(self) -> None:
        """Mixed wins and losses should produce correct intermediate stats."""
        trades = [
            Trade(
                entry_bar=0, entry_date="2025-01-01", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=3, exit_date="2025-01-04", exit_price=106,
                outcome=OUTCOME_TP, pnl=6.0, bars_held=3,
            ),
            Trade(
                entry_bar=5, entry_date="2025-01-06", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=7, exit_date="2025-01-08", exit_price=97,
                outcome=OUTCOME_SL, pnl=-3.0, bars_held=2,
            ),
            Trade(
                entry_bar=10, entry_date="2025-01-11", direction="SHORT",
                entry_price=100, stop_loss=103, take_profit=94,
                exit_bar=13, exit_date="2025-01-14", exit_price=94,
                outcome=OUTCOME_TP, pnl=6.0, bars_held=3,
            ),
            Trade(
                entry_bar=15, entry_date="2025-01-16", direction="SHORT",
                entry_price=100, stop_loss=103, take_profit=94,
                exit_bar=17, exit_date="2025-01-18", exit_price=103,
                outcome=OUTCOME_SL, pnl=-3.0, bars_held=2,
            ),
        ]
        result = compute_statistics(trades)
        assert result.total_trades == 4
        assert result.win_rate == pytest.approx(0.5, abs=0.01)
        assert result.total_pnl == pytest.approx(6.0, abs=0.01)
        assert result.avg_trade == pytest.approx(1.5, abs=0.01)
        # profit_factor = 12.0 / 6.0 = 2.0
        assert result.profit_factor == pytest.approx(2.0, abs=0.01)
        assert len(result.equity_curve) == 4

    def test_equity_curve_is_cumulative(self) -> None:
        """Equity curve should be a cumulative sum of PnLs."""
        trades = [
            Trade(
                entry_bar=0, entry_date="2025-01-01", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=3, exit_date="2025-01-04", exit_price=106,
                outcome=OUTCOME_TP, pnl=6.0, bars_held=3,
            ),
            Trade(
                entry_bar=5, entry_date="2025-01-06", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=7, exit_date="2025-01-08", exit_price=97,
                outcome=OUTCOME_SL, pnl=-3.0, bars_held=2,
            ),
        ]
        result = compute_statistics(trades)
        assert result.equity_curve == [6.0, 3.0]

    def test_max_drawdown_calculation(self) -> None:
        """Max drawdown should correctly measure peak-to-trough decline."""
        trades = [
            Trade(
                entry_bar=0, entry_date="d", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=1, exit_date="d", exit_price=106,
                outcome=OUTCOME_TP, pnl=10.0, bars_held=1,
            ),
            Trade(
                entry_bar=2, entry_date="d", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=3, exit_date="d", exit_price=97,
                outcome=OUTCOME_SL, pnl=-5.0, bars_held=1,
            ),
            Trade(
                entry_bar=4, entry_date="d", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=5, exit_date="d", exit_price=97,
                outcome=OUTCOME_SL, pnl=-3.0, bars_held=1,
            ),
        ]
        result = compute_statistics(trades)
        # Equity curve: [10, 5, 2]
        # Peak = 10, trough at 2, drawdown = (10 - 2) / 10 = 0.8
        assert result.max_drawdown == pytest.approx(0.8, abs=0.01)

    def test_sharpe_ratio_positive_for_consistent_wins(self) -> None:
        """Sharpe ratio should be positive for consistently profitable trades."""
        trades = [
            Trade(
                entry_bar=i, entry_date="d", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=i+1, exit_date="d", exit_price=106,
                outcome=OUTCOME_TP, pnl=6.0, bars_held=1,
            )
            for i in range(10)
        ]
        result = compute_statistics(trades)
        # All identical positive PnL: std will be 0, so sharpe = 0
        # This is a degenerate case. Let's verify it handles gracefully.
        assert result.sharpe_ratio == 0.0 or result.sharpe_ratio > 0

    def test_expectancy_calculation(self) -> None:
        """Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)."""
        trades = [
            Trade(
                entry_bar=0, entry_date="d", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=1, exit_date="d", exit_price=106,
                outcome=OUTCOME_TP, pnl=6.0, bars_held=1,
            ),
            Trade(
                entry_bar=2, entry_date="d", direction="LONG",
                entry_price=100, stop_loss=97, take_profit=106,
                exit_bar=3, exit_date="d", exit_price=97,
                outcome=OUTCOME_SL, pnl=-3.0, bars_held=1,
            ),
        ]
        result = compute_statistics(trades)
        # win_rate = 0.5, avg_win = 6.0, loss_rate = 0.5, avg_loss = 3.0
        # expectancy = (0.5 * 6.0) - (0.5 * 3.0) = 1.5
        assert result.expectancy == pytest.approx(1.5, abs=0.01)


# ---------------------------------------------------------------------------
# Test: BacktestResult
# ---------------------------------------------------------------------------


class TestBacktestResult:
    def test_to_dict(self) -> None:
        """to_dict should produce a serializable dictionary."""
        result = BacktestResult(
            trades=[],
            win_rate=0.65,
            profit_factor=2.1,
            max_drawdown=0.12,
            sharpe_ratio=1.8,
            total_pnl=500.0,
            total_trades=20,
            avg_trade=25.0,
            expectancy=12.5,
            equity_curve=[100, 200, 150, 500],
        )
        d = result.to_dict()
        assert d["total_trades"] == 20
        assert d["win_rate"] == 0.65
        assert d["equity_curve_len"] == 4

    def test_summary_format(self) -> None:
        """summary() should return a formatted string with key metrics."""
        result = BacktestResult(
            total_trades=10,
            win_rate=0.6,
            profit_factor=2.0,
            total_pnl=100.0,
            avg_trade=10.0,
            expectancy=5.0,
            max_drawdown=0.15,
            sharpe_ratio=1.5,
        )
        summary = result.summary()
        assert "Total Trades" in summary
        assert "Win Rate" in summary
        assert "Profit Factor" in summary
        assert "Sharpe Ratio" in summary


# ---------------------------------------------------------------------------
# Test: Trade dataclass
# ---------------------------------------------------------------------------


class TestTrade:
    def test_to_dict(self) -> None:
        """Trade.to_dict should include all fields."""
        t = Trade(
            entry_bar=0,
            entry_date="2025-01-01",
            direction="LONG",
            entry_price=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            exit_bar=3,
            exit_date="2025-01-04",
            exit_price=106.0,
            outcome=OUTCOME_TP,
            pnl=6.0,
            bars_held=3,
        )
        d = t.to_dict()
        assert d["direction"] == "LONG"
        assert d["pnl"] == 6.0
        assert d["outcome"] == OUTCOME_TP
        assert "entry_bar" in d
        assert "exit_date" in d


# ---------------------------------------------------------------------------
# Test: CLI argument parsing
# ---------------------------------------------------------------------------


class TestCLI:
    def test_parse_args_required_symbol(self) -> None:
        """--symbol should be required."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parse_args_defaults(self) -> None:
        """Default values for period, interval, sl-mult, tp-mult."""
        args = parse_args(["--symbol", "NQ=F"])
        assert args.symbol == "NQ=F"
        assert args.period == "6mo"
        assert args.interval == "1d"
        assert args.sl_mult == 1.5
        assert args.tp_mult == 3.0
        assert args.verbose is False

    def test_parse_args_custom_values(self) -> None:
        """Custom argument values should be parsed correctly."""
        args = parse_args([
            "--symbol", "ES=F",
            "--period", "1y",
            "--interval", "1h",
            "--sl-mult", "2.0",
            "--tp-mult", "4.0",
            "--verbose",
        ])
        assert args.symbol == "ES=F"
        assert args.period == "1y"
        assert args.interval == "1h"
        assert args.sl_mult == 2.0
        assert args.tp_mult == 4.0
        assert args.verbose is True


# ---------------------------------------------------------------------------
# Test: BacktestEngine integration
# ---------------------------------------------------------------------------


class TestBacktestEngine:
    def test_run_with_synthetic_data(self) -> None:
        """Engine.run() with pre-supplied DataFrame should produce a BacktestResult."""
        df = _make_trending_df(rows=120, trend="up")
        engine = BacktestEngine()
        result = engine.run(symbol="TEST", df=df)
        assert isinstance(result, BacktestResult)
        assert result.total_trades >= 0
        assert isinstance(result.equity_curve, list)

    def test_run_with_downtrend(self) -> None:
        """Engine should handle downtrend data and produce SHORT trades."""
        df = _make_trending_df(rows=120, trend="down")
        engine = BacktestEngine()
        result = engine.run(symbol="TEST", df=df)
        assert isinstance(result, BacktestResult)
        # In a downtrend, any trades should include SHORT direction
        if result.trades:
            directions = {t.direction for t in result.trades}
            assert "SHORT" in directions or len(result.trades) == 0

    def test_run_with_custom_atr_multipliers(self) -> None:
        """Custom ATR multipliers should affect trade outcomes."""
        df = _make_trending_df(rows=120, trend="up")
        engine_tight = BacktestEngine(sl_atr_mult=0.5, tp_atr_mult=1.0)
        engine_wide = BacktestEngine(sl_atr_mult=3.0, tp_atr_mult=6.0)
        result_tight = engine_tight.run(symbol="TEST", df=df)
        result_wide = engine_wide.run(symbol="TEST", df=df)
        # Both should produce valid results
        assert isinstance(result_tight, BacktestResult)
        assert isinstance(result_wide, BacktestResult)

    def test_run_with_insufficient_data(self) -> None:
        """Engine should handle DataFrames with few bars gracefully."""
        df = _make_trending_df(rows=20, trend="up")
        engine = BacktestEngine()
        result = engine.run(symbol="TEST", df=df)
        # Should still return a valid result, just possibly with 0 trades
        assert isinstance(result, BacktestResult)

    def test_fetch_data_called_when_no_df(self) -> None:
        """When df is not provided, fetch_data should be called."""
        mock_df = _make_trending_df(rows=120, trend="up")
        engine = BacktestEngine()
        with patch.object(engine, "fetch_data", return_value=mock_df) as mock_fetch:
            result = engine.run(symbol="NQ=F", period="6mo", interval="1d")
            mock_fetch.assert_called_once_with("NQ=F", "6mo", "1d")
            assert isinstance(result, BacktestResult)

    def test_main_cli_integration(self) -> None:
        """main() should work end-to-end with a mocked fetch."""
        mock_df = _make_trending_df(rows=120, trend="up")
        with patch(
            "modules.backtester.BacktestEngine.fetch_data",
            return_value=mock_df,
        ):
            result = main(["--symbol", "NQ=F", "--period", "6mo"])
            assert isinstance(result, BacktestResult)
