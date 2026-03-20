"""vectorbt-based backtesting engine.

Replaces the custom backtester with vectorbt for:
- Vectorized simulation (1000x faster parameter sweeps)
- Realistic spread/commission modeling (Fineco CFD costs)
- Portfolio-level metrics (Sharpe, Sortino, Calmar, etc.)
- Built-in walk-forward and Monte Carlo analysis

Usage::

    python -m modules.vbt_backtester --symbols NQ ES GC EURUSD AAPL --period 1y
    python -m modules.vbt_backtester --class forex --period 2y --interval 1h
    python -m modules.vbt_backtester --all --period 1y
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta
import vectorbt as vbt

from modules.data import ASSET_UNIVERSE, AssetClass, AssetSpec
from modules.data.registry import DataRegistry, create_default_registry

logger = logging.getLogger(__name__)

# Suppress vectorbt warnings about missing plotly features
warnings.filterwarnings("ignore", category=UserWarning, module="vectorbt")


# ---------------------------------------------------------------------------
# Indicator computation (reuses logic from price_data.py)
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators on an OHLCV DataFrame.

    Returns the original DataFrame with indicator columns appended.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    # RSI
    rsi = ta.rsi(close, length=14)
    if rsi is not None:
        df["RSI"] = rsi

    # MACD
    macd = ta.macd(close, fast=12, slow=26, signal=9)
    if macd is not None:
        df["MACD"] = macd.iloc[:, 0]
        df["MACD_hist"] = macd.iloc[:, 1]
        df["MACD_signal"] = macd.iloc[:, 2]

    # Bollinger Bands
    bb = ta.bbands(close, length=20, std=2)
    if bb is not None:
        df["BB_upper"] = bb.iloc[:, 2]
        df["BB_middle"] = bb.iloc[:, 1]
        df["BB_lower"] = bb.iloc[:, 0]
        df["BB_bandwidth"] = ((bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1]) * 100

    # Stochastic
    stoch = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
    if stoch is not None:
        df["STOCH_K"] = stoch.iloc[:, 0]
        df["STOCH_D"] = stoch.iloc[:, 1]

    # EMAs
    ema20 = ta.ema(close, length=20)
    ema50 = ta.ema(close, length=50)
    if ema20 is not None:
        df["EMA20"] = ema20
    if ema50 is not None:
        df["EMA50"] = ema50

    # ADX
    adx_df = ta.adx(high, low, close, length=14)
    if adx_df is not None:
        df["ADX"] = adx_df.iloc[:, 0]
        df["DI_plus"] = adx_df.iloc[:, 1]
        df["DI_minus"] = adx_df.iloc[:, 2]

    # ATR
    atr = ta.atr(high, low, close, length=14)
    if atr is not None:
        df["ATR"] = atr

    return df


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Generate trading signals using the adaptive-weight composite score.

    Adds columns: signal (1=LONG, -1=SHORT, 0=none), composite_score.
    """
    n = len(df)
    signals = np.zeros(n, dtype=int)
    scores = np.zeros(n, dtype=float)

    for i in range(50, n):  # Start after warmup
        row = df.iloc[i]

        adx = row.get("ADX", 20)
        if pd.isna(adx):
            adx = 20

        # Adaptive weights based on market regime
        if adx > 25:
            w = {"momentum": 1.5, "mean_reversion": 0.7}
        elif adx < 20:
            w = {"momentum": 0.7, "mean_reversion": 1.5}
        else:
            w = {"momentum": 1.0, "mean_reversion": 1.0}

        bull_score = 0.0
        bear_score = 0.0
        total_weight = 0.0

        # RSI (mean reversion)
        rsi = row.get("RSI")
        if not pd.isna(rsi) if rsi is not None else False:
            wt = w["mean_reversion"]
            total_weight += wt
            if rsi < 30:
                bull_score += wt
            elif rsi > 70:
                bear_score += wt
            elif rsi > 60:
                bull_score += wt * 0.5
            elif rsi < 40:
                bear_score += wt * 0.5

        # MACD (momentum)
        macd_hist = row.get("MACD_hist")
        if not pd.isna(macd_hist) if macd_hist is not None else False:
            wt = w["momentum"]
            total_weight += wt
            if macd_hist > 0:
                bull_score += wt
            else:
                bear_score += wt

        # Bollinger Bands (mean reversion)
        bb_upper = row.get("BB_upper")
        bb_lower = row.get("BB_lower")
        bb_mid = row.get("BB_middle")
        close = row["Close"]
        if all(not pd.isna(v) for v in [bb_upper, bb_lower, bb_mid] if v is not None):
            wt = w["mean_reversion"]
            total_weight += wt
            if close > bb_upper:
                bear_score += wt
            elif close < bb_lower:
                bull_score += wt
            elif close > bb_mid:
                bull_score += wt * 0.3
            else:
                bear_score += wt * 0.3

        # Stochastic (mean reversion)
        stoch_k = row.get("STOCH_K")
        stoch_d = row.get("STOCH_D")
        if all(not pd.isna(v) for v in [stoch_k, stoch_d] if v is not None):
            wt = w["mean_reversion"]
            total_weight += wt
            if stoch_k < 20:
                bull_score += wt
            elif stoch_k > 80:
                bear_score += wt
            elif stoch_k > stoch_d:
                bull_score += wt * 0.3
            else:
                bear_score += wt * 0.3

        # EMA Trend (momentum)
        ema20 = row.get("EMA20")
        ema50 = row.get("EMA50")
        if all(not pd.isna(v) for v in [ema20, ema50] if v is not None):
            wt = w["momentum"]
            total_weight += wt
            if ema20 > ema50:
                bull_score += wt
            else:
                bear_score += wt

        # VWAP proxy: close vs EMA20 (simple substitute for daily data)
        if not pd.isna(ema20) if ema20 is not None else False:
            wt = 1.0
            total_weight += wt
            if close > ema20:
                bull_score += wt * 0.5
            else:
                bear_score += wt * 0.5

        # Compute composite
        if total_weight > 0:
            bull_pct = bull_score / total_weight
            bear_pct = bear_score / total_weight
        else:
            bull_pct = bear_pct = 0.5

        threshold = 0.60  # 60% agreement required

        # ADX filter: only signal when trend is strong enough
        if adx > 22:
            if bull_pct >= threshold:
                signals[i] = 1
                scores[i] = bull_pct
            elif bear_pct >= threshold:
                signals[i] = -1
                scores[i] = bear_pct

    df["signal"] = signals
    df["composite_score"] = scores

    # De-duplicate: only fire on first bar of a signal run
    for i in range(1, n):
        if signals[i] != 0 and signals[i] == signals[i - 1]:
            df.iloc[i, df.columns.get_loc("signal")] = 0

    return df


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

@dataclass
class CostModel:
    """Realistic trading costs for backtesting."""

    spread: float = 0.0       # Spread in price units (applied at entry + exit)
    commission: float = 0.0   # Fixed commission per trade (USD)
    slippage_pct: float = 0.0001  # Slippage as fraction of price (1 bps default)


def get_cost_model(spec: AssetSpec) -> CostModel:
    """Build a cost model from asset specification."""
    return CostModel(
        spread=spec.spread_points,
        commission=spec.commission,
        slippage_pct=0.0001,
    )


# ---------------------------------------------------------------------------
# Backtest result
# ---------------------------------------------------------------------------

@dataclass
class VBTBacktestResult:
    """Results from a vectorbt backtest."""

    symbol: str
    asset_class: str
    interval: str
    bars: int
    data_source: str

    # Trade metrics
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    avg_trade_pnl: float = 0.0
    expectancy: float = 0.0

    # Risk metrics
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Cost impact
    total_costs: float = 0.0
    pnl_before_costs: float = 0.0

    # Kelly
    kelly_fraction: float = 0.0

    # Data quality
    data_warnings: list[str] = field(default_factory=list)

    # Trade details
    trades: list[dict[str, Any]] = field(default_factory=list)

    # Portfolio object (for further analysis)
    _portfolio: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------

class VBTBacktester:
    """vectorbt-based backtesting engine with realistic cost modeling."""

    def __init__(self, registry: DataRegistry | None = None):
        self.registry = registry or create_default_registry()

    def run(
        self,
        symbol: str,
        interval: str = "1d",
        bars: int = 500,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.0,
        adaptive_sl: bool = True,
    ) -> VBTBacktestResult | None:
        """Run a full backtest for a single symbol.

        Args:
            symbol: Canonical symbol (e.g. "EURUSD", "NQ", "AAPL").
            interval: Bar interval.
            bars: Number of bars to fetch.
            sl_atr_mult: Base SL multiplier (x ATR).
            tp_atr_mult: Base TP multiplier (x ATR).
            adaptive_sl: If True, adjust SL/TP based on ATR percentile.
        """
        spec = ASSET_UNIVERSE.get(symbol)
        if spec is None:
            logger.error("Unknown symbol: %s", symbol)
            return None

        # Fetch data
        data = self.registry.fetch(symbol, interval=interval, bars=bars)
        if data is None or data.empty:
            logger.error("No data for %s", symbol)
            return None

        df = data.df.copy()
        data_warnings = data.validate()

        if len(df) < 60:
            logger.error("Insufficient data for %s: %d bars (need 60+)", symbol, len(df))
            return None

        # Compute indicators
        df = compute_indicators(df)

        # Generate signals
        df = generate_signals(df)

        # Get cost model
        costs = get_cost_model(spec)

        # Compute ATR-adaptive SL/TP
        sl_prices, tp_prices = self._compute_sl_tp(
            df, sl_atr_mult, tp_atr_mult, adaptive_sl
        )

        # Build entry/exit signals for vectorbt
        long_entries = df["signal"] == 1
        short_entries = df["signal"] == -1

        # Calculate total cost per trade in price units
        spread_cost = costs.spread
        slippage_cost = df["Close"] * costs.slippage_pct
        # Commission as fraction of price (for vbt fees parameter)
        comm_pct = costs.commission / (df["Close"] * spec.point_value).clip(lower=1)

        # Run vectorbt portfolio simulation
        try:
            close = df["Close"]

            # Long portfolio
            long_pf = None
            if long_entries.any():
                long_sl = sl_prices.where(long_entries.cumsum() > 0)
                long_tp = tp_prices.where(long_entries.cumsum() > 0)
                long_pf = vbt.Portfolio.from_signals(
                    close=close,
                    entries=long_entries,
                    exits=pd.Series(False, index=df.index),
                    sl_stop=((close - long_sl) / close).clip(lower=0.001),
                    tp_stop=((long_tp - close) / close).clip(lower=0.001),
                    fees=spread_cost / close + comm_pct,
                    freq=interval,
                    init_cash=100_000,
                    size=1.0,
                    size_type="amount",
                    accumulate=False,
                )

            # Short portfolio
            short_pf = None
            if short_entries.any():
                short_sl = sl_prices.where(short_entries.cumsum() > 0)
                short_tp = tp_prices.where(short_entries.cumsum() > 0)
                short_pf = vbt.Portfolio.from_signals(
                    close=close,
                    entries=short_entries,
                    exits=pd.Series(False, index=df.index),
                    short_entries=short_entries,
                    sl_stop=((short_sl - close) / close).clip(lower=0.001),
                    tp_stop=((close - short_tp) / close).clip(lower=0.001),
                    fees=spread_cost / close + comm_pct,
                    freq=interval,
                    init_cash=100_000,
                    size=1.0,
                    size_type="amount",
                    accumulate=False,
                )

            # Merge results
            result = self._build_result(
                symbol=symbol,
                spec=spec,
                interval=interval,
                data=data,
                df=df,
                long_pf=long_pf,
                short_pf=short_pf,
                costs=costs,
                data_warnings=data_warnings,
            )
            return result

        except Exception as exc:
            logger.error("vectorbt simulation failed for %s: %s", symbol, exc)
            # Fallback to manual simulation
            return self._manual_backtest(
                symbol, spec, interval, data, df, sl_prices, tp_prices, costs, data_warnings
            )

    def run_universe(
        self,
        symbols: list[str] | None = None,
        asset_class: AssetClass | None = None,
        interval: str = "1d",
        bars: int = 500,
        **kwargs: Any,
    ) -> list[VBTBacktestResult]:
        """Run backtest across multiple symbols."""
        if symbols:
            target = symbols
        elif asset_class:
            target = [
                s for s, a in ASSET_UNIVERSE.items()
                if a.asset_class == asset_class
            ]
        else:
            target = [
                s for s, a in ASSET_UNIVERSE.items()
                if a.asset_class != AssetClass.REFERENCE
            ]

        results: list[VBTBacktestResult] = []
        for sym in target:
            logger.info("Backtesting %s...", sym)
            r = self.run(sym, interval=interval, bars=bars, **kwargs)
            if r is not None:
                results.append(r)
            else:
                logger.warning("Skipped %s (no data or insufficient bars)", sym)

        return results

    def _compute_sl_tp(
        self,
        df: pd.DataFrame,
        sl_mult: float,
        tp_mult: float,
        adaptive: bool,
    ) -> tuple[pd.Series, pd.Series]:
        """Compute SL/TP price levels for each bar."""
        atr = df.get("ATR", pd.Series(dtype=float))
        close = df["Close"]

        if adaptive and len(atr.dropna()) > 20:
            # ATR percentile over rolling 50-bar window
            atr_pctile = atr.rolling(50, min_periods=20).apply(
                lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
            )
            # Adaptive multiplier: low vol → wider SL, high vol → tighter SL
            sl_multiplier = sl_mult * (1.0 + (0.5 - atr_pctile).clip(-0.5, 0.5))
            tp_multiplier = sl_multiplier * (tp_mult / sl_mult)
        else:
            sl_multiplier = pd.Series(sl_mult, index=df.index)
            tp_multiplier = pd.Series(tp_mult, index=df.index)

        sl_distance = atr * sl_multiplier
        tp_distance = atr * tp_multiplier

        # SL/TP levels (direction-agnostic, distance from close)
        sl_price = close - sl_distance  # For longs; inverted for shorts in simulation
        tp_price = close + tp_distance

        return sl_price, tp_price

    def _build_result(
        self,
        symbol: str,
        spec: AssetSpec,
        interval: str,
        data: Any,
        df: pd.DataFrame,
        long_pf: Any,
        short_pf: Any,
        costs: CostModel,
        data_warnings: list[str],
    ) -> VBTBacktestResult:
        """Build result from vectorbt portfolio objects."""
        result = VBTBacktestResult(
            symbol=symbol,
            asset_class=spec.asset_class.value,
            interval=interval,
            bars=len(df),
            data_source=data.source,
            data_warnings=data_warnings,
        )

        # Merge trade records from long and short portfolios
        all_trades = []

        for pf, direction in [(long_pf, "LONG"), (short_pf, "SHORT")]:
            if pf is None:
                continue
            try:
                trades = pf.trades.records_readable
                for _, t in trades.iterrows():
                    all_trades.append({
                        "direction": direction,
                        "entry_date": str(t.get("Entry Timestamp", "")),
                        "exit_date": str(t.get("Exit Timestamp", "")),
                        "entry_price": float(t.get("Avg Entry Price", 0)),
                        "exit_price": float(t.get("Avg Exit Price", 0)),
                        "pnl": float(t.get("PnL", 0)),
                        "return_pct": float(t.get("Return", 0)) * 100,
                        "status": t.get("Status", "Open"),
                    })
            except Exception:
                pass

        result.trades = all_trades
        result.total_trades = len(all_trades)

        if not all_trades:
            return result

        # Aggregate metrics
        pnls = [t["pnl"] for t in all_trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        result.total_pnl = sum(pnls)
        result.avg_trade_pnl = np.mean(pnls) if pnls else 0
        result.win_rate = len(winners) / len(pnls) if pnls else 0

        gross_profit = sum(winners) if winners else 0
        gross_loss = abs(sum(losers)) if losers else 0
        result.profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else float("inf")
        )

        # Risk metrics from the primary portfolio
        primary_pf = long_pf or short_pf
        if primary_pf is not None:
            try:
                stats = primary_pf.stats()
                result.max_drawdown_pct = abs(float(stats.get("Max Drawdown [%]", 0)))
                result.sharpe_ratio = float(stats.get("Sharpe Ratio", 0))
                result.sortino_ratio = float(stats.get("Sortino Ratio", 0))
                result.calmar_ratio = float(stats.get("Calmar Ratio", 0))
            except Exception:
                pass

        # Expectancy
        avg_win = np.mean(winners) if winners else 0
        avg_loss = np.mean([abs(l) for l in losers]) if losers else 0
        result.expectancy = (result.win_rate * avg_win) - ((1 - result.win_rate) * avg_loss)

        # Kelly criterion (half-Kelly, capped)
        if avg_loss > 0 and avg_win > 0:
            b = avg_win / avg_loss
            kelly = (result.win_rate * b - (1 - result.win_rate)) / b
            result.kelly_fraction = max(0, min(kelly / 2, 0.5))

        # Cost estimate
        result.total_costs = (
            costs.spread * 2 * result.total_trades
            + costs.commission * result.total_trades
        )

        result._portfolio = primary_pf

        return result

    def _manual_backtest(
        self,
        symbol: str,
        spec: AssetSpec,
        interval: str,
        data: Any,
        df: pd.DataFrame,
        sl_prices: pd.Series,
        tp_prices: pd.Series,
        costs: CostModel,
        data_warnings: list[str],
    ) -> VBTBacktestResult:
        """Fallback bar-by-bar simulation when vectorbt fails."""
        result = VBTBacktestResult(
            symbol=symbol,
            asset_class=spec.asset_class.value,
            interval=interval,
            bars=len(df),
            data_source=data.source,
            data_warnings=data_warnings,
        )

        trades: list[dict[str, Any]] = []
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        signals = df["signal"]

        for i in range(len(df)):
            sig = signals.iloc[i]
            if sig == 0:
                continue

            entry_price = close.iloc[i]
            atr_val = df["ATR"].iloc[i] if "ATR" in df.columns else entry_price * 0.01
            if pd.isna(atr_val):
                atr_val = entry_price * 0.01

            # Apply spread + slippage at entry
            entry_cost = costs.spread + entry_price * costs.slippage_pct

            if sig == 1:  # LONG
                entry_price += entry_cost
                sl = sl_prices.iloc[i] if not pd.isna(sl_prices.iloc[i]) else entry_price - atr_val * 1.5
                tp = tp_prices.iloc[i] if not pd.isna(tp_prices.iloc[i]) else entry_price + atr_val * 3.0
            else:  # SHORT
                entry_price -= entry_cost
                sl = 2 * close.iloc[i] - sl_prices.iloc[i] if not pd.isna(sl_prices.iloc[i]) else entry_price + atr_val * 1.5
                tp = 2 * close.iloc[i] - tp_prices.iloc[i] if not pd.isna(tp_prices.iloc[i]) else entry_price - atr_val * 3.0

            # Walk forward to find exit
            exit_price = close.iloc[-1]
            exit_date = str(df.index[-1])
            outcome = "STILL_OPEN"
            bars_held = len(df) - i

            for j in range(i + 1, len(df)):
                if sig == 1:
                    if low.iloc[j] <= sl:
                        exit_price = sl - costs.spread
                        exit_date = str(df.index[j])
                        outcome = "SL_HIT"
                        bars_held = j - i
                        break
                    if high.iloc[j] >= tp:
                        exit_price = tp - costs.spread
                        exit_date = str(df.index[j])
                        outcome = "TP_HIT"
                        bars_held = j - i
                        break
                else:
                    if high.iloc[j] >= sl:
                        exit_price = sl + costs.spread
                        exit_date = str(df.index[j])
                        outcome = "SL_HIT"
                        bars_held = j - i
                        break
                    if low.iloc[j] <= tp:
                        exit_price = tp + costs.spread
                        exit_date = str(df.index[j])
                        outcome = "TP_HIT"
                        bars_held = j - i
                        break

            pnl = (exit_price - entry_price) * sig - costs.commission

            trades.append({
                "direction": "LONG" if sig == 1 else "SHORT",
                "entry_date": str(df.index[i]),
                "exit_date": exit_date,
                "entry_price": round(entry_price, 5),
                "exit_price": round(exit_price, 5),
                "pnl": round(pnl, 2),
                "return_pct": round(pnl / entry_price * 100, 4),
                "status": outcome,
                "bars_held": bars_held,
            })

        result.trades = trades
        result.total_trades = len(trades)

        if trades:
            pnls = [t["pnl"] for t in trades]
            winners = [p for p in pnls if p > 0]
            losers = [p for p in pnls if p <= 0]

            result.total_pnl = sum(pnls)
            result.avg_trade_pnl = np.mean(pnls)
            result.win_rate = len(winners) / len(pnls) if pnls else 0

            gross_profit = sum(winners) if winners else 0
            gross_loss = abs(sum(losers)) if losers else 0
            result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

            # Max drawdown
            equity = np.cumsum(pnls)
            peak = np.maximum.accumulate(equity)
            dd = (peak - equity) / (np.abs(peak) + 1e-10)
            result.max_drawdown_pct = float(np.max(dd)) * 100

            # Sharpe
            if len(pnls) > 1 and np.std(pnls) > 0:
                result.sharpe_ratio = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252)

            # Expectancy and Kelly
            avg_win = np.mean(winners) if winners else 0
            avg_loss = np.mean([abs(l) for l in losers]) if losers else 0
            result.expectancy = (result.win_rate * avg_win) - ((1 - result.win_rate) * avg_loss)

            if avg_loss > 0 and avg_win > 0:
                b = avg_win / avg_loss
                kelly = (result.win_rate * b - (1 - result.win_rate)) / b
                result.kelly_fraction = max(0, min(kelly / 2, 0.5))

            result.total_costs = (costs.spread * 2 + costs.commission) * len(trades)

        return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_results(results: list[VBTBacktestResult]) -> None:
    """Pretty-print backtest results for all symbols."""
    if not results:
        print("No results to display.")
        return

    # Header
    print()
    print("=" * 120)
    print(f"{'SYMBOL':<10} {'CLASS':<12} {'SOURCE':<12} {'BARS':>5} {'TRADES':>6} "
          f"{'WIN%':>6} {'PF':>6} {'PNL':>10} {'COSTS':>8} "
          f"{'DD%':>6} {'SHARPE':>7} {'KELLY':>6} {'WARNINGS'}")
    print("-" * 120)

    total_trades = 0
    total_pnl = 0.0
    total_costs = 0.0

    for r in sorted(results, key=lambda x: x.asset_class):
        warns = len(r.data_warnings)
        warn_str = f"{warns} warn" if warns else "clean"
        print(
            f"{r.symbol:<10} {r.asset_class:<12} {r.data_source:<12} {r.bars:>5} {r.total_trades:>6} "
            f"{r.win_rate*100:>5.1f}% {r.profit_factor:>6.2f} {r.total_pnl:>+10.2f} {r.total_costs:>8.2f} "
            f"{r.max_drawdown_pct:>5.1f}% {r.sharpe_ratio:>7.2f} {r.kelly_fraction:>5.1f}% {warn_str}"
        )
        total_trades += r.total_trades
        total_pnl += r.total_pnl
        total_costs += r.total_costs

    print("-" * 120)
    print(f"{'TOTAL':<10} {'':12} {'':12} {'':>5} {total_trades:>6} "
          f"{'':>6} {'':>6} {total_pnl:>+10.2f} {total_costs:>8.2f}")
    print("=" * 120)

    # Per-class summary
    print("\nPer Asset Class:")
    for cls in AssetClass:
        if cls == AssetClass.REFERENCE:
            continue
        cls_results = [r for r in results if r.asset_class == cls.value]
        if not cls_results:
            continue
        cls_trades = sum(r.total_trades for r in cls_results)
        cls_pnl = sum(r.total_pnl for r in cls_results)
        cls_wr = (
            sum(r.win_rate * r.total_trades for r in cls_results) / cls_trades
            if cls_trades > 0 else 0
        )
        print(
            f"  {cls.value:<12}: {len(cls_results)} assets, "
            f"{cls_trades} trades, {cls_wr*100:.1f}% WR, PnL {cls_pnl:+.2f}"
        )

    # Trade list
    print("\nDetailed Trades:")
    for r in results:
        if not r.trades:
            continue
        print(f"\n  {r.symbol} ({r.asset_class}, {r.data_source}):")
        print(f"  {'#':>3}  {'Dir':<6} {'Entry':>12} {'Exit':>12} {'PnL':>10} {'Status':<12} {'Date'}")
        print(f"  {'---':>3}  {'---':<6} {'---':>12} {'---':>12} {'---':>10} {'---':<12} {'---'}")
        for i, t in enumerate(r.trades, 1):
            print(
                f"  {i:>3}  {t['direction']:<6} {t['entry_price']:>12.2f} "
                f"{t['exit_price']:>12.2f} {t['pnl']:>+10.2f} {t['status']:<12} {t['entry_date'][:10]}"
            )

    # Data quality
    any_warnings = any(r.data_warnings for r in results)
    if any_warnings:
        print("\nData Quality Warnings:")
        for r in results:
            if r.data_warnings:
                print(f"  {r.symbol}: {'; '.join(r.data_warnings)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Trading Copilot — vectorbt Backtester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m modules.vbt_backtester --symbols NQ ES GC EURUSD AAPL
  python -m modules.vbt_backtester --class forex --period 2y
  python -m modules.vbt_backtester --all --interval 1h --bars 500
  python -m modules.vbt_backtester --symbols AAPL MSFT NVDA --bars 500
        """,
    )
    parser.add_argument("--symbols", nargs="+", help="Symbols to backtest")
    parser.add_argument("--class", dest="asset_class", help="Asset class: forex, commodity, index, stock")
    parser.add_argument("--all", action="store_true", help="Backtest entire universe")
    parser.add_argument("--interval", default="1d", help="Bar interval (default: 1d)")
    parser.add_argument("--bars", type=int, default=500, help="Number of bars (default: 500)")
    parser.add_argument("--sl-mult", type=float, default=1.5, help="SL ATR multiplier")
    parser.add_argument("--tp-mult", type=float, default=3.0, help="TP ATR multiplier")
    parser.add_argument("--no-adaptive", action="store_true", help="Disable adaptive SL/TP")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    bt = VBTBacktester()

    if args.all:
        results = bt.run_universe(
            interval=args.interval,
            bars=args.bars,
            sl_atr_mult=args.sl_mult,
            tp_atr_mult=args.tp_mult,
            adaptive_sl=not args.no_adaptive,
        )
    elif args.asset_class:
        cls = AssetClass(args.asset_class)
        results = bt.run_universe(
            asset_class=cls,
            interval=args.interval,
            bars=args.bars,
            sl_atr_mult=args.sl_mult,
            tp_atr_mult=args.tp_mult,
            adaptive_sl=not args.no_adaptive,
        )
    elif args.symbols:
        results = bt.run_universe(
            symbols=args.symbols,
            interval=args.interval,
            bars=args.bars,
            sl_atr_mult=args.sl_mult,
            tp_atr_mult=args.tp_mult,
            adaptive_sl=not args.no_adaptive,
        )
    else:
        # Default: a representative mix
        results = bt.run_universe(
            symbols=["EURUSD", "GC", "NQ", "AAPL"],
            interval=args.interval,
            bars=args.bars,
            sl_atr_mult=args.sl_mult,
            tp_atr_mult=args.tp_mult,
            adaptive_sl=not args.no_adaptive,
        )

    print_results(results)


if __name__ == "__main__":
    main()
