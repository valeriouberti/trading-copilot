"""Data provider registry with fallback chain.

Routes data requests to the best available provider. For the ETF system,
yfinance is the sole provider (free, reliable for UCITS ETFs).
"""

from __future__ import annotations

import logging
from typing import Any

from modules.data.provider import DataProvider, OHLCVData
from modules.data.universe import ASSET_UNIVERSE, AssetClass

logger = logging.getLogger(__name__)


# Default provider priority per asset class.
_DEFAULT_PRIORITY: dict[AssetClass, list[str]] = {
    AssetClass.ETF: ["yfinance"],
}


class DataRegistry:
    """Manages multiple data providers with intelligent fallback.

    Usage::

        from modules.data.yfinance_provider import YFinanceProvider

        registry = DataRegistry()
        registry.register(YFinanceProvider())

        data = registry.fetch("SWDA.MI", interval="1d", bars=250)
    """

    def __init__(self) -> None:
        self._providers: dict[str, DataProvider] = {}

    def register(self, provider: DataProvider) -> None:
        """Register a data provider."""
        self._providers[provider.name] = provider
        logger.info("Registered data provider: %s", provider.name)

    def fetch(
        self,
        symbol: str,
        interval: str = "1d",
        bars: int = 200,
        preferred_provider: str | None = None,
        **kwargs: Any,
    ) -> OHLCVData | None:
        """Fetch data using the best available provider.

        Tries providers in priority order based on asset class.
        Returns first successful result, or None if all fail.
        """
        providers = self._get_provider_order(symbol, preferred_provider)

        for provider_name in providers:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue
            if not provider.supports(symbol):
                continue

            try:
                data = provider.fetch(symbol, interval=interval, bars=bars, **kwargs)
                if data is not None and not data.empty:
                    warnings = data.validate()
                    if warnings:
                        logger.warning(
                            "%s data for %s has quality issues: %s",
                            provider_name,
                            symbol,
                            "; ".join(warnings),
                        )
                    logger.debug(
                        "Fetched %d bars for %s from %s",
                        data.bars,
                        symbol,
                        provider_name,
                    )
                    return data
            except Exception as exc:
                logger.warning(
                    "Provider %s failed for %s: %s", provider_name, symbol, exc
                )

        logger.error("All providers failed for %s (interval=%s)", symbol, interval)
        return None

    def fetch_multiple(
        self,
        symbols: list[str],
        interval: str = "1d",
        bars: int = 200,
        **kwargs: Any,
    ) -> dict[str, OHLCVData]:
        """Fetch data for multiple symbols. Returns {symbol: OHLCVData}."""
        results: dict[str, OHLCVData] = {}
        for symbol in symbols:
            data = self.fetch(symbol, interval=interval, bars=bars, **kwargs)
            if data is not None:
                results[symbol] = data
            else:
                logger.warning("No data available for %s, skipping", symbol)
        return results

    def _get_provider_order(
        self, symbol: str, preferred: str | None
    ) -> list[str]:
        """Determine provider priority for a symbol."""
        if preferred and preferred in self._providers:
            others = [
                n for n in self._providers if n != preferred
            ]
            return [preferred] + others

        asset_spec = ASSET_UNIVERSE.get(symbol)
        if asset_spec:
            priority = _DEFAULT_PRIORITY.get(asset_spec.asset_class, [])
            ordered = [p for p in priority if p in self._providers]
            remaining = [p for p in self._providers if p not in ordered]
            return ordered + remaining

        # Unknown symbol: try all providers
        return list(self._providers.keys())


def create_default_registry() -> DataRegistry:
    """Create a registry with yfinance provider."""
    from modules.data.yfinance_provider import YFinanceProvider

    registry = DataRegistry()
    registry.register(YFinanceProvider())

    return registry
