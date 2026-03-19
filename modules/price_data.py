"""Price data and technical indicators module.

Downloads OHLCV data via yfinance (primary) or Twelve Data (fallback),
and computes technical indicators using pandas-ta. Returns structured
analysis per asset.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0

# ---------------------------------------------------------------------------
# Twelve Data fallback configuration
# ---------------------------------------------------------------------------
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
_TWELVE_DATA_BASE = "https://api.twelvedata.com"

# yfinance symbol → (Twelve Data symbol, asset type)
_TD_SYMBOL_MAP: dict[str, tuple[str, str]] = {
    "NQ=F": ("NQ", "futures"),
    "ES=F": ("ES", "futures"),
    "GC=F": ("GC", "futures"),
    "CL=F": ("CL", "futures"),
    "EURUSD=X": ("EUR/USD", "forex"),
    "GBPUSD=X": ("GBP/USD", "forex"),
}

# Twelve Data interval mapping
_TD_INTERVAL_MAP: dict[str, str] = {
    "1d": "1day",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
}


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
    data_source: str = "yfinance"
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
            "data_source": self.data_source,
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


# ---------------------------------------------------------------------------
# Data fetching — yfinance (primary) + Twelve Data (fallback)
# ---------------------------------------------------------------------------

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


def _fetch_twelvedata(
    symbol: str,
    interval: str = "1d",
    outputsize: int = 60,
) -> pd.DataFrame | None:
    """Fetch OHLCV data from Twelve Data API as fallback.

    Returns a DataFrame with Open/High/Low/Close/Volume columns
    matching the yfinance format, or None if unavailable.
    """
    if not TWELVE_DATA_API_KEY:
        return None

    td_info = _TD_SYMBOL_MAP.get(symbol)
    if td_info:
        td_symbol = td_info[0]
    else:
        td_symbol = symbol.replace("=F", "").replace("=X", "")
    td_interval = _TD_INTERVAL_MAP.get(interval, interval)

    params = {
        "symbol": td_symbol,
        "interval": td_interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
    }

    try:
        resp = requests.get(
            f"{_TWELVE_DATA_BASE}/time_series",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "values" not in data:
            logger.warning(
                "Twelve Data no values for %s: %s",
                symbol,
                data.get("message", data.get("status", "")),
            )
            return None

        rows = data["values"]
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
        df.sort_index(inplace=True)

        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            },
            inplace=True,
        )

        if "Volume" not in df.columns:
            df["Volume"] = 0.0

        return df if not df.empty else None
    except Exception as exc:
        logger.warning("Twelve Data failed for %s: %s", symbol, exc)
        return None


def _fetch_daily(symbol: str) -> tuple[pd.DataFrame, str]:
    """Fetch daily data, trying yfinance first then Twelve Data.

    Returns (dataframe, source_name).
    """
    try:
        df = _fetch_with_retry(symbol, period="60d", interval="1d")
        if df is not None and not df.empty:
            return df, "yfinance"
    except Exception as exc:
        logger.warning("yfinance daily failed for %s: %s", symbol, exc)

    df = _fetch_twelvedata(symbol, interval="1d", outputsize=60)
    if df is not None and not df.empty:
        logger.info("Using Twelve Data fallback for %s (daily)", symbol)
        return df, "twelvedata"

    raise ValueError(f"No daily data available for {symbol} from any source")


def _fetch_intraday(symbol: str) -> tuple[pd.DataFrame, str]:
    """Fetch 5-minute intraday data, trying yfinance first then Twelve Data.

    Returns (dataframe, source_name).
    """
    try:
        df = _fetch_with_retry(symbol, period="5d", interval="5m")
        if df is not None and not df.empty:
            return df, "yfinance"
    except Exception as exc:
        logger.warning("yfinance 5m failed for %s: %s", symbol, exc)

    df = _fetch_twelvedata(symbol, interval="5m", outputsize=200)
    if df is not None and not df.empty:
        logger.info("Using Twelve Data fallback for %s (5m)", symbol)
        return df, "twelvedata"

    return pd.DataFrame(), "none"


# ---------------------------------------------------------------------------
# Technical analysis
# ---------------------------------------------------------------------------

def _analyze_single_asset(symbol: str, display_name: str) -> AssetAnalysis:
    """Download data and compute indicators for a single asset."""
    # Daily data for trend indicators
    df_daily, daily_source = _fetch_daily(symbol)

    # 5-minute data for intraday context
    df_5m, _ = _fetch_intraday(symbol)

    current_price = float(df_daily["Close"].iloc[-1])
    prev_close = float(df_daily["Close"].iloc[-2]) if len(df_daily) >= 2 else current_price
    change_pct = ((current_price - prev_close) / prev_close) * 100

    signals: list[TechnicalSignal] = []

    # --- RSI(14) ---
    try:
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
    except Exception as exc:
        logger.warning("RSI failed for %s: %s", symbol, exc)

    # --- MACD(12, 26, 9) ---
    try:
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
    except Exception as exc:
        logger.warning("MACD failed for %s: %s", symbol, exc)

    # --- Bollinger Bands (20, 2) ---
    try:
        bbands = ta.bbands(df_daily["Close"], length=20, std=2)
        if bbands is not None and not bbands.empty:
            bb_cols = bbands.columns.tolist()
            upper = float(bbands[[c for c in bb_cols if c.startswith("BBU_")][0]].iloc[-1])
            middle = float(bbands[[c for c in bb_cols if c.startswith("BBM_")][0]].iloc[-1])
            lower = float(bbands[[c for c in bb_cols if c.startswith("BBL_")][0]].iloc[-1])
            bandwidth = float(bbands[[c for c in bb_cols if c.startswith("BBB_")][0]].iloc[-1])

            if current_price > upper:
                label = "BEARISH"
                detail = f"Above upper BB ({upper:.2f}) — overextended"
            elif current_price < lower:
                label = "BULLISH"
                detail = f"Below lower BB ({lower:.2f}) — oversold"
            elif bandwidth < 4.0:
                label = "NEUTRAL"
                detail = f"BB squeeze (bw {bandwidth:.1f}%) — breakout pending"
            elif current_price > middle:
                label = "BULLISH"
                detail = f"Above mid BB ({middle:.2f}), bw {bandwidth:.1f}%"
            else:
                label = "BEARISH"
                detail = f"Below mid BB ({middle:.2f}), bw {bandwidth:.1f}%"
            signals.append(TechnicalSignal("BBANDS", bandwidth, label, detail))
    except Exception as exc:
        logger.warning("Bollinger Bands failed for %s: %s", symbol, exc)

    # --- Stochastic (14, 3, 3) ---
    try:
        stoch = ta.stoch(df_daily["High"], df_daily["Low"], df_daily["Close"], k=14, d=3, smooth_k=3)
        if stoch is not None and not stoch.empty:
            stoch_cols = stoch.columns.tolist()
            k_col = [c for c in stoch_cols if c.startswith("STOCHk_")][0]
            d_col = [c for c in stoch_cols if c.startswith("STOCHd_")][0]

            k_val = float(stoch[k_col].iloc[-1])
            d_val = float(stoch[d_col].iloc[-1])
            prev_k = float(stoch[k_col].iloc[-2]) if len(stoch) >= 2 else k_val
            prev_d = float(stoch[d_col].iloc[-2]) if len(stoch) >= 2 else d_val

            k_cross_up = prev_k <= prev_d and k_val > d_val
            k_cross_down = prev_k >= prev_d and k_val < d_val

            if k_cross_up and k_val < 30:
                label = "BULLISH"
                detail = f"Stoch %K {k_val:.1f} — oversold + bullish crossover"
            elif k_cross_down and k_val > 70:
                label = "BEARISH"
                detail = f"Stoch %K {k_val:.1f} — overbought + bearish crossover"
            elif k_cross_up:
                label = "BULLISH"
                detail = f"Stoch %K {k_val:.1f} — bullish crossover"
            elif k_cross_down:
                label = "BEARISH"
                detail = f"Stoch %K {k_val:.1f} — bearish crossover"
            elif k_val > 80:
                label = "BEARISH"
                detail = f"Stoch %K {k_val:.1f} — overbought"
            elif k_val < 20:
                label = "BULLISH"
                detail = f"Stoch %K {k_val:.1f} — oversold"
            else:
                label = "NEUTRAL"
                detail = f"Stoch %K {k_val:.1f} / %D {d_val:.1f}"
            signals.append(TechnicalSignal("STOCH", k_val, label, detail))
    except Exception as exc:
        logger.warning("Stochastic failed for %s: %s", symbol, exc)

    # --- VWAP (using intraday data) ---
    if not df_5m.empty and "Volume" in df_5m.columns and df_5m["Volume"].sum() > 0:
        try:
            vwap_series = ta.vwap(df_5m["High"], df_5m["Low"], df_5m["Close"], df_5m["Volume"])
            if vwap_series is not None and not vwap_series.empty:
                vwap_val = float(vwap_series.iloc[-1])
                current_5m = float(df_5m["Close"].iloc[-1])
                pct_diff = ((current_5m - vwap_val) / vwap_val) * 100
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
        except Exception as exc:
            logger.warning("VWAP failed for %s: %s", symbol, exc)
            signals.append(TechnicalSignal("VWAP", None, "NEUTRAL", "VWAP calculation error"))
    else:
        signals.append(TechnicalSignal("VWAP", None, "NEUTRAL", "VWAP not available (no volume)"))

    # --- ATR(14) ---
    try:
        atr_series = ta.atr(df_daily["High"], df_daily["Low"], df_daily["Close"], length=14)
        if atr_series is not None and not atr_series.empty:
            atr_val = float(atr_series.iloc[-1])
            atr_pct = (atr_val / current_price) * 100
            if atr_pct > 2.0:
                label, detail = "NEUTRAL", f"ATR {atr_val:.2f} ({atr_pct:.2f}%) — high volatility"
            else:
                label, detail = "NEUTRAL", f"ATR {atr_val:.2f} ({atr_pct:.2f}%) — normal volatility"
            signals.append(TechnicalSignal("ATR", atr_val, label, detail))
    except Exception as exc:
        logger.warning("ATR failed for %s: %s", symbol, exc)

    # --- EMA(20) vs EMA(50) ---
    try:
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
    except Exception as exc:
        logger.warning("EMA failed for %s: %s", symbol, exc)

    # --- ADX(14) — trend strength (non-directional) ---
    try:
        adx_df = ta.adx(df_daily["High"], df_daily["Low"], df_daily["Close"], length=14)
        if adx_df is not None and not adx_df.empty:
            adx_cols = adx_df.columns.tolist()
            adx_val = float(adx_df[[c for c in adx_cols if c.startswith("ADX_")][0]].iloc[-1])
            dmp_val = float(adx_df[[c for c in adx_cols if c.startswith("DMP_")][0]].iloc[-1])
            dmn_val = float(adx_df[[c for c in adx_cols if c.startswith("DMN_")][0]].iloc[-1])

            if adx_val >= 25:
                trend_dir = "bullish" if dmp_val > dmn_val else "bearish"
                detail = f"ADX {adx_val:.1f} — strong {trend_dir} trend (+DI {dmp_val:.1f} / -DI {dmn_val:.1f})"
            else:
                detail = f"ADX {adx_val:.1f} — weak/ranging (+DI {dmp_val:.1f} / -DI {dmn_val:.1f})"
            signals.append(TechnicalSignal("ADX", adx_val, "NEUTRAL", detail))
    except Exception as exc:
        logger.warning("ADX failed for %s: %s", symbol, exc)

    # --- Composite score — 6-point system ---
    # Directional indicators: RSI, MACD, VWAP, EMA_TREND, BBANDS, STOCH
    # Non-directional (excluded): ATR, ADX
    directional_names = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}
    directional_signals = [s for s in signals if s.name in directional_names]
    bullish_count = sum(1 for s in directional_signals if s.label == "BULLISH")
    total = len(directional_signals) or 6

    if bullish_count >= 4:
        composite = "BULLISH"
        confidence = (bullish_count / total) * 100
    elif bullish_count <= 2:
        bearish_count = sum(1 for s in directional_signals if s.label == "BEARISH")
        if bearish_count >= 4:
            composite = "BEARISH"
            confidence = (bearish_count / total) * 100
        else:
            composite = "NEUTRAL"
            confidence = 50.0
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
        data_source=daily_source,
    )


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    results = analyze_assets(config["assets"])
    for r in results:
        print(f"\n{'='*60}")
        print(f"{r.display_name} ({r.symbol}) [source: {r.data_source}]")
        if r.error:
            print(f"  ERROR: {r.error}")
            continue
        print(f"  Price: {r.price:.2f} ({r.change_pct:+.2f}%)")
        for s in r.signals:
            print(f"  {s.name}: {s.label} — {s.detail}")
        print(f"  Composite: {r.composite_score} ({r.confidence_pct}%)")
