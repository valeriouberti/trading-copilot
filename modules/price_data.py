"""Price data and technical indicators module.

Downloads OHLCV data via yfinance and computes technical indicators
using pandas-ta. Returns structured analysis per asset.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pandas_ta as ta
import yfinance as yf

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0


@dataclass
class TechnicalSignal:
    """A single technical indicator result."""
    name: str
    value: float | None
    label: str  # "BULLISH", "BEARISH", or "NEUTRAL"
    detail: str  # Human-readable explanation


@dataclass
class AssetAnalysis:
    """Complete technical analysis for one asset."""
    symbol: str
    display_name: str
    price: float | None
    change_pct: float | None
    signals: list[TechnicalSignal] = field(default_factory=list)
    composite_score: str = "NEUTRAL"
    confidence_pct: float = 50.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "display_name": self.display_name,
            "price": self.price,
            "change_pct": self.change_pct,
            "signals": {s.name: {"value": s.value, "label": s.label, "detail": s.detail} for s in self.signals},
            "composite_score": self.composite_score,
            "confidence_pct": self.confidence_pct,
            "error": self.error,
        }


def analyze_assets(assets: list[dict[str, str]]) -> list[AssetAnalysis]:
    """Run technical analysis on all configured assets.

    Args:
        assets: List of dicts with 'symbol' and 'display_name' keys.

    Returns:
        List of AssetAnalysis objects.
    """
    results: list[AssetAnalysis] = []
    for asset_cfg in assets:
        symbol = asset_cfg["symbol"]
        display_name = asset_cfg.get("display_name", symbol)
        logger.info("Analyzing %s (%s)...", display_name, symbol)
        try:
            analysis = _analyze_single_asset(symbol, display_name)
        except Exception as exc:
            logger.error("Error analyzing %s: %s", symbol, exc)
            analysis = AssetAnalysis(
                symbol=symbol,
                display_name=display_name,
                price=None,
                change_pct=None,
                error=str(exc),
            )
        results.append(analysis)
    return results


def _fetch_with_retry(symbol: str, period: str, interval: str):
    """Fetch yfinance data with retry and exponential backoff."""
    ticker = yf.Ticker(symbol)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = ticker.history(period=period, interval=interval, timeout=15)
            return df
        except Exception as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BACKOFF_BASE ** attempt
            logger.warning(
                "yfinance %s (%s/%s) failed (attempt %d/%d), retry in %.1fs: %s",
                symbol, period, interval, attempt, MAX_RETRIES, wait, exc,
            )
            time.sleep(wait)
    return None


def _analyze_single_asset(symbol: str, display_name: str) -> AssetAnalysis:
    """Download data and compute indicators for a single asset."""
    # Daily data for trend indicators (with retry)
    df_daily = _fetch_with_retry(symbol, period="60d", interval="1d")
    if df_daily is None or df_daily.empty:
        raise ValueError(f"No daily data returned for {symbol}")

    # 5-minute data for intraday context (with retry)
    try:
        df_5m = _fetch_with_retry(symbol, period="5d", interval="5m")
        if df_5m is None:
            df_5m = _fetch_with_retry(symbol, period="5d", interval="5m")
    except Exception as exc:
        logger.warning("Could not fetch 5m data for %s: %s", symbol, exc)
        import pandas as pd
        df_5m = pd.DataFrame()

    current_price = float(df_daily["Close"].iloc[-1])
    prev_close = float(df_daily["Close"].iloc[-2]) if len(df_daily) >= 2 else current_price
    change_pct = ((current_price - prev_close) / prev_close) * 100

    signals: list[TechnicalSignal] = []

    # RSI(14)
    rsi_series = ta.rsi(df_daily["Close"], length=14)
    if rsi_series is not None and not rsi_series.empty:
        rsi_val = float(rsi_series.iloc[-1])
        if rsi_val > 70:
            rsi_label, rsi_detail = "BEARISH", f"RSI {rsi_val:.1f} — overbought"
        elif rsi_val < 30:
            rsi_label, rsi_detail = "BULLISH", f"RSI {rsi_val:.1f} — oversold"
        elif rsi_val > 60:
            rsi_label, rsi_detail = "BULLISH", f"RSI {rsi_val:.1f} — bullish momentum"
        elif rsi_val < 40:
            rsi_label, rsi_detail = "BEARISH", f"RSI {rsi_val:.1f} — bearish momentum"
        else:
            rsi_label, rsi_detail = "NEUTRAL", f"RSI {rsi_val:.1f} — neutral"
        signals.append(TechnicalSignal("RSI", rsi_val, rsi_label, rsi_detail))

    # MACD(12, 26, 9)
    macd_df = ta.macd(df_daily["Close"], fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        macd_hist = float(macd_df.iloc[-1, 1])

        prev_hist = float(macd_df.iloc[-2, 1]) if len(macd_df) >= 2 else 0

        if macd_hist > 0 and prev_hist <= 0:
            label, detail = "BULLISH", "MACD bullish crossover"
        elif macd_hist < 0 and prev_hist >= 0:
            label, detail = "BEARISH", "MACD bearish crossover"
        elif macd_hist > 0:
            label, detail = "BULLISH", f"MACD positive ({macd_hist:.2f})"
        elif macd_hist < 0:
            label, detail = "BEARISH", f"MACD negative ({macd_hist:.2f})"
        else:
            label, detail = "NEUTRAL", "MACD neutral"
        signals.append(TechnicalSignal("MACD", macd_hist, label, detail))

    # VWAP (using intraday data)
    if not df_5m.empty and "Volume" in df_5m.columns and df_5m["Volume"].sum() > 0:
        vwap_series = ta.vwap(df_5m["High"], df_5m["Low"], df_5m["Close"], df_5m["Volume"])
        if vwap_series is not None and not vwap_series.empty:
            vwap_val = float(vwap_series.iloc[-1])
            current_5m = float(df_5m["Close"].iloc[-1])
            pct_diff = ((current_5m - vwap_val) / vwap_val) * 100
            # Only signal directional if distance > 0.1% from VWAP
            if abs(pct_diff) < 0.1:
                label = "NEUTRAL"
                detail = f"Price ≈ VWAP ({pct_diff:+.2f}%) — too close"
            elif current_5m > vwap_val:
                label = "BULLISH"
                detail = f"Price above VWAP ({pct_diff:+.2f}%)"
            else:
                label = "BEARISH"
                detail = f"Price below VWAP ({pct_diff:+.2f}%)"
            signals.append(TechnicalSignal("VWAP", vwap_val, label, detail))
    else:
        # For FX pairs and instruments without volume, skip VWAP
        signals.append(TechnicalSignal("VWAP", None, "NEUTRAL", "VWAP not available (no volume)"))

    # ATR(14)
    atr_series = ta.atr(df_daily["High"], df_daily["Low"], df_daily["Close"], length=14)
    if atr_series is not None and not atr_series.empty:
        atr_val = float(atr_series.iloc[-1])
        atr_pct = (atr_val / current_price) * 100
        if atr_pct > 2.0:
            label, detail = "NEUTRAL", f"ATR {atr_val:.2f} ({atr_pct:.2f}%) — high volatility"
        else:
            label, detail = "NEUTRAL", f"ATR {atr_val:.2f} ({atr_pct:.2f}%) — normal volatility"
        signals.append(TechnicalSignal("ATR", atr_val, label, detail))

    # EMA(20) vs EMA(50)
    ema20 = ta.ema(df_daily["Close"], length=20)
    ema50 = ta.ema(df_daily["Close"], length=50)
    if ema20 is not None and ema50 is not None and not ema20.empty and not ema50.empty:
        ema20_val = float(ema20.iloc[-1])
        ema50_val = float(ema50.iloc[-1])
        if ema20_val > ema50_val and current_price > ema20_val:
            label = "BULLISH"
            detail = f"EMA20 ({ema20_val:.2f}) > EMA50 ({ema50_val:.2f}), price above both"
        elif ema20_val > ema50_val:
            label = "BULLISH"
            detail = f"EMA20 ({ema20_val:.2f}) > EMA50 ({ema50_val:.2f})"
        elif ema20_val < ema50_val and current_price < ema20_val:
            label = "BEARISH"
            detail = f"EMA20 ({ema20_val:.2f}) < EMA50 ({ema50_val:.2f}), price below both"
        elif ema20_val < ema50_val:
            label = "BEARISH"
            detail = f"EMA20 ({ema20_val:.2f}) < EMA50 ({ema50_val:.2f})"
        else:
            label = "NEUTRAL"
            detail = f"EMA20 ≈ EMA50 ({ema20_val:.2f})"
        signals.append(TechnicalSignal("EMA_TREND", ema20_val, label, detail))

    # Composite score — 4-point system (EMA, VWAP, RSI, MACD only; ATR excluded)
    directional_names = {"RSI", "MACD", "VWAP", "EMA_TREND"}
    directional_signals = [s for s in signals if s.name in directional_names]
    bullish_count = sum(1 for s in directional_signals if s.label == "BULLISH")
    total = len(directional_signals) or 4

    if bullish_count >= 3:
        composite = "BULLISH"
        confidence = (bullish_count / total) * 100
    elif bullish_count <= 1:
        composite = "BEARISH"
        confidence = ((total - bullish_count) / total) * 100
    else:
        composite = "NEUTRAL"
        confidence = 50.0

    return AssetAnalysis(
        symbol=symbol,
        display_name=display_name,
        price=current_price,
        change_pct=change_pct,
        signals=signals,
        composite_score=composite,
        confidence_pct=round(confidence, 1),
    )


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    results = analyze_assets(config["assets"])
    for r in results:
        print(f"\n{'='*50}")
        print(f"{r.display_name} ({r.symbol})")
        if r.error:
            print(f"  ERROR: {r.error}")
            continue
        print(f"  Price: {r.price:.2f} ({r.change_pct:+.2f}%)")
        for s in r.signals:
            print(f"  {s.name}: {s.label} — {s.detail}")
        print(f"  Composite: {r.composite_score} ({r.confidence_pct}%)")
