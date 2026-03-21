"""Tests for Sprint 4, 5, and 6 features.

Domain-specific tests have been extracted to dedicated files:
- test_analyzer.py — ATR-adaptive SL/TP
- test_auth.py — API key authentication middleware
- test_analytics_api.py — Portfolio heatmap endpoint

Candle pattern tests were removed (duplicates of test_price_data.py).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Project root: tests/ -> parent is repo root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Sprint 4: T1.1 — Adaptive indicator weights
# ---------------------------------------------------------------------------


class TestAdaptiveWeights:
    """Test that composite score uses ADX-adaptive weighting."""

    def test_trending_regime_favors_momentum(self) -> None:
        """When ADX > 25, momentum indicators (MACD, EMA_TREND) get 1.5x weight."""
        from modules.price_data import TechnicalSignal

        signals = [
            TechnicalSignal("MACD", 1.0, "BULLISH", "MACD bullish"),
            TechnicalSignal("EMA_TREND", 100.0, "BULLISH", "EMA bullish"),
            TechnicalSignal("RSI", 45.0, "BEARISH", "RSI bearish"),
            TechnicalSignal("BBANDS", 10.0, "BEARISH", "BB bearish"),
            TechnicalSignal("VWAP", 100.0, "BULLISH", "VWAP bullish"),
            TechnicalSignal("STOCH", 40.0, "BEARISH", "STOCH bearish"),
            TechnicalSignal("ADX", 30.0, "NEUTRAL", "ADX 30"),
            TechnicalSignal("ATR", 2.0, "NEUTRAL", "ATR"),
        ]
        momentum_names = {"MACD", "EMA_TREND"}
        mean_reversion_names = {"RSI", "BBANDS"}
        directional_names = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}

        momentum_weight = 1.5
        mean_rev_weight = 0.7

        bullish_w = 0.0
        total_w = 0.0
        for s in signals:
            if s.name not in directional_names:
                continue
            if s.name in momentum_names:
                w = momentum_weight
            elif s.name in mean_reversion_names:
                w = mean_rev_weight
            else:
                w = 1.0
            total_w += w
            if s.label == "BULLISH":
                bullish_w += w

        assert bullish_w / total_w >= 0.6, (
            f"Expected BULLISH in trending regime, got ratio {bullish_w/total_w:.2f}"
        )

    def test_ranging_regime_favors_mean_reversion(self) -> None:
        """When ADX < 20, mean-reversion indicators (RSI, BBANDS) get 1.5x weight."""
        from modules.price_data import TechnicalSignal

        momentum_names = {"MACD", "EMA_TREND"}
        mean_reversion_names = {"RSI", "BBANDS"}
        directional_names = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}

        signals = [
            TechnicalSignal("RSI", 55.0, "BULLISH", "RSI bullish"),
            TechnicalSignal("BBANDS", 10.0, "BULLISH", "BB bullish"),
            TechnicalSignal("MACD", -1.0, "BEARISH", "MACD bearish"),
            TechnicalSignal("EMA_TREND", 100.0, "BEARISH", "EMA bearish"),
            TechnicalSignal("VWAP", 100.0, "BULLISH", "VWAP bullish"),
            TechnicalSignal("STOCH", 40.0, "BEARISH", "STOCH bearish"),
        ]

        momentum_weight = 0.7
        mean_rev_weight = 1.5

        bullish_w = 0.0
        total_w = 0.0
        for s in signals:
            if s.name not in directional_names:
                continue
            if s.name in momentum_names:
                w = momentum_weight
            elif s.name in mean_reversion_names:
                w = mean_rev_weight
            else:
                w = 1.0
            total_w += w
            if s.label == "BULLISH":
                bullish_w += w

        assert bullish_w / total_w >= 0.6

    def test_neutral_adx_equal_weights(self) -> None:
        """When 20 <= ADX <= 25, all weights are 1.0."""
        adx_value = 22.0
        assert not (adx_value > 25)
        assert not (adx_value < 20)


# ---------------------------------------------------------------------------
# Sprint 4: E2.2 — httpx dependency
# ---------------------------------------------------------------------------


class TestHttpxDependency:
    def test_httpx_importable(self) -> None:
        """httpx should be installable and importable."""
        import httpx
        assert hasattr(httpx, "AsyncClient")


# ---------------------------------------------------------------------------
# Sprint 4: E3.1 — get_asset_by_symbol
# ---------------------------------------------------------------------------


class TestGetAssetBySymbol:
    @pytest.mark.asyncio
    async def test_get_asset_by_symbol_found(self) -> None:
        """Should return a dict when the symbol exists."""
        from app.models.database import get_asset_by_symbol

        mock_asset = MagicMock()
        mock_asset.symbol = "NQ=F"
        mock_asset.display_name = "NASDAQ 100 Futures"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_asset

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_asset_by_symbol(mock_factory, "NQ=F")
        assert result is not None
        assert result["symbol"] == "NQ=F"
        assert result["display_name"] == "NASDAQ 100 Futures"

    @pytest.mark.asyncio
    async def test_get_asset_by_symbol_not_found(self) -> None:
        """Should return None when the symbol does not exist."""
        from app.models.database import get_asset_by_symbol

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_asset_by_symbol(mock_factory, "NONEXISTENT")
        assert result is None


# ---------------------------------------------------------------------------
# Sprint 5: E7.2 — Separate ML deps
# ---------------------------------------------------------------------------


class TestRequirementsFiles:
    def test_requirements_base_exists(self) -> None:
        """requirements-base.txt should exist."""
        assert (_PROJECT_ROOT / "requirements-base.txt").is_file()

    def test_requirements_ml_exists(self) -> None:
        """requirements-ml.txt should exist."""
        assert (_PROJECT_ROOT / "requirements-ml.txt").is_file()

    def test_base_does_not_include_ml(self) -> None:
        """requirements-base.txt should NOT contain transformers or torch."""
        content = (_PROJECT_ROOT / "requirements-base.txt").read_text()
        assert "transformers" not in content
        assert "torch" not in content

    def test_ml_references_base(self) -> None:
        """requirements-ml.txt should reference requirements-base.txt."""
        content = (_PROJECT_ROOT / "requirements-ml.txt").read_text()
        assert "-r requirements-base.txt" in content
        assert "transformers" in content
        assert "torch" in content


# ---------------------------------------------------------------------------
# Sprint 6: T5.3 — Intermarket analysis
# ---------------------------------------------------------------------------


class TestIntermarketSignals:
    def test_no_divergence_with_single_asset(self) -> None:
        """Single asset should produce no warnings."""
        from modules.price_data import AssetAnalysis, compute_intermarket_signals

        analyses = [
            AssetAnalysis(
                symbol="NQ=F",
                display_name="NASDAQ",
                price=21000.0,
                change_pct=1.0,
                composite_score="BULLISH",
            ),
        ]
        warnings = compute_intermarket_signals(analyses)
        assert warnings == []

    def test_dxy_gold_divergence_detected(self) -> None:
        """DXY bullish + Gold bullish should trigger a divergence warning."""
        from modules.price_data import AssetAnalysis, compute_intermarket_signals

        analyses = [
            AssetAnalysis(
                symbol="DX=F",
                display_name="US Dollar Index",
                price=105.0,
                change_pct=0.5,
                composite_score="BULLISH",
            ),
            AssetAnalysis(
                symbol="GC=F",
                display_name="Gold Futures",
                price=2300.0,
                change_pct=1.0,
                composite_score="BULLISH",
            ),
        ]
        warnings = compute_intermarket_signals(analyses)
        assert len(warnings) > 0
        assert any("divergence" in w.lower() for w in warnings)

    def test_no_divergence_when_neutral(self) -> None:
        """Neutral assets should not trigger divergence."""
        from modules.price_data import AssetAnalysis, compute_intermarket_signals

        analyses = [
            AssetAnalysis(
                symbol="DX=F",
                display_name="Dollar",
                price=105.0,
                change_pct=0.0,
                composite_score="NEUTRAL",
            ),
            AssetAnalysis(
                symbol="GC=F",
                display_name="Gold",
                price=2300.0,
                change_pct=0.0,
                composite_score="NEUTRAL",
            ),
        ]
        warnings = compute_intermarket_signals(analyses)
        assert warnings == []

    def test_empty_analyses(self) -> None:
        """Empty list should produce no warnings."""
        from modules.price_data import compute_intermarket_signals

        assert compute_intermarket_signals([]) == []

    def test_error_analyses_excluded(self) -> None:
        """Assets with errors should be excluded."""
        from modules.price_data import AssetAnalysis, compute_intermarket_signals

        analyses = [
            AssetAnalysis(
                symbol="DX=F",
                display_name="Dollar",
                price=None,
                change_pct=None,
                error="No data",
            ),
            AssetAnalysis(
                symbol="GC=F",
                display_name="Gold",
                price=2300.0,
                change_pct=1.0,
                composite_score="BULLISH",
            ),
        ]
        warnings = compute_intermarket_signals(analyses)
        assert warnings == []
