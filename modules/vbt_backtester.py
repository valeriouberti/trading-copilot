"""vectorbt-based backtesting engine — ETF LONG-only.

Backtests the UCITS ETF swing trading strategy with:
- LONG-only signals (BEARISH → no trade, not short)
- Realistic Fineco costs (€2.95 commission per trade, no spread)
- Max 10-day hold period forced exit
- Position sizing in EUR with shares calculation
- Portfolio-level metrics (Sharpe, Sortino, Calmar, etc.)

Usage::

    python -m modules.vbt_backtester --symbols SWDA.MI CSSPX.MI EQQQ.MI
    python -m modules.vbt_backtester --all --bars 500
    python -m modules.vbt_backtester --symbols EQQQ.MI --bars 250
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

    Adds columns: signal (1=LONG, 0=none), composite_score, regime.
    LONG-only: BEARISH signals are set to 0 (no trade) instead of -1.

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
        # LONG-only: BEARISH signals are skipped (no short selling for ETFs)

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
    """Realistic trading costs for ETF backtesting."""

    spread: float = 0.0            # ETFs have no spread (exchange-traded)
    commission: float = 2.95       # Fineco per-trade commission in EUR
    slippage_pct: float = 0.0005   # Slippage as fraction of price (5 bps for ETFs)


MAX_HOLD_BARS = 10  # Force exit after 10 bars (days)


def get_cost_model(spec: AssetSpec) -> CostModel:
    """Build a cost model from ETF asset specification."""
    return CostModel(
        spread=0.0,
        commission=spec.commission_eur,
        slippage_pct=0.0005,
    )


# Per-class SL/TP tuning now lives in modules.strategy._CLASS_SL_TP
_CLASS_PARAMS: dict[AssetClass, dict[str, float]] = {
    AssetClass(k): v for k, v in _STRATEGY_SL_TP.items()
    if k in [e.value for e in AssetClass]
}

# Default starting equity for metrics (EUR, small account)
DEFAULT_EQUITY = 3_000.0


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
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl_eur: float = 0.0    # PnL in EUR (shares × price_diff - commissions)
    avg_trade_pnl: float = 0.0
    expectancy_eur: float = 0.0

    # Risk metrics (based on EUR equity curve)
    max_drawdown_pct: float = 0.0
    max_drawdown_eur: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    return_pct: float = 0.0       # Total return on starting equity

    # Cost impact
    total_costs_eur: float = 0.0

    # Kelly
    kelly_fraction: float = 0.0

    # Position sizing
    position_size_eur: float = 1500.0

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
        """Run a full backtest for a single ETF symbol.

        LONG-only bar-by-bar simulation with SL/TP handling, max hold
        forced exit, and Fineco commission costs. If sl_atr_mult or
        tp_atr_mult are None, per-class defaults are used.

        Args:
            symbol: ETF symbol (e.g. "SWDA.MI", "EQQQ.MI").
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
            target = list(ASSET_UNIVERSE.keys())

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
        """LONG-only bar-by-bar simulation with max hold forced exit."""
        import math

        position_size_eur = 1500.0

        result = VBTBacktestResult(
            symbol=symbol,
            asset_class=spec.asset_class.value,
            interval=interval,
            bars=len(df),
            data_source=data.source,
            data_warnings=data_warnings,
            position_size_eur=position_size_eur,
        )

        trades: list[dict[str, Any]] = []
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        signals = df["signal"]

        in_trade = False

        for i in range(len(df)):
            sig = signals.iloc[i]
            if sig != 1 or in_trade:  # LONG-only
                continue

            entry_price = close.iloc[i]
            atr_val = df["ATR"].iloc[i] if "ATR" in df.columns else entry_price * 0.01
            if pd.isna(atr_val):
                atr_val = entry_price * 0.01

            sl_d = sl_dist.iloc[i] if not pd.isna(sl_dist.iloc[i]) else atr_val * 1.5
            tp_d = tp_dist.iloc[i] if not pd.isna(tp_dist.iloc[i]) else atr_val * 3.0

            # Apply slippage at entry (no spread for ETFs)
            entry_price += entry_price * costs.slippage_pct

            sl = entry_price - sl_d
            tp = entry_price + tp_d

            # Compute shares
            shares = math.floor(position_size_eur / entry_price)
            if shares < 1:
                continue

            # Walk forward to find exit
            in_trade = True
            exit_price = close.iloc[-1]
            exit_date = str(df.index[-1])
            outcome = "STILL_OPEN"
            bars_held = len(df) - i

            for j in range(i + 1, len(df)):
                # Max hold forced exit
                if j - i >= MAX_HOLD_BARS:
                    exit_price = close.iloc[j]
                    exit_date = str(df.index[j])
                    outcome = "MAX_HOLD"
                    bars_held = j - i
                    break

                # SL hit
                if low.iloc[j] <= sl:
                    exit_price = sl
                    exit_date = str(df.index[j])
                    outcome = "SL_HIT"
                    bars_held = j - i
                    break

                # TP hit
                if high.iloc[j] >= tp:
                    exit_price = tp
                    exit_date = str(df.index[j])
                    outcome = "TP_HIT"
                    bars_held = j - i
                    break

            in_trade = False

            # P&L in EUR: (exit - entry) × shares - round-trip commission
            round_trip_commission = costs.commission * 2
            pnl_eur = (exit_price - entry_price) * shares - round_trip_commission

            trades.append({
                "direction": "LONG",
                "entry_date": str(df.index[i]),
                "exit_date": exit_date,
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "sl": round(sl, 2),
                "tp": round(tp, 2),
                "shares": shares,
                "pnl_eur": round(pnl_eur, 2),
                "commission": round(round_trip_commission, 2),
                "status": outcome,
                "bars_held": bars_held,
            })

        result.trades = trades
        result.total_trades = len(trades)
        result.long_trades = len(trades)

        if trades:
            pnls = [t["pnl_eur"] for t in trades]
            winners = [p for p in pnls if p > 0]
            losers = [p for p in pnls if p <= 0]

            result.total_pnl_eur = sum(pnls)
            result.avg_trade_pnl = np.mean(pnls)
            result.win_rate = len(winners) / len(pnls) if pnls else 0

            gross_profit = sum(winners) if winners else 0
            gross_loss = abs(sum(losers)) if losers else 0
            result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

            # Equity curve in EUR
            equity_curve = starting_equity + np.cumsum(pnls)
            peak = np.maximum.accumulate(equity_curve)
            dd_eur = peak - equity_curve
            dd_pct = dd_eur / peak
            result.max_drawdown_eur = float(np.max(dd_eur))
            result.max_drawdown_pct = float(np.max(dd_pct)) * 100
            result.return_pct = (equity_curve[-1] - starting_equity) / starting_equity * 100

            # Sharpe (annualized)
            if len(pnls) > 1 and np.std(pnls) > 0:
                result.sharpe_ratio = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252)

            # Sortino
            downside = [p for p in pnls if p < 0]
            if downside and np.std(downside) > 0:
                result.sortino_ratio = (np.mean(pnls) / np.std(downside)) * np.sqrt(252)

            # Calmar
            if result.max_drawdown_eur > 0:
                result.calmar_ratio = result.total_pnl_eur / result.max_drawdown_eur

            # Expectancy and Kelly (in EUR)
            avg_win = np.mean(winners) if winners else 0
            avg_loss = np.mean([abs(x) for x in losers]) if losers else 0
            result.expectancy_eur = (result.win_rate * avg_win) - ((1 - result.win_rate) * avg_loss)

            if avg_loss > 0 and avg_win > 0:
                b = avg_win / avg_loss
                kelly = (result.win_rate * b - (1 - result.win_rate)) / b
                result.kelly_fraction = max(0, min(kelly / 2, 0.5))

            result.total_costs_eur = sum(t["commission"] for t in trades)

        return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_results(results: list[VBTBacktestResult]) -> None:
    """Pretty-print backtest results for all ETFs (all PnL in EUR)."""
    if not results:
        print("No results to display.")
        return

    W = 120
    print()
    print("=" * W)
    print(
        f"{'SYMBOL':<10} {'SRC':<6} {'BARS':>4} "
        f"{'#':>3} {'WIN%':>6} {'PF':>5} "
        f"{'PnL EUR':>10} {'Costs':>7} {'DD%':>6} {'DD EUR':>8} "
        f"{'Sharpe':>6} {'Sortino':>7} {'Kelly':>5} {'Ret%':>7}"
    )
    print("-" * W)

    total_trades = 0
    total_pnl = 0.0
    total_costs = 0.0

    for r in sorted(results, key=lambda x: x.symbol):
        print(
            f"{r.symbol:<10} {r.data_source[:6]:<6} {r.bars:>4} "
            f"{r.total_trades:>3} {r.win_rate*100:>5.1f}% {r.profit_factor:>5.2f} "
            f"{r.total_pnl_eur:>+10.0f} {r.total_costs_eur:>7.0f} "
            f"{r.max_drawdown_pct:>5.1f}% {r.max_drawdown_eur:>8.0f} "
            f"{r.sharpe_ratio:>6.2f} {r.sortino_ratio:>7.2f} "
            f"{r.kelly_fraction*100:>4.1f}% {r.return_pct:>+6.1f}%"
        )
        total_trades += r.total_trades
        total_pnl += r.total_pnl_eur
        total_costs += r.total_costs_eur

    print("-" * W)
    print(
        f"{'TOTAL':<10} {'':6} {'':>4} "
        f"{total_trades:>3} {'':>6} {'':>5} "
        f"{total_pnl:>+10.0f} {total_costs:>7.0f}"
    )
    print("=" * W)

    # Profitable/losing summary
    profitable = [r for r in results if r.total_pnl_eur > 0]
    losing = [r for r in results if r.total_pnl_eur <= 0]
    print(f"\nProfitable ({len(profitable)}):", ", ".join(
        f"{r.symbol} (EUR{r.total_pnl_eur:+,.0f})" for r in
        sorted(profitable, key=lambda x: x.total_pnl_eur, reverse=True)
    ) or "none")
    print(f"Losing ({len(losing)}):", ", ".join(
        f"{r.symbol} (EUR{r.total_pnl_eur:+,.0f})" for r in
        sorted(losing, key=lambda x: x.total_pnl_eur)
    ) or "none")

    # Trade list
    print("\nDetailed Trades:")
    for r in results:
        if not r.trades:
            continue
        print(f"\n  {r.symbol} (position size: EUR{r.position_size_eur:,.0f}):")
        print(f"  {'#':>3}  {'Entry':>10} {'Exit':>10} {'Shares':>6} {'PnL EUR':>10} {'Status':<10} {'Days':>4} {'Date'}")
        print(f"  {'---':>3}  {'--------':>10} {'--------':>10} {'------':>6} {'-------':>10} {'------':<10} {'----':>4} {'----------'}")
        for i, t in enumerate(r.trades, 1):
            print(
                f"  {i:>3}  {t['entry_price']:>10.2f} "
                f"{t['exit_price']:>10.2f} {t.get('shares', '-'):>6} "
                f"{t['pnl_eur']:>+10.2f} "
                f"{t['status']:<10} {t['bars_held']:>4} {t['entry_date'][:10]}"
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

    # Default ETF symbols for backtesting
    DEFAULT_SYMBOLS = ["SWDA.MI", "CSSPX.MI", "EQQQ.MI"]

    parser = argparse.ArgumentParser(
        description="ETF Swing Trader — vectorbt Backtester (LONG-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m modules.vbt_backtester --symbols SWDA.MI CSSPX.MI EQQQ.MI
  python -m modules.vbt_backtester --all --bars 500
  python -m modules.vbt_backtester --symbols EQQQ.MI --bars 250
  python -m modules.vbt_backtester --all --equity 5000
        """,
    )
    parser.add_argument("--symbols", nargs="+", help="ETF symbols to backtest (e.g. SWDA.MI EQQQ.MI)")
    parser.add_argument("--all", action="store_true", help="Backtest all 8 UCITS ETFs")
    parser.add_argument("--bars", type=int, default=500, help="Number of daily bars (default: 500)")
    parser.add_argument("--sl-mult", type=float, default=None,
                        help="Override SL ATR multiplier (default: 1.5)")
    parser.add_argument("--tp-mult", type=float, default=None,
                        help="Override TP ATR multiplier (default: 3.0)")
    parser.add_argument("--equity", type=float, default=DEFAULT_EQUITY,
                        help=f"Starting equity in EUR (default: {DEFAULT_EQUITY:.0f})")
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

    bt = VBTBacktester()

    common_kwargs: dict[str, Any] = {
        "interval": "1d",  # Daily only for swing trading
        "bars": args.bars,
        "sl_atr_mult": args.sl_mult,
        "tp_atr_mult": args.tp_mult,
        "adaptive_sl": not args.no_adaptive,
        "starting_equity": args.equity,
        "qs_filter": not args.no_qs_filter,
        "qs_min": args.qs_min,
    }

    if args.all:
        results = bt.run_universe(**common_kwargs)
    elif args.symbols:
        results = bt.run_universe(symbols=args.symbols, **common_kwargs)
    else:
        results = bt.run_universe(symbols=DEFAULT_SYMBOLS, **common_kwargs)

    print_results(results)


if __name__ == "__main__":
    main()
