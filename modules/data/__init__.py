"""Data provider abstraction layer.

Uses yfinance as the sole provider for UCITS ETFs on Borsa Italiana.
"""

from modules.data.provider import DataProvider, OHLCVData
from modules.data.registry import DataRegistry
from modules.data.universe import ASSET_UNIVERSE, AssetClass, AssetSpec, ETFCategory

__all__ = [
    "DataProvider",
    "OHLCVData",
    "DataRegistry",
    "ASSET_UNIVERSE",
    "AssetClass",
    "AssetSpec",
    "ETFCategory",
]
