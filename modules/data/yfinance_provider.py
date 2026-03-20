"""yfinance data provider.

Good for US stocks and indices. Unreliable for forex and some futures.
"""

from __future__ import annotations

import logging
from typing import Any

import yfinance as yf

from modules.data.provider import DataProvider, OHLCVData

logger = logging.getLogger(__name__)

# Map canonical symbols → yfinance symbols
_YF_SYMBOL_MAP: dict[str, str] = {
    # Forex
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    # Futures
    "NQ": "NQ=F",
    "ES": "ES=F",
    "YM": "YM=F",
    "RTY": "RTY=F",
    "GC": "GC=F",
    "SI": "SI=F",
    "CL": "CL=F",
    "NG": "NG=F",
    # Indices (reference)
    "DXY": "DX-Y.NYB",
    "VIX": "^VIX",
    "US10Y": "^TNX",
}

# yfinance period string from approximate bar count + interval
_PERIOD_MAP: dict[str, dict[int, str]] = {
    "1d": {60: "3mo", 120: "6mo", 250: "1y", 500: "2y"},
    "1h": {50: "30d", 100: "60d", 200: "2y"},
    "5m": {100: "5d", 200: "30d"},
    "1wk": {52: "1y", 104: "2y", 260: "5y"},
}


def _bars_to_period(interval: str, bars: int) -> str:
    """Convert (interval, bars) to yfinance period string."""
    mapping = _PERIOD_MAP.get(interval, {})
    for threshold, period in sorted(mapping.items()):
        if bars <= threshold:
            return period
    # Default: pick the largest available
    if mapping:
        return list(sorted(mapping.values(), key=lambda x: x))[-1]
    return "1y"


class YFinanceProvider(DataProvider):
    """yfinance data provider — free, best for US stocks/indices."""

    @property
    def name(self) -> str:
        return "yfinance"

    def supports(self, symbol: str) -> bool:
        # yfinance supports almost anything but quality varies
        return True

    def fetch(
        self,
        symbol: str,
        interval: str = "1d",
        bars: int = 200,
        **kwargs: Any,
    ) -> OHLCVData | None:
        yf_symbol = _YF_SYMBOL_MAP.get(symbol, symbol)
        period = _bars_to_period(interval, bars)

        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period=period, interval=interval, timeout=20)
        except Exception as exc:
            logger.warning("yfinance fetch failed for %s: %s", symbol, exc)
            return None

        if df is None or df.empty:
            logger.warning("yfinance returned empty data for %s", symbol)
            return None

        df = self._normalize_df(df)

        return OHLCVData(
            df=df,
            symbol=symbol,
            interval=interval,
            source=self.name,
            metadata={"yf_symbol": yf_symbol, "period": period},
        )
