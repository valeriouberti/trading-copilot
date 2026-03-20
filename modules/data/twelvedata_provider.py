"""Twelve Data provider.

Good for forex, futures, and stocks. Free tier: 800 API credits/day.
Each time-series call costs 1 credit.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd
import requests

from modules.data.provider import DataProvider, OHLCVData

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com"

# Map canonical symbols → Twelve Data symbols
_TD_SYMBOL_MAP: dict[str, str] = {
    # Forex
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD",
    "USDCHF": "USD/CHF",
    "USDCAD": "USD/CAD",
    # Futures
    "NQ": "NQ",
    "ES": "ES",
    "YM": "YM",
    "RTY": "RTY",
    "GC": "GC",
    "SI": "SI",
    "CL": "CL",
    "NG": "NG",
    # Reference
    "DXY": "DXY",
    "VIX": "VIX",
    "US10Y": "US10Y",
}

# Interval mapping: canonical → Twelve Data format
_INTERVAL_MAP: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
    "1wk": "1week",
}


class TwelveDataProvider(DataProvider):
    """Twelve Data provider — reliable for forex and futures."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("TWELVE_DATA_API_KEY", "")

    @property
    def name(self) -> str:
        return "twelvedata"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def supports(self, symbol: str) -> bool:
        return self.available

    def fetch(
        self,
        symbol: str,
        interval: str = "1d",
        bars: int = 200,
        **kwargs: Any,
    ) -> OHLCVData | None:
        if not self._api_key:
            return None

        td_symbol = _TD_SYMBOL_MAP.get(symbol, symbol)
        td_interval = _INTERVAL_MAP.get(interval, interval)

        params = {
            "symbol": td_symbol,
            "interval": td_interval,
            "outputsize": bars,
            "apikey": self._api_key,
        }

        try:
            resp = requests.get(
                f"{_BASE_URL}/time_series",
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Twelve Data request failed for %s: %s", symbol, exc)
            return None

        if "values" not in data:
            msg = data.get("message", data.get("status", "unknown error"))
            logger.warning("Twelve Data no values for %s: %s", symbol, msg)
            return None

        df = pd.DataFrame(data["values"])
        df = self._normalize_df(df)

        if df.empty:
            return None

        return OHLCVData(
            df=df,
            symbol=symbol,
            interval=interval,
            source=self.name,
            metadata={"td_symbol": td_symbol, "credits_used": 1},
        )
