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
from modules.strategy import (
    _CLASS_SL_TP as _STRATEGY_SL_TP,
    classify_regime,
    compute_composite,
    compute_quality_score,
    compute_sl_tp_series,
    label_bar,
    COMPOSITE_THRESHOLD,
)

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


def generate_signals(
    df: pd.DataFrame,
    qs_filter: bool = True,
    qs_min: int = 4,
) -> pd.DataFrame:
    """Generate trading signals using the unified strategy module.

    Uses regime-aware indicator labeling from modules.strategy for the same
    logic as the live system. Optionally filters by Quality Score.

    Adds columns: signal (1=LONG, -1=SHORT, 0=none), composite_score, regime.

    Args:
        df: DataFrame with indicator columns from compute_indicators().
        qs_filter: If True, only fire signals when Quality Score >= qs_min.
        qs_min: Minimum Quality Score threshold (default 4).
    """
    n = len(df)
    signals = np.zeros(n, dtype=int)
    scores = np.zeros(n, dtype=float)
    regimes = [""] * n

    for i in range(50, n):  # Start after warmup
        regime, labels, adx_val = label_bar(df, i)
        regimes[i] = regime.value

        composite_dir, confidence = compute_composite(
            labels, regime, adx_filter=adx_val,
        )

        if composite_dir == "NEUTRAL":
            continue

        # Quality Score filter
        if qs_filter:
            qs = compute_quality_score(
                df, i, composite_dir,
                adx_value=adx_val,
                labels=labels,
            )
            if qs.total < qs_min:
                continue

        if composite_dir == "BULLISH":
            signals[i] = 1
            scores[i] = confidence / 100.0
        elif composite_dir == "BEARISH":
            signals[i] = -1
            scores[i] = confidence / 100.0

    df["signal"] = signals
    df["composite_score"] = scores
    df["regime"] = regimes

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


# Per-class SL/TP tuning now lives in modules.strategy._CLASS_SL_TP
_CLASS_PARAMS: dict[AssetClass, dict[str, float]] = {
    AssetClass(k): v for k, v in _STRATEGY_SL_TP.items()
    if k in [e.value for e in AssetClass]
}

# Default starting equity for metrics (USD)
DEFAULT_EQUITY = 10_000.0


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
    long_trades: int = 0
    short_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0        # Raw price-unit PnL
    total_pnl_usd: float = 0.0    # PnL in USD (price_pnl × point_value)
    avg_trade_pnl: float = 0.0
    expectancy: float = 0.0
    expectancy_usd: float = 0.0

    # Risk metrics (based on USD equity curve)
    max_drawdown_pct: float = 0.0
    max_drawdown_usd: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    return_pct: float = 0.0       # Total return on starting equity

    # Cost impact
    total_costs: float = 0.0
    total_costs_usd: float = 0.0

    # Kelly
    kelly_fraction: float = 0.0

    # Point value used
    point_value: float = 1.0

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
        sl_atr_mult: float | None = None,
        tp_atr_mult: float | None = None,
        adaptive_sl: bool = True,
        starting_equity: float = DEFAULT_EQUITY,
        qs_filter: bool = True,
        qs_min: int = 4,
    ) -> VBTBacktestResult | None:
        """Run a full backtest for a single symbol.

        Uses bar-by-bar simulation for accurate SL/TP handling with
        realistic spread/commission/slippage costs. If sl_atr_mult or
        tp_atr_mult are None, per-class defaults are used.

        Args:
            symbol: Canonical symbol (e.g. "EURUSD", "NQ", "AAPL").
            interval: Bar interval.
            bars: Number of bars to fetch.
            sl_atr_mult: SL multiplier (x ATR). None = use per-class default.
            tp_atr_mult: TP multiplier (x ATR). None = use per-class default.
            adaptive_sl: If True, adjust SL/TP based on ATR percentile.
            starting_equity: Starting equity in USD for metric calculations.
            qs_filter: If True, require Quality Score >= qs_min for signals.
            qs_min: Minimum Quality Score threshold (default 4).
        """
        spec = ASSET_UNIVERSE.get(symbol)
        if spec is None:
            logger.error("Unknown symbol: %s", symbol)
            return None

        # Per-class SL/TP defaults
        class_params = _CLASS_PARAMS.get(spec.asset_class, {})
        sl_mult = sl_atr_mult if sl_atr_mult is not None else class_params.get("sl_atr_mult", 1.5)
        tp_mult = tp_atr_mult if tp_atr_mult is not None else class_params.get("tp_atr_mult", 3.0)

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

        # Generate signals (unified strategy)
        df = generate_signals(df, qs_filter=qs_filter, qs_min=qs_min)

        # Get cost model
        costs = get_cost_model(spec)

        # Compute ATR-adaptive SL/TP distances (unified strategy)
        sl_dist, tp_dist = self._compute_sl_tp_distance(
            df, sl_mult, tp_mult, adaptive_sl,
            asset_class=spec.asset_class.value,
        )

        return self._simulate_trades(
            symbol, spec, interval, data, df, sl_dist, tp_dist, costs,
            data_warnings, starting_equity,
        )

    def run_universe(
        self,
        symbols: list[str] | None = None,
        asset_class: AssetClass | None = None,
        interval: str = "1d",
        bars: int = 500,
        starting_equity: float = DEFAULT_EQUITY,
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
            r = self.run(
                sym, interval=interval, bars=bars,
                starting_equity=starting_equity, **kwargs,
            )
            if r is not None:
                results.append(r)
            else:
                logger.warning("Skipped %s (no data or insufficient bars)", sym)

        return results

    def _compute_sl_tp_distance(
        self,
        df: pd.DataFrame,
        sl_mult: float,
        tp_mult: float,
        adaptive: bool,
        asset_class: str = "index",
    ) -> tuple[pd.Series, pd.Series]:
        """Compute SL/TP distances (in price units) for each bar.

        Delegates to strategy.compute_sl_tp_series() for unified logic.

        Returns (sl_distance, tp_distance) — always positive values
        representing distance from entry price. Direction is applied
        during trade simulation.
        """
        atr = df.get("ATR", pd.Series(dtype=float))
        return compute_sl_tp_series(
            atr,
            asset_class=asset_class,
            adaptive=adaptive,
            sl_override=sl_mult,
            tp_override=tp_mult,
        )

    def _simulate_trades(
        self,
        symbol: str,
        spec: AssetSpec,
        interval: str,
        data: Any,
        df: pd.DataFrame,
        sl_dist: pd.Series,
        tp_dist: pd.Series,
        costs: CostModel,
        data_warnings: list[str],
        starting_equity: float = DEFAULT_EQUITY,
    ) -> VBTBacktestResult:
        """Bar-by-bar simulation with proper LONG and SHORT SL/TP handling."""
        pv = spec.point_value  # USD per 1.0 price movement per contract

        result = VBTBacktestResult(
            symbol=symbol,
            asset_class=spec.asset_class.value,
            interval=interval,
            bars=len(df),
            data_source=data.source,
            data_warnings=data_warnings,
            point_value=pv,
        )

        trades: list[dict[str, Any]] = []
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        signals = df["signal"]

        in_trade = False  # Prevent overlapping trades

        for i in range(len(df)):
            sig = signals.iloc[i]
            if sig == 0 or in_trade:
                continue

            entry_price = close.iloc[i]
            atr_val = df["ATR"].iloc[i] if "ATR" in df.columns else entry_price * 0.01
            if pd.isna(atr_val):
                atr_val = entry_price * 0.01

            # Get SL/TP distances (always positive)
            sl_d = sl_dist.iloc[i] if not pd.isna(sl_dist.iloc[i]) else atr_val * 1.5
            tp_d = tp_dist.iloc[i] if not pd.isna(tp_dist.iloc[i]) else atr_val * 3.0

            # Apply spread + slippage at entry
            entry_cost = costs.spread + entry_price * costs.slippage_pct

            if sig == 1:  # LONG
                entry_price += entry_cost  # Worse fill for longs
                sl = entry_price - sl_d
                tp = entry_price + tp_d
            else:  # SHORT
                entry_price -= entry_cost  # Worse fill for shorts
                sl = entry_price + sl_d
                tp = entry_price - tp_d

            # Walk forward to find exit
            in_trade = True
            exit_price = close.iloc[-1]
            exit_date = str(df.index[-1])
            outcome = "STILL_OPEN"
            bars_held = len(df) - i

            for j in range(i + 1, len(df)):
                if sig == 1:  # LONG: SL below, TP above
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
                else:  # SHORT: SL above, TP below
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

            in_trade = False  # Trade closed, allow next

            pnl_raw = (exit_price - entry_price) * sig  # Price-unit PnL
            pnl_usd = pnl_raw * pv - costs.commission   # USD PnL after commission

            trades.append({
                "direction": "LONG" if sig == 1 else "SHORT",
                "entry_date": str(df.index[i]),
                "exit_date": exit_date,
                "entry_price": round(entry_price, 5),
                "exit_price": round(exit_price, 5),
                "sl": round(sl, 5),
                "tp": round(tp, 5),
                "pnl_raw": round(pnl_raw, 5),
                "pnl_usd": round(pnl_usd, 2),
                "status": outcome,
                "bars_held": bars_held,
            })

        result.trades = trades
        result.total_trades = len(trades)
        result.long_trades = sum(1 for t in trades if t["direction"] == "LONG")
        result.short_trades = sum(1 for t in trades if t["direction"] == "SHORT")

        if trades:
            pnls_usd = [t["pnl_usd"] for t in trades]
            winners = [p for p in pnls_usd if p > 0]
            losers = [p for p in pnls_usd if p <= 0]

            result.total_pnl = sum(t["pnl_raw"] for t in trades)
            result.total_pnl_usd = sum(pnls_usd)
            result.avg_trade_pnl = np.mean(pnls_usd)
            result.win_rate = len(winners) / len(pnls_usd) if pnls_usd else 0

            gross_profit = sum(winners) if winners else 0
            gross_loss = abs(sum(losers)) if losers else 0
            result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

            # Equity curve in USD — proper drawdown on notional account
            equity_curve = starting_equity + np.cumsum(pnls_usd)
            peak = np.maximum.accumulate(equity_curve)
            dd_usd = peak - equity_curve
            dd_pct = dd_usd / peak
            result.max_drawdown_usd = float(np.max(dd_usd))
            result.max_drawdown_pct = float(np.max(dd_pct)) * 100
            result.return_pct = (equity_curve[-1] - starting_equity) / starting_equity * 100

            # Sharpe (annualized, based on USD PnL per trade)
            if len(pnls_usd) > 1 and np.std(pnls_usd) > 0:
                result.sharpe_ratio = (np.mean(pnls_usd) / np.std(pnls_usd)) * np.sqrt(252)

            # Sortino (downside deviation only)
            downside = [p for p in pnls_usd if p < 0]
            if downside and np.std(downside) > 0:
                result.sortino_ratio = (np.mean(pnls_usd) / np.std(downside)) * np.sqrt(252)

            # Calmar (return / max drawdown)
            if result.max_drawdown_usd > 0:
                result.calmar_ratio = result.total_pnl_usd / result.max_drawdown_usd

            # Expectancy and Kelly (in USD)
            avg_win = np.mean(winners) if winners else 0
            avg_loss = np.mean([abs(x) for x in losers]) if losers else 0
            result.expectancy_usd = (result.win_rate * avg_win) - ((1 - result.win_rate) * avg_loss)

            if avg_loss > 0 and avg_win > 0:
                b = avg_win / avg_loss
                kelly = (result.win_rate * b - (1 - result.win_rate)) / b
                result.kelly_fraction = max(0, min(kelly / 2, 0.5))

            result.total_costs_usd = sum(
                (costs.spread * 2 * pv + costs.commission) for _ in trades
            )

        return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_results(results: list[VBTBacktestResult]) -> None:
    """Pretty-print backtest results for all symbols (all PnL in USD)."""
    if not results:
        print("No results to display.")
        return

    W = 135
    print()
    print("=" * W)
    print(
        f"{'SYMBOL':<8} {'CLASS':<10} {'SRC':<6} {'BARS':>4} "
        f"{'L/S':>5} {'#':>3} {'WIN%':>6} {'PF':>5} "
        f"{'PnL $':>10} {'Costs $':>8} {'DD%':>6} {'DD $':>9} "
        f"{'Sharpe':>6} {'Sortino':>7} {'Kelly':>5} {'Ret%':>7}"
    )
    print("-" * W)

    total_trades = 0
    total_pnl = 0.0
    total_costs = 0.0

    for r in sorted(results, key=lambda x: (x.asset_class, x.symbol)):
        ls = f"{r.long_trades}/{r.short_trades}"
        print(
            f"{r.symbol:<8} {r.asset_class:<10} {r.data_source[:6]:<6} {r.bars:>4} "
            f"{ls:>5} {r.total_trades:>3} {r.win_rate*100:>5.1f}% {r.profit_factor:>5.2f} "
            f"{r.total_pnl_usd:>+10.0f} {r.total_costs_usd:>8.0f} "
            f"{r.max_drawdown_pct:>5.1f}% {r.max_drawdown_usd:>9.0f} "
            f"{r.sharpe_ratio:>6.2f} {r.sortino_ratio:>7.2f} "
            f"{r.kelly_fraction*100:>4.1f}% {r.return_pct:>+6.1f}%"
        )
        total_trades += r.total_trades
        total_pnl += r.total_pnl_usd
        total_costs += r.total_costs_usd

    print("-" * W)
    print(
        f"{'TOTAL':<8} {'':10} {'':6} {'':>4} "
        f"{'':>5} {total_trades:>3} {'':>6} {'':>5} "
        f"{total_pnl:>+10.0f} {total_costs:>8.0f}"
    )
    print("=" * W)

    # Per-class summary
    print("\nPer Asset Class (USD):")
    for cls in AssetClass:
        if cls == AssetClass.REFERENCE:
            continue
        cls_results = [r for r in results if r.asset_class == cls.value]
        if not cls_results:
            continue
        cls_trades = sum(r.total_trades for r in cls_results)
        cls_pnl = sum(r.total_pnl_usd for r in cls_results)
        cls_costs = sum(r.total_costs_usd for r in cls_results)
        cls_wr = (
            sum(r.win_rate * r.total_trades for r in cls_results) / cls_trades
            if cls_trades > 0 else 0
        )
        profitable = [r for r in cls_results if r.total_pnl_usd > 0]
        losing = [r for r in cls_results if r.total_pnl_usd <= 0]
        edge = "HAS EDGE" if cls_pnl > 0 else "NO EDGE"
        print(
            f"  {cls.value:<12}: {len(cls_results)} assets, "
            f"{cls_trades} trades, {cls_wr*100:.1f}% WR, "
            f"PnL ${cls_pnl:+,.0f}, Costs ${cls_costs:,.0f} "
            f"({len(profitable)} profitable, {len(losing)} losing) [{edge}]"
        )

    # Profitable assets summary
    profitable_all = [r for r in results if r.total_pnl_usd > 0]
    losing_all = [r for r in results if r.total_pnl_usd <= 0]
    print(f"\nProfitable ({len(profitable_all)}):", ", ".join(
        f"{r.symbol} (${r.total_pnl_usd:+,.0f})" for r in
        sorted(profitable_all, key=lambda x: x.total_pnl_usd, reverse=True)
    ) or "none")
    print(f"Losing ({len(losing_all)}):", ", ".join(
        f"{r.symbol} (${r.total_pnl_usd:+,.0f})" for r in
        sorted(losing_all, key=lambda x: x.total_pnl_usd)
    ) or "none")

    # Trade list
    print("\nDetailed Trades:")
    for r in results:
        if not r.trades:
            continue
        print(f"\n  {r.symbol} ({r.asset_class}, pv={r.point_value:,.0f}):")
        print(f"  {'#':>3}  {'Dir':<6} {'Entry':>12} {'Exit':>12} {'PnL $':>10} {'Status':<12} {'Bars':>4} {'Date'}")
        print(f"  {'---':>3}  {'------':<6} {'--------':>12} {'--------':>12} {'------':>10} {'------':<12} {'----':>4} {'----------'}")
        for i, t in enumerate(r.trades, 1):
            print(
                f"  {i:>3}  {t['direction']:<6} {t['entry_price']:>12.2f} "
                f"{t['exit_price']:>12.2f} {t['pnl_usd']:>+10.0f} "
                f"{t['status']:<12} {t['bars_held']:>4} {t['entry_date'][:10]}"
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

    from dotenv import load_dotenv
    load_dotenv()

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
    parser.add_argument("--edge-only", action="store_true",
                        help="Only backtest assets with demonstrated edge (forex, commodities, ES)")
    parser.add_argument("--interval", default="1d", help="Bar interval (default: 1d)")
    parser.add_argument("--bars", type=int, default=500, help="Number of bars (default: 500)")
    parser.add_argument("--sl-mult", type=float, default=None,
                        help="Override SL ATR multiplier (default: per-class)")
    parser.add_argument("--tp-mult", type=float, default=None,
                        help="Override TP ATR multiplier (default: per-class)")
    parser.add_argument("--equity", type=float, default=DEFAULT_EQUITY,
                        help=f"Starting equity in USD (default: {DEFAULT_EQUITY:.0f})")
    parser.add_argument("--no-adaptive", action="store_true", help="Disable adaptive SL/TP")
    parser.add_argument("--no-qs-filter", action="store_true",
                        help="Disable Quality Score filter (allow all signals)")
    parser.add_argument("--qs-min", type=int, default=4,
                        help="Minimum Quality Score threshold (default: 4)")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Assets that showed positive edge in backtest analysis (500 daily bars)
    # Tier 1: strong edge (PF > 1.5, positive Sharpe)
    # Tier 2: marginal edge (PF > 1.0, needs monitoring)
    EDGE_SYMBOLS = [
        "ES", "RTY", "NQ",   # Indices — strong edge with wider SL
        "CL",                 # Crude Oil — 50% WR, PF 2.5
        "USDJPY",             # Best forex pair — PF 3.4
        "USDCHF",             # Marginal forex — break-even, monitor
        "NG",                 # Natural Gas — volatile but trending
        "GC",                 # Gold — large moves, needs tuning
    ]

    bt = VBTBacktester()

    common_kwargs: dict[str, Any] = {
        "interval": args.interval,
        "bars": args.bars,
        "sl_atr_mult": args.sl_mult,     # None = use per-class defaults
        "tp_atr_mult": args.tp_mult,
        "adaptive_sl": not args.no_adaptive,
        "starting_equity": args.equity,
        "qs_filter": not args.no_qs_filter,
        "qs_min": args.qs_min,
    }

    if args.edge_only:
        results = bt.run_universe(symbols=EDGE_SYMBOLS, **common_kwargs)
    elif args.all:
        results = bt.run_universe(**common_kwargs)
    elif args.asset_class:
        cls = AssetClass(args.asset_class)
        results = bt.run_universe(asset_class=cls, **common_kwargs)
    elif args.symbols:
        results = bt.run_universe(symbols=args.symbols, **common_kwargs)
    else:
        # Default: edge symbols
        results = bt.run_universe(symbols=EDGE_SYMBOLS, **common_kwargs)

    print_results(results)


if __name__ == "__main__":
    main()
