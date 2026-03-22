"""UCITS ETF universe definitions.

Defines the trading universe of UCITS ETFs available on Borsa Italiana
and XETRA, with per-asset metadata for backtesting and position sizing.

Supports multiple brokers:
- Fineco: €2.95/trade, whole shares only
- Revolut: €0/trade, fractional shares (0.01 precision)
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


class Broker(str, Enum):
    """Supported brokers with different cost/feature profiles."""
    FINECO = "fineco"
    REVOLUT = "revolut"


@dataclass(frozen=True)
class BrokerProfile:
    """Broker-specific trading parameters."""
    name: str
    commission_eur: float       # Per-trade commission in EUR
    fractional_shares: bool     # Whether fractional shares are supported
    min_fraction: float = 1.0   # Minimum share increment (1.0 = whole, 0.01 = fractional)

    def compute_shares(self, position_size_eur: float, price: float) -> float:
        """Compute number of shares for a given position size and price.

        Returns fractional shares for Revolut, floor'd whole shares for Fineco.
        """
        import math
        raw = position_size_eur / price
        if self.fractional_shares:
            # Round down to min_fraction precision
            factor = 1.0 / self.min_fraction
            return math.floor(raw * factor) / factor
        return float(math.floor(raw))


# Broker profiles
BROKER_PROFILES: dict[Broker, BrokerProfile] = {
    Broker.FINECO: BrokerProfile(
        name="Fineco",
        commission_eur=2.95,
        fractional_shares=False,
        min_fraction=1.0,
    ),
    Broker.REVOLUT: BrokerProfile(
        name="Revolut",
        commission_eur=0.0,
        fractional_shares=True,
        min_fraction=0.01,
    ),
}


@dataclass(frozen=True)
class AssetSpec:
    """Specification for a tradeable UCITS ETF."""

    symbol: str              # Yahoo Finance ticker (e.g. "SWDA.MI")
    display_name: str        # Human-readable name
    asset_class: AssetClass  # Always ETF
    category: ETFCategory    # For grouping and rotation
    commission_eur: float = 2.95   # Default (Fineco); overridden by broker profile
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
    # Commodity — Gold
    AssetSpec(
        "SGLD.MI", "Invesco Physical Gold",
        AssetClass.ETF, ETFCategory.COMMODITY,
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
    """Return defensive ETFs (gold) for risk-off rotation."""
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
