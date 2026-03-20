"""Data provider abstraction layer.

Supports multiple data sources (yfinance, Twelve Data, OANDA) with
automatic fallback and unified OHLCV output.
"""

from modules.data.provider import DataProvider, OHLCVData
from modules.data.registry import DataRegistry
from modules.data.universe import ASSET_UNIVERSE, AssetClass, AssetSpec

__all__ = [
    "DataProvider",
    "OHLCVData",
    "DataRegistry",
    "ASSET_UNIVERSE",
    "AssetClass",
    "AssetSpec",
]
