"""UCITS ETF universe definitions.

Defines the trading universe of UCITS ETFs available on Borsa Italiana
and XETRA, with per-asset metadata for backtesting and position sizing.

Designed for a Fineco broker account with €2.95/trade commission for
EU-listed ETFs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssetClass(str, Enum):
    ETF = "etf"


class ETFCategory(str, Enum):
    """ETF category for grouping and rotation logic."""
    EQUITY_GLOBAL = "equity_global"
    EQUITY_US = "equity_us"
    EQUITY_EU = "equity_eu"
    EQUITY_EM = "equity_em"
    COMMODITY = "commodity"
    BOND = "bond"


@dataclass(frozen=True)
class AssetSpec:
    """Specification for a tradeable UCITS ETF."""

    symbol: str              # Yahoo Finance ticker (e.g. "SWDA.MI")
    display_name: str        # Human-readable name
    asset_class: AssetClass  # Always ETF
    category: ETFCategory    # For grouping and rotation
    commission_eur: float = 2.95   # Fineco flat fee per trade (EUR)
    exchange: str = "MI"           # Exchange suffix (MI = Borsa Italiana, DE = XETRA)
    currency: str = "EUR"          # Trading currency
    min_bars_daily: int = 200      # Minimum daily bars for reliable backtest


# ---------------------------------------------------------------------------
# UCITS ETF Universe — Borsa Italiana (.MI)
# ---------------------------------------------------------------------------

_ETF_UNIVERSE = [
    # Equity — Global
    AssetSpec(
        "SWDA.MI", "iShares Core MSCI World",
        AssetClass.ETF, ETFCategory.EQUITY_GLOBAL,
    ),
    # Equity — US
    AssetSpec(
        "CSSPX.MI", "iShares Core S&P 500",
        AssetClass.ETF, ETFCategory.EQUITY_US,
    ),
    AssetSpec(
        "EQQQ.MI", "Invesco NASDAQ-100",
        AssetClass.ETF, ETFCategory.EQUITY_US,
    ),
    # Equity — Europe
    AssetSpec(
        "MEUD.MI", "Amundi STOXX Europe 600",
        AssetClass.ETF, ETFCategory.EQUITY_EU,
    ),
    # Equity — Emerging Markets
    AssetSpec(
        "IEEM.MI", "iShares MSCI EM",
        AssetClass.ETF, ETFCategory.EQUITY_EM,
    ),
    # Commodity — Gold
    AssetSpec(
        "SGLD.MI", "Invesco Physical Gold",
        AssetClass.ETF, ETFCategory.COMMODITY,
    ),
    # Bonds — EUR Government
    AssetSpec(
        "IEGA.MI", "iShares EUR Gov Bond",
        AssetClass.ETF, ETFCategory.BOND,
    ),
    # Bonds — Global Aggregate
    AssetSpec(
        "AGGH.MI", "iShares Global Agg Bond",
        AssetClass.ETF, ETFCategory.BOND,
    ),
]

# Full universe keyed by symbol
ASSET_UNIVERSE: dict[str, AssetSpec] = {a.symbol: a for a in _ETF_UNIVERSE}


def get_tradeable() -> list[AssetSpec]:
    """Return all tradeable ETFs."""
    return list(ASSET_UNIVERSE.values())


def get_by_category(cat: ETFCategory) -> list[AssetSpec]:
    """Return ETFs of a specific category."""
    return [a for a in ASSET_UNIVERSE.values() if a.category == cat]


def get_defensive() -> list[AssetSpec]:
    """Return defensive ETFs (bonds + gold) for risk-off rotation."""
    return [
        a for a in ASSET_UNIVERSE.values()
        if a.category in (ETFCategory.BOND, ETFCategory.COMMODITY)
    ]


def get_offensive() -> list[AssetSpec]:
    """Return offensive ETFs (equities) for risk-on allocation."""
    return [
        a for a in ASSET_UNIVERSE.values()
        if a.category not in (ETFCategory.BOND, ETFCategory.COMMODITY)
    ]
