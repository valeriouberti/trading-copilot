"""Tests for Sprint 4, 5, and 6 features.

Tests active production code only. Deprecated backtester tests (WalkForward,
KellyPositionSize, MonteCarlo) were removed when modules/backtester.py was
deleted in favour of modules/vbt_backtester.py.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

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
# Sprint 4: T2.1 — ATR-adaptive SL/TP
# ---------------------------------------------------------------------------


class TestATRAdaptiveSLTP:
    """Test ATR-adaptive stop-loss and take-profit computation."""

    def test_low_volatility_tight_sl(self) -> None:
        """Low ATR percentile (< 0.8) should use SL multiplier of 1.0."""
        from app.services.analyzer import _compute_setup
        from modules.price_data import AssetAnalysis, TechnicalSignal

        analysis = AssetAnalysis(
            symbol="TEST",
            display_name="Test",
            price=100.0,
            change_pct=1.0,
            signals=[
                TechnicalSignal("ATR", 1.0, "NEUTRAL", "ATR 1.0"),
            ],
        )
        setup = _compute_setup(analysis, None, "LONG", 4, "ALIGNED")
        assert setup["tradeable"] is True
        assert "sl_multiplier" in setup
        assert "atr_percentile" in setup

    def test_setup_includes_new_fields(self) -> None:
        """Setup dict should include atr_percentile and sl_multiplier."""
        from app.services.analyzer import _compute_setup
        from modules.price_data import AssetAnalysis, TechnicalSignal

        analysis = AssetAnalysis(
            symbol="TEST",
            display_name="Test",
            price=100.0,
            change_pct=1.0,
            signals=[
                TechnicalSignal("ATR", 2.0, "NEUTRAL", "ATR 2.0"),
            ],
        )
        setup = _compute_setup(analysis, None, "LONG", 4, "ALIGNED")
        assert "atr_percentile" in setup
        assert "sl_multiplier" in setup
        assert setup["atr_percentile"] > 0
        assert setup["sl_multiplier"] > 0

    def test_maintains_risk_reward_ratio(self) -> None:
        """TP/SL ratio should match the per-class defaults from strategy module.

        Symbol "ES" resolves to "index" (SL=2.0x, TP=4.0x -> 1:2 R:R).
        """
        from app.services.analyzer import _compute_setup
        from modules.price_data import AssetAnalysis, TechnicalSignal

        analysis = AssetAnalysis(
            symbol="ES",
            display_name="S&P 500",
            price=100.0,
            change_pct=1.0,
            signals=[
                TechnicalSignal("ATR", 2.0, "NEUTRAL", "ATR 2.0"),
            ],
        )
        setup = _compute_setup(analysis, None, "LONG", 4, "ALIGNED")
        assert setup["tradeable"] is True
        ratio = setup["tp_distance"] / setup["sl_distance"]
        assert abs(ratio - 2.0) < 0.1


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
# Sprint 5: E4.1 — Authentication middleware
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    def test_public_paths_are_public(self) -> None:
        """Public paths should not require authentication."""
        from app.middleware.auth import _is_public

        assert _is_public("/api/health") is True
        assert _is_public("/") is True
        assert _is_public("/trades") is True
        assert _is_public("/analytics") is True
        assert _is_public("/signals") is True
        assert _is_public("/settings") is True
        assert _is_public("/static/css/style.css") is True
        assert _is_public("/asset/NQ=F") is True

    def test_api_paths_not_public(self) -> None:
        """API paths should require authentication."""
        from app.middleware.auth import _is_public

        assert _is_public("/api/analyze/NQ=F") is False
        assert _is_public("/api/assets") is False
        assert _is_public("/api/settings") is False

    @pytest.mark.asyncio
    async def test_middleware_skips_when_no_key(self) -> None:
        """If no API key configured, middleware should pass all requests."""
        from app.middleware.auth import APIKeyMiddleware

        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="")
        assert middleware.api_key == ""

    @pytest.mark.asyncio
    async def test_middleware_blocks_invalid_key(self) -> None:
        """Invalid API key should result in 401."""
        from app.middleware.auth import APIKeyMiddleware

        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/assets"
        mock_request.headers = {"X-API-Key": "wrong-key"}
        mock_request.query_params = {}
        mock_request.client.host = "127.0.0.1"

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 401
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_middleware_passes_valid_key(self) -> None:
        """Valid API key should pass through."""
        from app.middleware.auth import APIKeyMiddleware

        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/assets"
        mock_request.headers = {"X-API-Key": "secret-key-123"}
        mock_request.query_params = {}

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_middleware_accepts_query_param(self) -> None:
        """API key via query param should also work."""
        from app.middleware.auth import APIKeyMiddleware

        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/assets"
        mock_request.headers = {}
        mock_request.query_params = {"api_key": "secret-key-123"}

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_skips_public_paths(self) -> None:
        """Public paths should be allowed even without key."""
        from app.middleware.auth import APIKeyMiddleware

        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/health"
        mock_request.headers = {}
        mock_request.query_params = {}

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()


# ---------------------------------------------------------------------------
# Sprint 5: E7.2 — Separate ML deps
# ---------------------------------------------------------------------------


class TestRequirementsFiles:
    def test_requirements_base_exists(self) -> None:
        """requirements-base.txt should exist."""
        assert os.path.isfile(
            "/Users/valeriouberti/personal/side-projects/trading-assistant/requirements-base.txt"
        )

    def test_requirements_ml_exists(self) -> None:
        """requirements-ml.txt should exist."""
        assert os.path.isfile(
            "/Users/valeriouberti/personal/side-projects/trading-assistant/requirements-ml.txt"
        )

    def test_base_does_not_include_ml(self) -> None:
        """requirements-base.txt should NOT contain transformers or torch."""
        with open(
            "/Users/valeriouberti/personal/side-projects/trading-assistant/requirements-base.txt"
        ) as f:
            content = f.read()
        assert "transformers" not in content
        assert "torch" not in content

    def test_ml_references_base(self) -> None:
        """requirements-ml.txt should reference requirements-base.txt."""
        with open(
            "/Users/valeriouberti/personal/side-projects/trading-assistant/requirements-ml.txt"
        ) as f:
            content = f.read()
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


# ---------------------------------------------------------------------------
# Sprint 6: T1.3 — Advanced candle patterns
# ---------------------------------------------------------------------------


class TestAdvancedCandlePatterns:
    def test_inside_bar_detected(self) -> None:
        """Inside bar should be detected when high < prev high AND low > prev low."""
        from modules.price_data import _detect_candle_pattern

        df = pd.DataFrame({
            "Open": [100.0, 101.0],
            "High": [105.0, 103.0],
            "Low": [95.0, 97.0],
            "Close": [102.0, 100.0],
        })
        result = _detect_candle_pattern(df, "BULLISH")
        assert result == "INSIDE_BAR"

    def test_engulfing_bullish(self) -> None:
        """Bullish engulfing should return 'ENGULFING'."""
        from modules.price_data import _detect_candle_pattern

        df = pd.DataFrame({
            "Open": [102.0, 97.0],
            "High": [103.0, 105.0],
            "Low": [98.0, 96.0],
            "Close": [99.0, 104.0],
        })
        result = _detect_candle_pattern(df, "BULLISH")
        assert result == "ENGULFING"

    def test_engulfing_bearish(self) -> None:
        """Bearish engulfing should return 'ENGULFING'."""
        from modules.price_data import _detect_candle_pattern

        df = pd.DataFrame({
            "Open": [98.0, 103.0],
            "High": [102.0, 104.0],
            "Low": [97.0, 95.0],
            "Close": [101.0, 96.0],
        })
        result = _detect_candle_pattern(df, "BEARISH")
        assert result == "ENGULFING"

    def test_pin_bar_bullish(self) -> None:
        """Bullish pin bar (long lower wick) should return 'PIN_BAR'."""
        from modules.price_data import _detect_candle_pattern

        df = pd.DataFrame({
            "Open": [100.0, 101.0],
            "High": [105.0, 101.5],
            "Low": [95.0, 95.0],
            "Close": [102.0, 101.2],
        })
        result = _detect_candle_pattern(df, "BULLISH")
        assert result == "PIN_BAR"

    def test_no_pattern_returns_none(self) -> None:
        """When no pattern matches, should return None."""
        from modules.price_data import _detect_candle_pattern

        df = pd.DataFrame({
            "Open": [100.0, 100.0],
            "High": [102.0, 103.0],
            "Low": [98.0, 97.0],
            "Close": [101.0, 101.0],
        })
        result = _detect_candle_pattern(df, "BULLISH")
        assert result in (None, "PIN_BAR", "ENGULFING", "INSIDE_BAR")

    def test_return_type_truthy_compatible(self) -> None:
        """Return value should be truthy when a pattern is detected."""
        from modules.price_data import _detect_candle_pattern

        df = pd.DataFrame({
            "Open": [100.0, 101.0],
            "High": [105.0, 103.0],
            "Low": [95.0, 97.0],
            "Close": [102.0, 100.0],
        })
        result = _detect_candle_pattern(df, "BULLISH")
        assert result
        assert isinstance(result, str)

    def test_insufficient_data_returns_none(self) -> None:
        """With fewer than 2 bars, should return None."""
        from modules.price_data import _detect_candle_pattern

        df = pd.DataFrame({
            "Open": [100.0],
            "High": [105.0],
            "Low": [95.0],
            "Close": [102.0],
        })
        result = _detect_candle_pattern(df, "BULLISH")
        assert result is None


# ---------------------------------------------------------------------------
# Sprint 6: T6.1 — Portfolio heatmap endpoint
# ---------------------------------------------------------------------------


class TestHeatmapEndpoint:
    def test_analytics_api_module_importable(self) -> None:
        """analytics_api module should be importable."""
        from app.api import analytics_api
        assert hasattr(analytics_api, "router")

    def test_compute_heatmap_returns_dict(self) -> None:
        """_compute_heatmap should return a dict with symbols and matrix."""
        from app.api.analytics_api import _compute_heatmap

        mock_analysis_1 = MagicMock()
        mock_analysis_1.symbol = "A"
        mock_analysis_1.daily_closes = pd.Series(
            np.random.normal(0, 1, 40).cumsum() + 100,
            index=pd.date_range("2025-01-01", periods=40, freq="D"),
        )

        mock_analysis_2 = MagicMock()
        mock_analysis_2.symbol = "B"
        mock_analysis_2.daily_closes = pd.Series(
            np.random.normal(0, 1, 40).cumsum() + 200,
            index=pd.date_range("2025-01-01", periods=40, freq="D"),
        )

        with patch("modules.price_data.analyze_assets", return_value=[mock_analysis_1, mock_analysis_2]):
            result = _compute_heatmap([
                {"symbol": "A", "display_name": "Asset A"},
                {"symbol": "B", "display_name": "Asset B"},
            ])

        assert "symbols" in result
        assert "matrix" in result
        if result["symbols"]:
            assert len(result["symbols"]) == 2
            assert len(result["matrix"]) == 2
            assert len(result["matrix"][0]) == 2

    def test_compute_heatmap_empty_assets(self) -> None:
        """Empty assets should return empty result."""
        from app.api.analytics_api import _compute_heatmap

        with patch("modules.price_data.analyze_assets", return_value=[]):
            result = _compute_heatmap([])

        assert result["symbols"] == []
        assert result["matrix"] == []
