"""Abstract data provider and OHLCV container."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class OHLCVData:
    """Standardized OHLCV container returned by all providers.

    DataFrame has columns: Open, High, Low, Close, Volume
    with a DatetimeIndex (UTC-aware).
    """

    df: pd.DataFrame
    symbol: str
    interval: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.df is None or self.df.empty

    @property
    def bars(self) -> int:
        return 0 if self.empty else len(self.df)

    def validate(self) -> list[str]:
        """Check data quality. Returns list of warnings (empty = clean)."""
        warnings: list[str] = []
        if self.empty:
            warnings.append("DataFrame is empty")
            return warnings

        required = {"Open", "High", "Low", "Close"}
        missing = required - set(self.df.columns)
        if missing:
            warnings.append(f"Missing columns: {missing}")

        for col in ["Open", "High", "Low", "Close"]:
            if col in self.df.columns:
                nans = self.df[col].isna().sum()
                if nans > 0:
                    warnings.append(f"{col}: {nans} NaN values ({nans/len(self.df)*100:.1f}%)")

        if "Volume" in self.df.columns:
            zero_vol = (self.df["Volume"] == 0).sum()
            if zero_vol > len(self.df) * 0.5:
                warnings.append(
                    f"Volume: {zero_vol}/{len(self.df)} bars have zero volume"
                )

        if len(self.df) > 1:
            gaps = self.df.index.to_series().diff().dropna()
            median_gap = gaps.median()
            large_gaps = gaps[gaps > median_gap * 5]
            if len(large_gaps) > 0:
                warnings.append(f"Data gaps: {len(large_gaps)} gaps > 5x median interval")

        return warnings


class DataProvider(ABC):
    """Abstract base class for OHLCV data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging."""

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        interval: str = "1d",
        bars: int = 200,
        **kwargs: Any,
    ) -> OHLCVData | None:
        """Fetch OHLCV data for a symbol.

        Args:
            symbol: Canonical symbol (e.g. "EURUSD", "NQ", "AAPL").
            interval: Bar interval ("1m", "5m", "15m", "1h", "1d", "1wk").
            bars: Approximate number of bars to fetch.

        Returns:
            OHLCVData or None if data unavailable.
        """

    @abstractmethod
    def supports(self, symbol: str) -> bool:
        """Whether this provider can serve data for the given symbol."""

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard column names and UTC index."""
        col_map = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        if "Volume" not in df.columns:
            df["Volume"] = 0.0

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if not isinstance(df.index, pd.DatetimeIndex):
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"])
                df.set_index("datetime", inplace=True)
            elif "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)

        df.sort_index(inplace=True)
        return df
