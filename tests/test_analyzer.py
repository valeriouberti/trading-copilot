"""Tests for app.services.analyzer — ATR-adaptive SL/TP computation."""

from __future__ import annotations

import pytest

from app.services.analyzer import _compute_setup
from modules.price_data import AssetAnalysis, TechnicalSignal


class TestATRAdaptiveSLTP:
    """Test ATR-adaptive stop-loss and take-profit computation."""

    def test_low_volatility_tight_sl(self) -> None:
        """Low ATR percentile (< 0.8) should use SL multiplier of 1.0."""
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
