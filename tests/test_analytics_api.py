"""Tests for app.api.analytics_api — portfolio heatmap endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd


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
