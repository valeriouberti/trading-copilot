"""Backtesting engine for the trading assistant.

Replays historical signals using the same indicators as the live system
(RSI, MACD, EMA20/EMA50, ATR, ADX) and evaluates ATR-based SL/TP outcomes.
Uses a vectorized pandas approach for performance.

Usage (CLI):
    python -m modules.backtester --symbol NQ=F --period 6mo
    python -m modules.backtester --symbol ES=F --period 1y --interval 1d
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trade outcome constants
# ---------------------------------------------------------------------------

OUTCOME_TP = "TP_HIT"
OUTCOME_SL = "SL_HIT"
OUTCOME_OPEN = "STILL_OPEN"

# Default ATR multipliers for stop-loss and take-profit
DEFAULT_SL_ATR_MULT = 1.5
DEFAULT_TP_ATR_MULT = 3.0

# Minimum number of bars required for indicator warm-up
MIN_BARS_WARMUP = 50


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Trade:
    """A single backtest trade record."""

    entry_bar: int
    entry_date: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_bar: int | None = None
    exit_date: str | None = None
    exit_price: float | None = None
    outcome: str = OUTCOME_OPEN  # TP_HIT, SL_HIT, STILL_OPEN
    pnl: float = 0.0
    bars_held: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_bar": self.entry_bar,
            "entry_date": self.entry_date,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "exit_bar": self.exit_bar,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "outcome": self.outcome,
            "pnl": self.pnl,
            "bars_held": self.bars_held,
        }


@dataclass
class BacktestResult:
    """Comprehensive backtest result with trade statistics."""

    trades: list[Trade] = field(default_factory=list)
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    total_pnl: float = 0.0
    total_trades: int = 0
    avg_trade: float = 0.0
    expectancy: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    kelly_fraction: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "total_pnl": round(self.total_pnl, 4),
            "avg_trade": round(self.avg_trade, 4),
            "expectancy": round(self.expectancy, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "equity_curve_len": len(self.equity_curve),
            "trades": [t.to_dict() for t in self.trades],
        }

    def summary(self) -> str:
        """Human-readable summary of the backtest."""
        lines = [
            "=" * 60,
            "BACKTEST RESULTS",
            "=" * 60,
            f"  Total Trades:   {self.total_trades}",
            f"  Win Rate:       {self.win_rate:.1%}",
            f"  Profit Factor:  {self.profit_factor:.2f}",
            f"  Total PnL:      {self.total_pnl:+.2f}",
            f"  Avg Trade:      {self.avg_trade:+.2f}",
            f"  Expectancy:     {self.expectancy:+.4f}",
            f"  Max Drawdown:   {self.max_drawdown:.2%}",
            f"  Sharpe Ratio:   {self.sharpe_ratio:.2f}",
            "=" * 60,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Indicator computation (vectorized)
# ---------------------------------------------------------------------------


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators on an OHLCV DataFrame.

    Adds columns: rsi_14, macd_hist, ema_20, ema_50, atr_14, adx_14,
    plus intermediate signal columns for composite scoring.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain Open, High, Low, Close, Volume columns.

    Returns
    -------
    pd.DataFrame
        Original DataFrame augmented with indicator columns.
    """
    df = df.copy()

    # RSI(14)
    rsi = ta.rsi(df["Close"], length=14)
    df["rsi_14"] = rsi if rsi is not None else np.nan

    # MACD(12, 26, 9)
    macd_df = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        hist_col = [c for c in macd_df.columns if "h" in c.lower() or "MACD" in c]
        # pandas-ta returns MACDh_12_26_9 for histogram
        hist_cols = [c for c in macd_df.columns if c.startswith("MACDh_")]
        if hist_cols:
            df["macd_hist"] = macd_df[hist_cols[0]].values
        else:
            # Fallback: take the third column (histogram)
            df["macd_hist"] = macd_df.iloc[:, -1].values
    else:
        df["macd_hist"] = np.nan

    # EMA(20) and EMA(50)
    ema20 = ta.ema(df["Close"], length=20)
    ema50 = ta.ema(df["Close"], length=50)
    df["ema_20"] = ema20 if ema20 is not None else np.nan
    df["ema_50"] = ema50 if ema50 is not None else np.nan

    # ATR(14)
    atr = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    df["atr_14"] = atr if atr is not None else np.nan

    # ADX(14)
    adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    if adx_df is not None and not adx_df.empty:
        adx_cols = [c for c in adx_df.columns if c.startswith("ADX_")]
        if adx_cols:
            df["adx_14"] = adx_df[adx_cols[0]].values
        else:
            df["adx_14"] = np.nan
    else:
        df["adx_14"] = np.nan

    # Derive directional labels per bar (vectorized)
    df["rsi_bull"] = (df["rsi_14"] > 50) & (df["rsi_14"] < 75)
    df["rsi_bear"] = (df["rsi_14"] < 50) & (df["rsi_14"] > 25)
    df["macd_bull"] = df["macd_hist"] > 0
    df["macd_bear"] = df["macd_hist"] < 0
    df["ema_bull"] = df["ema_20"] > df["ema_50"]
    df["ema_bear"] = df["ema_20"] < df["ema_50"]

    # Composite bullish / bearish counts (out of 3 core directional indicators)
    df["bull_count"] = (
        df["rsi_bull"].astype(int)
        + df["macd_bull"].astype(int)
        + df["ema_bull"].astype(int)
    )
    df["bear_count"] = (
        df["rsi_bear"].astype(int)
        + df["macd_bear"].astype(int)
        + df["ema_bear"].astype(int)
    )

    return df


# ---------------------------------------------------------------------------
# Signal generation (vectorized)
# ---------------------------------------------------------------------------


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Generate trade signals from indicator columns.

    A signal fires when:
    - Composite score is strongly directional (bull_count >= 3 OR bear_count >= 3)
      meaning all 3 of RSI, MACD, EMA agree on direction
    - ADX > 25 (strong trend)

    Adds a 'signal' column: 1 = LONG, -1 = SHORT, 0 = no signal.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain indicator columns from ``compute_indicators()``.

    Returns
    -------
    pd.DataFrame
        DataFrame with 'signal' column added.
    """
    df = df.copy()
    df["signal"] = 0

    # Strong trend filter
    adx_strong = df["adx_14"] > 25

    # Bullish signal: all 3 indicators agree + ADX strong
    long_mask = (df["bull_count"] >= 3) & adx_strong
    # Bearish signal: all 3 indicators agree + ADX strong
    short_mask = (df["bear_count"] >= 3) & adx_strong

    df.loc[long_mask, "signal"] = 1
    df.loc[short_mask, "signal"] = -1

    # Avoid overlapping signals: if both somehow fire, prefer the stronger count
    both_mask = long_mask & short_mask
    if both_mask.any():
        prefer_long = df["bull_count"] > df["bear_count"]
        df.loc[both_mask & prefer_long, "signal"] = 1
        df.loc[both_mask & ~prefer_long, "signal"] = -1

    # Only fire on the first bar of a signal run (de-duplicate consecutive signals)
    df["signal_change"] = df["signal"].diff().fillna(df["signal"])
    df.loc[df["signal_change"] == 0, "signal"] = 0
    df.drop(columns=["signal_change"], inplace=True)

    return df


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------


def simulate_trades(
    df: pd.DataFrame,
    sl_atr_mult: float = DEFAULT_SL_ATR_MULT,
    tp_atr_mult: float = DEFAULT_TP_ATR_MULT,
) -> list[Trade]:
    """Walk through signals and simulate trade outcomes.

    For each signal bar:
    - Entry at bar's Close
    - SL = ATR * sl_atr_mult away from entry
    - TP = ATR * tp_atr_mult away from entry
    - Walk forward through subsequent bars checking if High/Low hits SL/TP

    Parameters
    ----------
    df : pd.DataFrame
        Must contain signal, Close, High, Low, atr_14 columns.
    sl_atr_mult : float
        ATR multiplier for stop-loss distance.
    tp_atr_mult : float
        ATR multiplier for take-profit distance.

    Returns
    -------
    list[Trade]
        List of completed or still-open trades.
    """
    trades: list[Trade] = []
    signal_bars = df.index[df["signal"] != 0]

    for sig_idx in signal_bars:
        bar_pos = df.index.get_loc(sig_idx)
        row = df.loc[sig_idx]

        direction_val = int(row["signal"])
        entry_price = float(row["Close"])
        atr_val = float(row["atr_14"])

        if pd.isna(atr_val) or atr_val <= 0:
            continue

        direction = "LONG" if direction_val == 1 else "SHORT"

        if direction == "LONG":
            sl = entry_price - atr_val * sl_atr_mult
            tp = entry_price + atr_val * tp_atr_mult
        else:
            sl = entry_price + atr_val * sl_atr_mult
            tp = entry_price - atr_val * tp_atr_mult

        entry_date = (
            sig_idx.strftime("%Y-%m-%d %H:%M")
            if hasattr(sig_idx, "strftime")
            else str(sig_idx)
        )

        trade = Trade(
            entry_bar=bar_pos,
            entry_date=entry_date,
            direction=direction,
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
        )

        # Walk forward to find outcome
        remaining = df.iloc[bar_pos + 1:]
        for future_idx, future_row in remaining.iterrows():
            future_pos = df.index.get_loc(future_idx)
            high = float(future_row["High"])
            low = float(future_row["Low"])

            if direction == "LONG":
                # Check SL first (conservative: assume worst case within bar)
                if low <= sl:
                    trade.outcome = OUTCOME_SL
                    trade.exit_price = sl
                    trade.pnl = sl - entry_price
                    trade.exit_bar = future_pos
                    trade.exit_date = (
                        future_idx.strftime("%Y-%m-%d %H:%M")
                        if hasattr(future_idx, "strftime")
                        else str(future_idx)
                    )
                    trade.bars_held = future_pos - bar_pos
                    break
                if high >= tp:
                    trade.outcome = OUTCOME_TP
                    trade.exit_price = tp
                    trade.pnl = tp - entry_price
                    trade.exit_bar = future_pos
                    trade.exit_date = (
                        future_idx.strftime("%Y-%m-%d %H:%M")
                        if hasattr(future_idx, "strftime")
                        else str(future_idx)
                    )
                    trade.bars_held = future_pos - bar_pos
                    break
            else:  # SHORT
                if high >= sl:
                    trade.outcome = OUTCOME_SL
                    trade.exit_price = sl
                    trade.pnl = entry_price - sl
                    trade.exit_bar = future_pos
                    trade.exit_date = (
                        future_idx.strftime("%Y-%m-%d %H:%M")
                        if hasattr(future_idx, "strftime")
                        else str(future_idx)
                    )
                    trade.bars_held = future_pos - bar_pos
                    break
                if low <= tp:
                    trade.outcome = OUTCOME_TP
                    trade.exit_price = tp
                    trade.pnl = entry_price - tp
                    trade.exit_bar = future_pos
                    trade.exit_date = (
                        future_idx.strftime("%Y-%m-%d %H:%M")
                        if hasattr(future_idx, "strftime")
                        else str(future_idx)
                    )
                    trade.bars_held = future_pos - bar_pos
                    break

        # If still open, mark PnL to the last close
        if trade.outcome == OUTCOME_OPEN:
            last_close = float(df["Close"].iloc[-1])
            if direction == "LONG":
                trade.pnl = last_close - entry_price
            else:
                trade.pnl = entry_price - last_close
            trade.exit_price = last_close
            trade.exit_bar = len(df) - 1
            trade.exit_date = (
                df.index[-1].strftime("%Y-%m-%d %H:%M")
                if hasattr(df.index[-1], "strftime")
                else str(df.index[-1])
            )
            trade.bars_held = len(df) - 1 - bar_pos

        trades.append(trade)

    return trades


# ---------------------------------------------------------------------------
# Statistics computation
# ---------------------------------------------------------------------------


def compute_statistics(trades: list[Trade]) -> BacktestResult:
    """Compute comprehensive backtest statistics from a list of trades.

    Parameters
    ----------
    trades : list[Trade]
        The trade records from ``simulate_trades()``.

    Returns
    -------
    BacktestResult
        Full statistics including equity curve.
    """
    result = BacktestResult(trades=trades, total_trades=len(trades))

    if not trades:
        return result

    pnls = [t.pnl for t in trades]
    result.total_pnl = sum(pnls)
    result.avg_trade = result.total_pnl / len(trades)

    # Equity curve
    equity = []
    running = 0.0
    for p in pnls:
        running += p
        equity.append(running)
    result.equity_curve = equity

    # Win rate (only count resolved trades)
    resolved = [t for t in trades if t.outcome != OUTCOME_OPEN]
    if resolved:
        winners = [t for t in resolved if t.pnl > 0]
        result.win_rate = len(winners) / len(resolved)
    else:
        result.win_rate = 0.0

    # Profit factor = gross profit / gross loss
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss > 0:
        result.profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        result.profit_factor = float("inf")
    else:
        result.profit_factor = 0.0

    # Max drawdown (from equity curve)
    if equity:
        peak = equity[0]
        max_dd = 0.0
        for eq in equity:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                max_dd = max(max_dd, dd)
            elif peak == 0 and eq < 0:
                # Handle case where peak is 0 — use absolute drawdown
                max_dd = max(max_dd, abs(eq))
        result.max_drawdown = max_dd

    # Sharpe ratio (annualized, assuming daily trades)
    if len(pnls) >= 2:
        pnl_array = np.array(pnls)
        mean_pnl = float(np.mean(pnl_array))
        std_pnl = float(np.std(pnl_array, ddof=1))
        if std_pnl > 0:
            result.sharpe_ratio = (mean_pnl / std_pnl) * math.sqrt(252)
        else:
            result.sharpe_ratio = 0.0
    else:
        result.sharpe_ratio = 0.0

    # Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    avg_win = sum(winners) / len(winners) if winners else 0.0
    avg_loss = abs(sum(losers) / len(losers)) if losers else 0.0
    win_r = len(winners) / len(pnls) if pnls else 0.0
    loss_r = len(losers) / len(pnls) if pnls else 0.0
    result.expectancy = (win_r * avg_win) - (loss_r * avg_loss)

    # Kelly criterion
    result.kelly_fraction = kelly_position_size(win_r, avg_win, avg_loss)

    return result


def kelly_position_size(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Compute the half-Kelly position size fraction.

    Kelly fraction = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win

    The result is capped at half-Kelly (max 0.5) for safety and floored at 0.

    Parameters
    ----------
    win_rate : float
        Probability of winning (0-1).
    avg_win : float
        Average winning trade PnL (positive).
    avg_loss : float
        Average losing trade PnL (positive magnitude).

    Returns
    -------
    float
        Kelly fraction between 0.0 and 0.5.
    """
    if avg_win <= 0 or win_rate <= 0:
        return 0.0

    kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
    # Half-Kelly for safety, capped at 0.5, floored at 0
    half_kelly = kelly / 2.0
    return max(0.0, min(0.5, half_kelly))


def monte_carlo(
    trades: list[Trade],
    n_simulations: int = 1000,
) -> dict[str, float]:
    """Run Monte Carlo simulation by randomly permuting trade PnL sequences.

    Shuffles the order of trade PnLs *n_simulations* times and computes
    final equity and max drawdown for each permutation to give confidence
    intervals on backtest results.

    Parameters
    ----------
    trades : list[Trade]
        List of trades (must have ``.pnl`` attribute).
    n_simulations : int
        Number of random permutations (default 1000).

    Returns
    -------
    dict
        Keys: ``median_final``, ``p5_final``, ``p95_final``,
        ``median_max_drawdown``.
    """
    if not trades:
        return {
            "median_final": 0.0,
            "p5_final": 0.0,
            "p95_final": 0.0,
            "median_max_drawdown": 0.0,
        }

    pnls = np.array([t.pnl for t in trades])
    n = len(pnls)

    finals = np.empty(n_simulations)
    max_dds = np.empty(n_simulations)

    rng = np.random.default_rng()

    for i in range(n_simulations):
        shuffled = rng.permutation(pnls)
        equity = np.cumsum(shuffled)
        finals[i] = equity[-1]

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        # Avoid division by zero: use absolute drawdown when peak is 0
        with np.errstate(divide="ignore", invalid="ignore"):
            dd = np.where(peak > 0, (peak - equity) / peak, np.abs(equity))
        max_dds[i] = float(np.max(dd)) if len(dd) > 0 else 0.0

    return {
        "median_final": round(float(np.median(finals)), 4),
        "p5_final": round(float(np.percentile(finals, 5)), 4),
        "p95_final": round(float(np.percentile(finals, 95)), 4),
        "median_max_drawdown": round(float(np.median(max_dds)), 4),
    }


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """Main backtesting engine.

    Parameters
    ----------
    sl_atr_mult : float
        ATR multiplier for stop-loss distance (default 1.5).
    tp_atr_mult : float
        ATR multiplier for take-profit distance (default 3.0).
    """

    def __init__(
        self,
        sl_atr_mult: float = DEFAULT_SL_ATR_MULT,
        tp_atr_mult: float = DEFAULT_TP_ATR_MULT,
    ) -> None:
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def fetch_data(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        """Fetch historical OHLCV data via yfinance.

        Parameters
        ----------
        symbol : str
            Ticker symbol (e.g. "NQ=F", "AAPL").
        period : str
            Look-back period (e.g. "6mo", "1y", "2y").
        interval : str
            Bar interval (e.g. "1d", "1h").

        Returns
        -------
        pd.DataFrame
            OHLCV DataFrame with DatetimeIndex.

        Raises
        ------
        ValueError
            If no data is returned for the given symbol/period.
        """
        logger.info("Fetching %s data: period=%s, interval=%s", symbol, period, interval)
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, timeout=30)
        if df is None or df.empty:
            raise ValueError(
                f"No data returned for {symbol} (period={period}, interval={interval})"
            )
        logger.info("Fetched %d bars for %s", len(df), symbol)
        return df

    def run(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        df: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """Execute a full backtest on historical data.

        Parameters
        ----------
        symbol : str
            Ticker symbol.
        period : str
            Look-back period for data fetch.
        interval : str
            Bar interval for data fetch.
        df : pd.DataFrame | None
            Optional pre-fetched DataFrame. If provided, ``symbol``/``period``/
            ``interval`` are ignored for data fetching.

        Returns
        -------
        BacktestResult
            Complete backtest results with trades and statistics.
        """
        if df is None:
            df = self.fetch_data(symbol, period, interval)

        if len(df) < MIN_BARS_WARMUP:
            logger.warning(
                "Only %d bars available (need %d for indicator warm-up). "
                "Results may be unreliable.",
                len(df),
                MIN_BARS_WARMUP,
            )

        logger.info("Computing indicators on %d bars...", len(df))
        df = compute_indicators(df)

        logger.info("Generating signals...")
        df = generate_signals(df)

        signal_count = (df["signal"] != 0).sum()
        logger.info("Found %d raw signals", signal_count)

        logger.info("Simulating trades (SL=%.1fx ATR, TP=%.1fx ATR)...",
                     self.sl_atr_mult, self.tp_atr_mult)
        trades = simulate_trades(df, self.sl_atr_mult, self.tp_atr_mult)

        logger.info("Computing statistics on %d trades...", len(trades))
        result = compute_statistics(trades)

        return result

    def walk_forward(
        self,
        symbol: str,
        period: str = "2y",
        interval: str = "1d",
        train_bars: int = 120,
        test_bars: int = 30,
        df: pd.DataFrame | None = None,
    ) -> dict:
        """Run walk-forward optimization with rolling train/test windows.

        Splits data into rolling windows: train on *train_bars* bars, test on
        *test_bars* bars, then slide forward by *test_bars*.

        Parameters
        ----------
        symbol : str
            Ticker symbol.
        period : str
            Look-back period for data fetch (should be long enough for
            multiple windows).
        interval : str
            Bar interval for data fetch.
        train_bars : int
            Number of bars for the in-sample (training) window.
        test_bars : int
            Number of bars for the out-of-sample (testing) window.
        df : pd.DataFrame | None
            Optional pre-fetched DataFrame.

        Returns
        -------
        dict
            Contains ``oos_results`` (list of BacktestResult for each
            out-of-sample window), ``is_results`` (in-sample results),
            and ``aggregate`` stats.
        """
        if df is None:
            df = self.fetch_data(symbol, period, interval)

        window_size = train_bars + test_bars
        if len(df) < window_size:
            logger.warning(
                "Not enough bars (%d) for walk-forward (need %d). "
                "Returning single backtest.",
                len(df),
                window_size,
            )
            result = self.run(symbol=symbol, df=df)
            return {
                "oos_results": [result],
                "is_results": [result],
                "aggregate": result.to_dict(),
            }

        oos_results: list[BacktestResult] = []
        is_results: list[BacktestResult] = []
        start = 0

        while start + window_size <= len(df):
            train_df = df.iloc[start: start + train_bars]
            test_df = df.iloc[start + train_bars: start + window_size]

            # In-sample run
            is_result = self.run(symbol=symbol, df=train_df)
            is_results.append(is_result)

            # Out-of-sample run: compute indicators on full train+test then
            # only simulate trades from the test portion
            full_window = df.iloc[start: start + window_size]
            full_ind = compute_indicators(full_window)
            full_sig = generate_signals(full_ind)
            # Only keep signals in the test portion
            test_start_idx = full_sig.index[train_bars] if len(full_sig) > train_bars else full_sig.index[-1]
            full_sig.loc[full_sig.index < test_start_idx, "signal"] = 0
            oos_trades = simulate_trades(full_sig, self.sl_atr_mult, self.tp_atr_mult)
            oos_result = compute_statistics(oos_trades)
            oos_results.append(oos_result)

            start += test_bars

        # Aggregate OOS stats
        all_oos_trades: list[Trade] = []
        for r in oos_results:
            all_oos_trades.extend(r.trades)
        aggregate = compute_statistics(all_oos_trades)

        # Compute IS/OOS performance ratio
        is_pnl = sum(r.total_pnl for r in is_results)
        oos_pnl = aggregate.total_pnl
        perf_ratio = oos_pnl / is_pnl if is_pnl != 0 else 0.0

        agg_dict = aggregate.to_dict()
        agg_dict["windows"] = len(oos_results)
        agg_dict["is_total_pnl"] = round(is_pnl, 4)
        agg_dict["oos_total_pnl"] = round(oos_pnl, 4)
        agg_dict["oos_is_ratio"] = round(perf_ratio, 4)

        return {
            "oos_results": oos_results,
            "is_results": is_results,
            "aggregate": agg_dict,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the backtester.

    Parameters
    ----------
    argv : list[str] | None
        Argument list (defaults to sys.argv[1:]).

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Backtest trading signals on historical data",
        prog="python -m modules.backtester",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        required=True,
        help="Ticker symbol (e.g. NQ=F, ES=F, AAPL)",
    )
    parser.add_argument(
        "--period",
        type=str,
        default="6mo",
        help="Look-back period (default: 6mo)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1d",
        help="Bar interval (default: 1d)",
    )
    parser.add_argument(
        "--sl-mult",
        type=float,
        default=DEFAULT_SL_ATR_MULT,
        help=f"ATR multiplier for stop-loss (default: {DEFAULT_SL_ATR_MULT})",
    )
    parser.add_argument(
        "--tp-mult",
        type=float,
        default=DEFAULT_TP_ATR_MULT,
        help=f"ATR multiplier for take-profit (default: {DEFAULT_TP_ATR_MULT})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> BacktestResult:
    """Run backtest from CLI arguments.

    Parameters
    ----------
    argv : list[str] | None
        CLI argument list.

    Returns
    -------
    BacktestResult
        The backtest result.
    """
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    engine = BacktestEngine(sl_atr_mult=args.sl_mult, tp_atr_mult=args.tp_mult)
    result = engine.run(symbol=args.symbol, period=args.period, interval=args.interval)

    print(result.summary())
    print()

    # Print individual trades
    if result.trades:
        print(f"{'#':>3}  {'Dir':>5}  {'Entry':>10}  {'Exit':>10}  {'PnL':>10}  {'Outcome':>12}  {'Bars':>5}  Date")
        print("-" * 85)
        for i, t in enumerate(result.trades, 1):
            print(
                f"{i:3d}  {t.direction:>5}  {t.entry_price:>10.2f}  "
                f"{t.exit_price:>10.2f}  {t.pnl:>+10.2f}  "
                f"{t.outcome:>12}  {t.bars_held:>5}  {t.entry_date}"
            )

    return result


if __name__ == "__main__":
    main()
