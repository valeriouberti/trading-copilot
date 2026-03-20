"""Asset universe definitions.

Defines the full trading universe: forex, commodities, indices, and
large-cap stocks, with per-asset metadata for backtesting (spread,
commission, point value).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssetClass(str, Enum):
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX = "index"
    STOCK = "stock"
    REFERENCE = "reference"


@dataclass(frozen=True)
class AssetSpec:
    """Specification for a tradeable asset."""

    symbol: str              # Canonical symbol (e.g. "EURUSD", "NQ", "AAPL")
    display_name: str        # Human-readable name
    asset_class: AssetClass  # Classification
    spread_points: float     # Typical spread in price units (Fineco CFD)
    commission: float        # Per-trade commission in USD
    point_value: float       # USD value per 1.0 price movement per contract
    min_bars_daily: int = 200  # Minimum daily bars for reliable backtest


# ---------------------------------------------------------------------------
# Complete asset universe
# ---------------------------------------------------------------------------

# Forex — 6 major pairs
_FOREX = [
    AssetSpec("EURUSD", "EUR/USD", AssetClass.FOREX, 0.00010, 0.0, 100_000, 250),
    AssetSpec("GBPUSD", "GBP/USD", AssetClass.FOREX, 0.00012, 0.0, 100_000, 250),
    AssetSpec("USDJPY", "USD/JPY", AssetClass.FOREX, 0.015, 0.0, 1_000, 250),
    AssetSpec("AUDUSD", "AUD/USD", AssetClass.FOREX, 0.00012, 0.0, 100_000, 250),
    AssetSpec("USDCHF", "USD/CHF", AssetClass.FOREX, 0.00015, 0.0, 100_000, 250),
    AssetSpec("USDCAD", "USD/CAD", AssetClass.FOREX, 0.00015, 0.0, 100_000, 250),
]

# Commodities — Gold, Silver, Oil, Natural Gas
_COMMODITIES = [
    AssetSpec("GC", "Gold", AssetClass.COMMODITY, 0.30, 0.0, 100, 200),
    AssetSpec("SI", "Silver", AssetClass.COMMODITY, 0.020, 0.0, 5_000, 200),
    AssetSpec("CL", "Crude Oil", AssetClass.COMMODITY, 0.03, 0.0, 1_000, 200),
    AssetSpec("NG", "Natural Gas", AssetClass.COMMODITY, 0.003, 0.0, 10_000, 200),
]

# Indices — US major indices
_INDICES = [
    AssetSpec("NQ", "NASDAQ 100", AssetClass.INDEX, 1.5, 0.0, 20, 200),
    AssetSpec("ES", "S&P 500", AssetClass.INDEX, 0.50, 0.0, 50, 200),
    AssetSpec("YM", "Dow Jones", AssetClass.INDEX, 3.0, 0.0, 5, 200),
    AssetSpec("RTY", "Russell 2000", AssetClass.INDEX, 0.30, 0.0, 50, 200),
]

# Stocks — 10 largest by market cap (as of March 2026)
_STOCKS = [
    AssetSpec("AAPL", "Apple", AssetClass.STOCK, 0.02, 3.95, 1, 250),
    AssetSpec("MSFT", "Microsoft", AssetClass.STOCK, 0.03, 3.95, 1, 250),
    AssetSpec("NVDA", "NVIDIA", AssetClass.STOCK, 0.05, 3.95, 1, 250),
    AssetSpec("GOOG", "Alphabet", AssetClass.STOCK, 0.03, 3.95, 1, 250),
    AssetSpec("AMZN", "Amazon", AssetClass.STOCK, 0.03, 3.95, 1, 250),
    AssetSpec("META", "Meta", AssetClass.STOCK, 0.05, 3.95, 1, 250),
    AssetSpec("BRK-B", "Berkshire Hathaway", AssetClass.STOCK, 0.10, 3.95, 1, 250),
    AssetSpec("LLY", "Eli Lilly", AssetClass.STOCK, 0.10, 3.95, 1, 250),
    AssetSpec("AVGO", "Broadcom", AssetClass.STOCK, 0.10, 3.95, 1, 250),
    AssetSpec("JPM", "JPMorgan Chase", AssetClass.STOCK, 0.03, 3.95, 1, 250),
]

# Reference assets (not traded, used for intermarket analysis)
_REFERENCE = [
    AssetSpec("DXY", "US Dollar Index", AssetClass.REFERENCE, 0, 0, 0),
    AssetSpec("VIX", "CBOE Volatility", AssetClass.REFERENCE, 0, 0, 0),
    AssetSpec("US10Y", "US 10Y Yield", AssetClass.REFERENCE, 0, 0, 0),
]

# Full universe
ASSET_UNIVERSE: dict[str, AssetSpec] = {
    a.symbol: a for a in _FOREX + _COMMODITIES + _INDICES + _STOCKS + _REFERENCE
}


def get_tradeable() -> list[AssetSpec]:
    """Return only tradeable assets (excludes reference)."""
    return [a for a in ASSET_UNIVERSE.values() if a.asset_class != AssetClass.REFERENCE]


def get_by_class(cls: AssetClass) -> list[AssetSpec]:
    """Return assets of a specific class."""
    return [a for a in ASSET_UNIVERSE.values() if a.asset_class == cls]
