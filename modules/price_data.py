"""Price data and technical indicators module.

Downloads OHLCV data via yfinance (primary) or Twelve Data (fallback),
and computes technical indicators using pandas-ta. Returns structured
analysis per asset.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf

from modules.exceptions import (
    DataFetchPermanent,
    DataFetchTransient,
    NoDataAvailable,
)
from modules.retry import retry_data_fetch

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
    "1wk": "1week",
}


import math

from modules.strategy import (
    classify_regime,
    compute_composite,
    detect_candle_pattern as _strategy_detect_candle,
    label_bbands,
    label_ema_trend,
    label_macd,
    label_rsi,
    label_stochastic,
    Regime,
    MOMENTUM_INDICATORS,
    MEAN_REVERSION_INDICATORS,
    COMPOSITE_THRESHOLD,
)


@dataclass
class TechnicalSignal:
    """A single technical indicator result."""

    name: str
    value: float | None
    label: str  # "BULLISH", "BEARISH", or "NEUTRAL"
    detail: str  # Human-readable explanation


@dataclass
class KeyLevels:
    """Key support/resistance levels for an asset."""

    pdh: float | None = None  # Previous Day High
    pdl: float | None = None  # Previous Day Low
    pdc: float | None = None  # Previous Day Close
    pwh: float | None = None  # Previous Week High
    pwl: float | None = None  # Previous Week Low
    pp: float | None = None  # Pivot Point
    r1: float | None = None  # Resistance 1
    r2: float | None = None  # Resistance 2
    s1: float | None = None  # Support 1
    s2: float | None = None  # Support 2
    psych_above: float | None = None  # Nearest psychological level above
    psych_below: float | None = None  # Nearest psychological level below
    nearest_level: float | None = None  # Closest level to current price
    nearest_level_name: str = ""  # Name of closest level
    nearest_level_dist_pct: float | None = None  # Distance % to closest level

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdh": self.pdh,
            "pdl": self.pdl,
            "pdc": self.pdc,
            "pwh": self.pwh,
            "pwl": self.pwl,
            "pp": self.pp,
            "r1": self.r1,
            "r2": self.r2,
            "s1": self.s1,
            "s2": self.s2,
            "psych_above": self.psych_above,
            "psych_below": self.psych_below,
            "nearest_level": self.nearest_level,
            "nearest_level_name": self.nearest_level_name,
            "nearest_level_dist_pct": self.nearest_level_dist_pct,
        }

    def all_levels(self) -> list[tuple[str, float]]:
        """Return all non-None levels as (name, value) pairs."""
        pairs = [
            ("PDH", self.pdh),
            ("PDL", self.pdl),
            ("PDC", self.pdc),
            ("PWH", self.pwh),
            ("PWL", self.pwl),
            ("PP", self.pp),
            ("R1", self.r1),
            ("R2", self.r2),
            ("S1", self.s1),
            ("S2", self.s2),
            ("Psych", self.psych_above),
            ("Psych", self.psych_below),
        ]
        return [(n, v) for n, v in pairs if v is not None]


@dataclass
class MTFAnalysis:
    """Multi-timeframe trend alignment analysis."""

    weekly_trend: str = "NEUTRAL"
    daily_trend: str = "NEUTRAL"
    hourly_trend: str = "NEUTRAL"
    alignment: str = "CONFLICTING"  # ALIGNED, PARTIAL, CONFLICTING
    dominant_direction: str = "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "weekly_trend": self.weekly_trend,
            "daily_trend": self.daily_trend,
            "hourly_trend": self.hourly_trend,
            "alignment": self.alignment,
            "dominant_direction": self.dominant_direction,
        }


@dataclass
class QualityScore:
    """Setup quality score (1-5) for an asset.

    Each factor adds +1:
    - confluence: 4+ directional signals agree
    - strong_trend: ADX > 25
    - near_key_level: price within 0.5% of S/R
    - candle_pattern: engulfing or pin bar on last daily candle
    - volume_above_avg: last bar volume > 20-day average
    """

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
    key_levels: KeyLevels | None = None
    mtf: MTFAnalysis | None = None
    quality_score: QualityScore | None = None
    daily_closes: pd.Series | None = field(default=None, repr=False)
    ohlc_data: list[dict] | None = field(default=None, repr=False)
    ema20_data: list[dict] | None = field(default=None, repr=False)
    ema50_data: list[dict] | None = field(default=None, repr=False)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "display_name": self.display_name,
            "price": self.price,
            "change_pct": self.change_pct,
            "signals": {
                s.name: {"value": s.value, "label": s.label, "detail": s.detail}
                for s in self.signals
            },
            "composite_score": self.composite_score,
            "confidence_pct": self.confidence_pct,
            "data_source": self.data_source,
            "key_levels": self.key_levels.to_dict() if self.key_levels else None,
            "mtf": self.mtf.to_dict() if self.mtf else None,
            "quality_score": self.quality_score.to_dict()
            if self.quality_score
            else None,
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
        except (DataFetchTransient, DataFetchPermanent, NoDataAvailable) as exc:
            logger.error("Data fetch error for %s: %s", symbol, exc)
            analysis = AssetAnalysis(
                symbol=symbol,
                display_name=display_name,
                price=None,
                change_pct=None,
                error=str(exc),
            )
        except Exception as exc:
            logger.error("Unexpected error analyzing %s: %s", symbol, exc)
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


@retry_data_fetch(max_attempts=MAX_RETRIES)
def _fetch_with_retry(symbol: str, period: str, interval: str):
    """Fetch yfinance data with retry and exponential backoff."""
    ticker = yf.Ticker(symbol)
    try:
        df = ticker.history(period=period, interval=interval, timeout=15)
        return df
    except Exception as exc:
        raise DataFetchTransient(
            symbol=symbol,
            source="yfinance",
            detail=str(exc),
        ) from exc


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
    except DataFetchTransient as exc:
        logger.warning("yfinance daily failed for %s: %s", symbol, exc)
    except Exception as exc:
        logger.warning("yfinance daily failed for %s: %s", symbol, exc)

    df = _fetch_twelvedata(symbol, interval="1d", outputsize=60)
    if df is not None and not df.empty:
        logger.info("Using Twelve Data fallback for %s (daily)", symbol)
        return df, "twelvedata"

    raise NoDataAvailable(
        symbol=symbol, source="all", detail="No daily data from any source"
    )


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


def _fetch_weekly(symbol: str) -> tuple[pd.DataFrame, str]:
    """Fetch weekly data, trying yfinance first then Twelve Data.

    Returns (dataframe, source_name). Needs ~52+ bars for EMA50.
    """
    try:
        df = _fetch_with_retry(symbol, period="2y", interval="1wk")
        if df is not None and not df.empty:
            return df, "yfinance"
    except Exception as exc:
        logger.warning("yfinance weekly failed for %s: %s", symbol, exc)

    df = _fetch_twelvedata(symbol, interval="1wk", outputsize=104)
    if df is not None and not df.empty:
        logger.info("Using Twelve Data fallback for %s (weekly)", symbol)
        return df, "twelvedata"

    return pd.DataFrame(), "none"


def _fetch_hourly(symbol: str) -> tuple[pd.DataFrame, str]:
    """Fetch 1-hour data, trying yfinance first then Twelve Data.

    Returns (dataframe, source_name). Needs ~50+ bars for EMA50.
    """
    try:
        df = _fetch_with_retry(symbol, period="30d", interval="1h")
        if df is not None and not df.empty:
            return df, "yfinance"
    except Exception as exc:
        logger.warning("yfinance 1h failed for %s: %s", symbol, exc)

    df = _fetch_twelvedata(symbol, interval="1h", outputsize=200)
    if df is not None and not df.empty:
        logger.info("Using Twelve Data fallback for %s (1h)", symbol)
        return df, "twelvedata"

    return pd.DataFrame(), "none"


# ---------------------------------------------------------------------------
# Key Levels (Support / Resistance)
# ---------------------------------------------------------------------------


def _psych_step(price: float) -> float:
    """Determine psychological level step size based on price magnitude."""
    if price < 2:
        return 0.01  # Forex (EURUSD ~1.08)
    elif price < 20:
        return 0.5
    elif price < 200:
        return 10
    elif price < 2000:
        return 50
    elif price < 6000:
        return 100  # ES (~5800)
    elif price < 25000:
        return 500  # NQ (~21000)
    else:
        return 1000


def _compute_key_levels(df_daily: pd.DataFrame, current_price: float) -> KeyLevels:
    """Compute key S/R levels from daily OHLCV data.

    Calculates:
    - Previous Day High/Low/Close (PDH/PDL/PDC)
    - Previous Week High/Low (PWH/PWL)
    - Classic Pivot Points (PP, R1, R2, S1, S2)
    - Nearest psychological (round-number) levels
    - Nearest overall level and distance %
    """
    levels = KeyLevels()

    if len(df_daily) < 2:
        return levels

    # --- Previous Day ---
    prev_day = df_daily.iloc[-2]
    levels.pdh = float(prev_day["High"])
    levels.pdl = float(prev_day["Low"])
    levels.pdc = float(prev_day["Close"])

    # --- Classic Pivot Points ---
    levels.pp = (levels.pdh + levels.pdl + levels.pdc) / 3
    levels.r1 = 2 * levels.pp - levels.pdl
    levels.r2 = levels.pp + (levels.pdh - levels.pdl)
    levels.s1 = 2 * levels.pp - levels.pdh
    levels.s2 = levels.pp - (levels.pdh - levels.pdl)

    # --- Previous Week High/Low ---
    try:
        weekly = df_daily.resample("W").agg({"High": "max", "Low": "min"})
        weekly = weekly.dropna()
        if len(weekly) >= 2:
            levels.pwh = float(weekly["High"].iloc[-2])
            levels.pwl = float(weekly["Low"].iloc[-2])
    except Exception as exc:
        logger.warning("Weekly levels calculation failed: %s", exc)

    # --- Psychological Levels ---
    step = _psych_step(current_price)
    levels.psych_below = float(math.floor(current_price / step) * step)
    levels.psych_above = float(levels.psych_below + step)
    # Avoid duplicates: if price IS the round number, shift
    if abs(current_price - levels.psych_below) < step * 0.001:
        levels.psych_below = float(levels.psych_below - step)

    # --- Find Nearest Level ---
    all_named = levels.all_levels()
    if all_named and current_price:
        closest_name, closest_val = min(
            all_named, key=lambda nv: abs(nv[1] - current_price)
        )
        levels.nearest_level = closest_val
        levels.nearest_level_name = closest_name
        levels.nearest_level_dist_pct = round(
            ((current_price - closest_val) / current_price) * 100, 2
        )

    return levels


# ---------------------------------------------------------------------------
# Multi-Timeframe Analysis
# ---------------------------------------------------------------------------


def _compute_ema_trend(df: pd.DataFrame, min_bars: int = 50) -> str:
    """Compute trend direction from EMA20/EMA50 on any timeframe.

    Returns "BULLISH", "BEARISH", or "NEUTRAL".
    """
    if df is None or df.empty or len(df) < min_bars:
        return "NEUTRAL"
    try:
        ema20 = ta.ema(df["Close"], length=20)
        ema50 = ta.ema(df["Close"], length=50)
        if ema20 is None or ema50 is None or ema20.empty or ema50.empty:
            return "NEUTRAL"
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        if e20 > e50:
            return "BULLISH"
        elif e20 < e50:
            return "BEARISH"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"


def _analyze_mtf(
    df_weekly: pd.DataFrame,
    daily_trend: str,
    df_hourly: pd.DataFrame,
) -> MTFAnalysis:
    """Compute multi-timeframe trend alignment.

    Args:
        df_weekly: Weekly OHLCV data.
        daily_trend: Already-computed daily EMA trend label.
        df_hourly: 1-hour OHLCV data.

    Returns:
        MTFAnalysis with alignment assessment.
    """
    weekly = _compute_ema_trend(df_weekly)
    hourly = _compute_ema_trend(df_hourly)

    trends = [weekly, daily_trend, hourly]
    bullish = trends.count("BULLISH")
    bearish = trends.count("BEARISH")

    if bullish == 3:
        alignment = "ALIGNED"
        dominant = "BULLISH"
    elif bearish == 3:
        alignment = "ALIGNED"
        dominant = "BEARISH"
    elif bullish >= 2:
        alignment = "PARTIAL"
        dominant = "BULLISH"
    elif bearish >= 2:
        alignment = "PARTIAL"
        dominant = "BEARISH"
    else:
        alignment = "CONFLICTING"
        dominant = "NEUTRAL"

    return MTFAnalysis(
        weekly_trend=weekly,
        daily_trend=daily_trend,
        hourly_trend=hourly,
        alignment=alignment,
        dominant_direction=dominant,
    )


# ---------------------------------------------------------------------------
# Quality Score
# ---------------------------------------------------------------------------


def _detect_candle_pattern(df_daily: pd.DataFrame, direction: str) -> str | None:
    """Detect candle patterns on the last daily candle.

    Delegates to the unified strategy module's detect_candle_pattern().
    Returns a string label: "ENGULFING", "PIN_BAR", "INSIDE_BAR", or None.
    """
    if len(df_daily) < 2:
        return None
    return _strategy_detect_candle(df_daily, len(df_daily) - 1, direction)


def _compute_quality_score(
    signals: list[TechnicalSignal],
    composite_score: str,
    key_levels: KeyLevels | None,
    df_daily: pd.DataFrame,
) -> QualityScore:
    """Compute setup quality score (1-5) based on confluence and market conditions.

    Delegates core logic to strategy.compute_quality_score(), then maps
    into the price_data.QualityScore dataclass for backward compatibility.
    """
    from modules.strategy import (
        IndicatorLabel as _StratLabel,
        KeyLevelsResult as _StratKL,
        compute_quality_score as _strategy_qs,
    )

    # Build strategy-compatible labels
    directional_names = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}
    strat_labels = [
        (s.name, _StratLabel(s.label, s.detail, 1.0))
        for s in signals if s.name in directional_names
    ]

    # ADX value
    adx_sig = next((s for s in signals if s.name == "ADX"), None)
    adx_val = adx_sig.value if (adx_sig and adx_sig.value is not None) else None

    # Map KeyLevels to strategy's KeyLevelsResult
    strat_kl = None
    if key_levels and key_levels.nearest_level_dist_pct is not None:
        strat_kl = _StratKL(
            pdh=key_levels.pdh, pdl=key_levels.pdl, pdc=key_levels.pdc,
            pp=key_levels.pp, r1=key_levels.r1, r2=key_levels.r2,
            s1=key_levels.s1, s2=key_levels.s2,
            nearest_level=key_levels.nearest_level,
            nearest_level_name=key_levels.nearest_level_name,
            nearest_level_dist_pct=key_levels.nearest_level_dist_pct,
        )

    bar_idx = len(df_daily) - 1 if len(df_daily) > 0 else 0
    strat_result = _strategy_qs(
        df_daily, bar_idx, composite_score,
        adx_value=adx_val, labels=strat_labels, key_levels=strat_kl,
    )

    return QualityScore(
        total=strat_result.total,
        confluence=strat_result.confluence,
        strong_trend=strat_result.strong_trend,
        near_key_level=strat_result.near_key_level,
        candle_pattern=strat_result.candle_pattern,
        volume_above_avg=strat_result.volume_above_avg,
    )


# ---------------------------------------------------------------------------
# Technical analysis
# ---------------------------------------------------------------------------


def _analyze_single_asset(symbol: str, display_name: str) -> AssetAnalysis:
    """Download data and compute indicators for a single asset."""
    # Daily data for trend indicators
    df_daily, daily_source = _fetch_daily(symbol)

    # 5-minute data for intraday context
    df_5m, _ = _fetch_intraday(symbol)

    # Weekly and hourly data for multi-timeframe analysis
    df_weekly, _ = _fetch_weekly(symbol)
    df_hourly, _ = _fetch_hourly(symbol)

    current_price = float(df_daily["Close"].iloc[-1])
    prev_close = (
        float(df_daily["Close"].iloc[-2]) if len(df_daily) >= 2 else current_price
    )
    change_pct = ((current_price - prev_close) / prev_close) * 100

    signals: list[TechnicalSignal] = []

    # Determine regime from ADX (compute it early so labeling can use it)
    adx_value_for_regime: float | None = None
    try:
        adx_df = ta.adx(df_daily["High"], df_daily["Low"], df_daily["Close"], length=14)
        if adx_df is not None and not adx_df.empty:
            adx_cols = adx_df.columns.tolist()
            adx_value_for_regime = float(
                adx_df[[c for c in adx_cols if c.startswith("ADX_")][0]].iloc[-1]
            )
    except Exception:
        pass
    regime = classify_regime(adx_value_for_regime)

    # --- RSI(14) — uses unified strategy labeling ---
    try:
        rsi_series = ta.rsi(df_daily["Close"], length=14)
        if rsi_series is not None and not rsi_series.empty:
            rsi_val = float(rsi_series.iloc[-1])
            rsi_lbl = label_rsi(rsi_val, regime)
            signals.append(TechnicalSignal("RSI", rsi_val, rsi_lbl.label, rsi_lbl.detail))
    except Exception as exc:
        logger.warning("RSI failed for %s: %s", symbol, exc)

    # --- MACD(12, 26, 9) — uses unified strategy labeling ---
    try:
        macd_df = ta.macd(df_daily["Close"], fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            macd_hist = float(macd_df.iloc[-1, 1])
            prev_hist = float(macd_df.iloc[-2, 1]) if len(macd_df) >= 2 else None
            macd_lbl = label_macd(macd_hist, prev_hist, regime)
            signals.append(TechnicalSignal("MACD", macd_hist, macd_lbl.label, macd_lbl.detail))
    except Exception as exc:
        logger.warning("MACD failed for %s: %s", symbol, exc)

    # --- Bollinger Bands (20, 2) — uses unified strategy labeling ---
    try:
        bbands = ta.bbands(df_daily["Close"], length=20, std=2)
        if bbands is not None and not bbands.empty:
            bb_cols = bbands.columns.tolist()
            upper = float(bbands[[c for c in bb_cols if c.startswith("BBU_")][0]].iloc[-1])
            middle = float(bbands[[c for c in bb_cols if c.startswith("BBM_")][0]].iloc[-1])
            lower = float(bbands[[c for c in bb_cols if c.startswith("BBL_")][0]].iloc[-1])
            bandwidth = float(bbands[[c for c in bb_cols if c.startswith("BBB_")][0]].iloc[-1])
            bb_lbl = label_bbands(current_price, upper, lower, middle, bandwidth, regime)
            signals.append(TechnicalSignal("BBANDS", bandwidth, bb_lbl.label, bb_lbl.detail))
    except Exception as exc:
        logger.warning("Bollinger Bands failed for %s: %s", symbol, exc)

    # --- Stochastic (14, 3, 3) — uses unified strategy labeling ---
    try:
        stoch = ta.stoch(
            df_daily["High"], df_daily["Low"], df_daily["Close"], k=14, d=3, smooth_k=3
        )
        if stoch is not None and not stoch.empty:
            stoch_cols = stoch.columns.tolist()
            k_col = [c for c in stoch_cols if c.startswith("STOCHk_")][0]
            d_col = [c for c in stoch_cols if c.startswith("STOCHd_")][0]

            k_val = float(stoch[k_col].iloc[-1])
            d_val = float(stoch[d_col].iloc[-1])
            prev_k = float(stoch[k_col].iloc[-2]) if len(stoch) >= 2 else None
            prev_d = float(stoch[d_col].iloc[-2]) if len(stoch) >= 2 else None

            stoch_lbl = label_stochastic(k_val, d_val, prev_k, prev_d, regime)
            signals.append(TechnicalSignal("STOCH", k_val, stoch_lbl.label, stoch_lbl.detail))
    except Exception as exc:
        logger.warning("Stochastic failed for %s: %s", symbol, exc)

    # --- VWAP (using intraday data) ---
    if not df_5m.empty and "Volume" in df_5m.columns and df_5m["Volume"].sum() > 0:
        try:
            vwap_series = ta.vwap(
                df_5m["High"], df_5m["Low"], df_5m["Close"], df_5m["Volume"]
            )
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
            signals.append(
                TechnicalSignal("VWAP", None, "NEUTRAL", "VWAP calculation error")
            )
    else:
        signals.append(
            TechnicalSignal("VWAP", None, "NEUTRAL", "VWAP not available (no volume)")
        )

    # --- ATR(14) ---
    try:
        atr_series = ta.atr(
            df_daily["High"], df_daily["Low"], df_daily["Close"], length=14
        )
        if atr_series is not None and not atr_series.empty:
            atr_val = float(atr_series.iloc[-1])
            atr_pct = (atr_val / current_price) * 100
            if atr_pct > 2.0:
                label, detail = (
                    "NEUTRAL",
                    f"ATR {atr_val:.2f} ({atr_pct:.2f}%) — high volatility",
                )
            else:
                label, detail = (
                    "NEUTRAL",
                    f"ATR {atr_val:.2f} ({atr_pct:.2f}%) — normal volatility",
                )
            signals.append(TechnicalSignal("ATR", atr_val, label, detail))
    except Exception as exc:
        logger.warning("ATR failed for %s: %s", symbol, exc)

    # --- EMA(20) vs EMA(50) — uses unified strategy labeling ---
    try:
        ema20 = ta.ema(df_daily["Close"], length=20)
        ema50 = ta.ema(df_daily["Close"], length=50)
        if (
            ema20 is not None
            and ema50 is not None
            and not ema20.empty
            and not ema50.empty
        ):
            ema20_val = float(ema20.iloc[-1])
            ema50_val = float(ema50.iloc[-1])
            ema_lbl = label_ema_trend(ema20_val, ema50_val, current_price, regime)
            signals.append(TechnicalSignal("EMA_TREND", ema20_val, ema_lbl.label, ema_lbl.detail))
    except Exception as exc:
        logger.warning("EMA failed for %s: %s", symbol, exc)

    # --- ADX(14) — trend strength (non-directional) ---
    try:
        adx_df = ta.adx(df_daily["High"], df_daily["Low"], df_daily["Close"], length=14)
        if adx_df is not None and not adx_df.empty:
            adx_cols = adx_df.columns.tolist()
            adx_val = float(
                adx_df[[c for c in adx_cols if c.startswith("ADX_")][0]].iloc[-1]
            )
            dmp_val = float(
                adx_df[[c for c in adx_cols if c.startswith("DMP_")][0]].iloc[-1]
            )
            dmn_val = float(
                adx_df[[c for c in adx_cols if c.startswith("DMN_")][0]].iloc[-1]
            )

            if adx_val >= 25:
                trend_dir = "bullish" if dmp_val > dmn_val else "bearish"
                detail = f"ADX {adx_val:.1f} — strong {trend_dir} trend (+DI {dmp_val:.1f} / -DI {dmn_val:.1f})"
            else:
                detail = f"ADX {adx_val:.1f} — weak/ranging (+DI {dmp_val:.1f} / -DI {dmn_val:.1f})"
            signals.append(TechnicalSignal("ADX", adx_val, "NEUTRAL", detail))
    except Exception as exc:
        logger.warning("ADX failed for %s: %s", symbol, exc)

    # --- Composite score — uses unified strategy module ---
    # Build IndicatorLabel list from TechnicalSignal objects for strategy.compute_composite
    from modules.strategy import IndicatorLabel as _StratLabel

    directional_names = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}
    composite_labels: list[tuple[str, _StratLabel]] = []
    for s in signals:
        if s.name in directional_names:
            composite_labels.append((s.name, _StratLabel(s.label, s.detail, 1.0)))

    composite, confidence = compute_composite(
        composite_labels,
        regime=regime,
        adx_filter=adx_value_for_regime,
    )

    # --- Multi-Timeframe Analysis ---
    mtf = None
    try:
        ema_signal = next((s for s in signals if s.name == "EMA_TREND"), None)
        daily_trend = ema_signal.label if ema_signal else "NEUTRAL"
        mtf = _analyze_mtf(df_weekly, daily_trend, df_hourly)

        # Apply MTF penalty to composite score
        if mtf.alignment == "CONFLICTING" and composite != "NEUTRAL":
            logger.info(
                "%s: MTF CONFLICTING — forcing composite %s → NEUTRAL",
                symbol,
                composite,
            )
            composite = "NEUTRAL"
            confidence = 50.0
        elif mtf.alignment == "PARTIAL":
            if composite != "NEUTRAL" and composite != mtf.dominant_direction:
                logger.info(
                    "%s: MTF PARTIAL (%s) contradicts composite %s → NEUTRAL",
                    symbol,
                    mtf.dominant_direction,
                    composite,
                )
                composite = "NEUTRAL"
                confidence = 50.0
            elif composite != "NEUTRAL":
                # Partial alignment in same direction: reduce confidence
                confidence = max(confidence - 15, 50.0)
    except Exception as exc:
        logger.warning("MTF analysis failed for %s: %s", symbol, exc)

    # --- Key Levels ---
    try:
        key_levels = _compute_key_levels(df_daily, current_price)
    except Exception as exc:
        logger.warning("Key levels failed for %s: %s", symbol, exc)
        key_levels = KeyLevels()

    # --- Quality Score ---
    try:
        quality = _compute_quality_score(signals, composite, key_levels, df_daily)
    except Exception as exc:
        logger.warning("Quality score failed for %s: %s", symbol, exc)
        quality = QualityScore()

    # Store daily closes for correlation computation
    daily_closes = df_daily["Close"].copy() if not df_daily.empty else None

    # Build OHLC + EMA chart data for the frontend
    ohlc_data = None
    ema20_data = None
    ema50_data = None
    if not df_daily.empty:
        try:
            ohlc_data = []
            for idx, row in df_daily.iterrows():
                day_str = idx.strftime("%Y-%m-%d")
                ohlc_data.append(
                    {
                        "time": day_str,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                    }
                )

            ema20 = ta.ema(df_daily["Close"], length=20)
            ema50 = ta.ema(df_daily["Close"], length=50)

            if ema20 is not None:
                ema20_data = []
                for idx, val in ema20.dropna().items():
                    ema20_data.append(
                        {
                            "time": idx.strftime("%Y-%m-%d"),
                            "value": round(float(val), 2),
                        }
                    )

            if ema50 is not None:
                ema50_data = []
                for idx, val in ema50.dropna().items():
                    ema50_data.append(
                        {
                            "time": idx.strftime("%Y-%m-%d"),
                            "value": round(float(val), 2),
                        }
                    )
        except Exception as exc:
            logger.warning("Chart data build failed for %s: %s", symbol, exc)

    return AssetAnalysis(
        symbol=symbol,
        display_name=display_name,
        price=current_price,
        change_pct=change_pct,
        signals=signals,
        composite_score=composite,
        confidence_pct=round(confidence, 1),
        data_source=daily_source,
        key_levels=key_levels,
        mtf=mtf,
        quality_score=quality,
        daily_closes=daily_closes,
        ohlc_data=ohlc_data,
        ema20_data=ema20_data,
        ema50_data=ema50_data,
    )


# ---------------------------------------------------------------------------
# Correlation analysis
# ---------------------------------------------------------------------------


def compute_correlation_matrix(analyses: list[AssetAnalysis]) -> pd.DataFrame | None:
    """Compute pairwise 30-day daily return correlation matrix.

    Args:
        analyses: List of AssetAnalysis with daily_closes populated.

    Returns:
        Correlation DataFrame indexed by symbol, or None if insufficient data.
    """
    returns: dict[str, pd.Series] = {}
    for a in analyses:
        if a.daily_closes is not None and len(a.daily_closes) >= 30:
            r = a.daily_closes.pct_change().dropna().tail(30)
            if len(r) >= 20:
                returns[a.symbol] = r

    if len(returns) < 2:
        return None

    df = pd.DataFrame(returns)
    return df.corr()


def filter_correlated_assets(
    analyses: list[AssetAnalysis],
    corr_matrix: pd.DataFrame | None,
    threshold: float = 0.7,
) -> list[str]:
    """Identify assets to skip due to high correlation with a better-scored setup.

    Among correlated pairs trading in the same direction, keeps the asset
    with the higher quality score and returns the others as 'skip'.

    Returns:
        List of symbols that should NOT be traded.
    """
    if corr_matrix is None or len(analyses) < 2:
        return []

    skip: set[str] = set()
    by_symbol = {a.symbol: a for a in analyses if a.error is None}

    symbols = list(corr_matrix.index)
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            sym_a, sym_b = symbols[i], symbols[j]
            corr = abs(float(corr_matrix.loc[sym_a, sym_b]))
            if corr < threshold:
                continue

            a = by_symbol.get(sym_a)
            b = by_symbol.get(sym_b)
            if not a or not b:
                continue

            # Only filter if both have same directional bias
            if (
                a.composite_score == b.composite_score
                and a.composite_score != "NEUTRAL"
            ):
                qs_a = a.quality_score.total if a.quality_score else 0
                qs_b = b.quality_score.total if b.quality_score else 0
                if qs_a >= qs_b:
                    skip.add(sym_b)
                else:
                    skip.add(sym_a)

    return list(skip)


# ---------------------------------------------------------------------------
# Intermarket analysis
# ---------------------------------------------------------------------------

# Known intermarket relationships (inverse correlations)
_INTERMARKET_PAIRS: list[tuple[str, str, str]] = [
    # (symbol_a_pattern, symbol_b_pattern, relationship_description)
    # DXY (US Dollar) inverse to Gold
    ("DX", "GC", "DXY/Gold inverse"),
    # Yields inverse to Equities (simplified: TNX/TLT vs SPY/ES/NQ)
    ("TNX", "ES", "Yields/Equities inverse"),
    ("TNX", "NQ", "Yields/Equities inverse"),
    ("TLT", "ES", "Bonds/Equities inverse"),
    ("TLT", "NQ", "Bonds/Equities inverse"),
]


def _match_symbol(analysis_symbol: str, pattern: str) -> bool:
    """Check if an analysis symbol matches an intermarket pattern."""
    return pattern in analysis_symbol.upper()


def compute_intermarket_signals(analyses: list[AssetAnalysis]) -> list[str]:
    """Check for known intermarket divergences across analysed assets.

    Takes a list of AssetAnalysis objects and checks for known inverse
    relationships (e.g. DXY vs Gold, Yields vs Equities). Returns
    informational warning strings when a divergence is detected.

    This is purely informational and does not block signals.

    Args:
        analyses: List of AssetAnalysis objects from analyze_assets().

    Returns:
        List of warning strings describing detected divergences.
    """
    if not analyses or len(analyses) < 2:
        return []

    warnings: list[str] = []
    by_symbol: dict[str, AssetAnalysis] = {
        a.symbol: a for a in analyses if a.error is None and a.composite_score != "NEUTRAL"
    }

    for pattern_a, pattern_b, desc in _INTERMARKET_PAIRS:
        matches_a = [
            (sym, a) for sym, a in by_symbol.items()
            if _match_symbol(sym, pattern_a)
        ]
        matches_b = [
            (sym, b) for sym, b in by_symbol.items()
            if _match_symbol(sym, pattern_b)
        ]

        for sym_a, a in matches_a:
            for sym_b, b in matches_b:
                # Divergence: both in the same direction when they should be inverse
                if a.composite_score == b.composite_score:
                    warnings.append(
                        f"{desc}: {sym_a} {a.composite_score} + "
                        f"{sym_b} {b.composite_score} -> divergence warning"
                    )
                # Also flag if the expected-inverse asset contradicts the signal
                # e.g. DXY strong BULLISH + Gold LONG
                if a.composite_score == "BULLISH" and b.composite_score == "BULLISH":
                    warnings.append(
                        f"{sym_a} strong + {sym_b} LONG -> {desc} divergence warning"
                    )

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return unique


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    results = analyze_assets(config["assets"])
    for r in results:
        print(f"\n{'=' * 60}")
        print(f"{r.display_name} ({r.symbol}) [source: {r.data_source}]")
        if r.error:
            print(f"  ERROR: {r.error}")
            continue
        print(f"  Price: {r.price:.2f} ({r.change_pct:+.2f}%)")
        for s in r.signals:
            print(f"  {s.name}: {s.label} — {s.detail}")
        print(f"  Composite: {r.composite_score} ({r.confidence_pct}%)")
