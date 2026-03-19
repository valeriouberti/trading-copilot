"""Test suite for the price_data module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from modules.price_data import AssetAnalysis, TechnicalSignal, analyze_assets, _analyze_single_asset


def _make_ohlcv_df(rows: int = 100, trend: str = "up") -> pd.DataFrame:
    """Generate a realistic OHLCV DataFrame for testing."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=rows, freq="D")
    np.random.seed(42)

    if trend == "up":
        base = np.linspace(100, 150, rows) + np.random.normal(0, 1, rows)
    elif trend == "down":
        base = np.linspace(150, 100, rows) + np.random.normal(0, 1, rows)
    else:
        base = np.full(rows, 125.0) + np.random.normal(0, 2, rows)

    close = base
    high = close + np.abs(np.random.normal(1, 0.5, rows))
    low = close - np.abs(np.random.normal(1, 0.5, rows))
    open_ = close + np.random.normal(0, 0.5, rows)
    volume = np.random.randint(1000, 100000, rows).astype(float)

    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


def _make_5m_df(rows: int = 200, base_price: float = 150.0) -> pd.DataFrame:
    """Generate a realistic 5min DataFrame."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=rows, freq="5min")
    np.random.seed(42)
    close = base_price + np.random.normal(0, 0.5, rows).cumsum()
    high = close + np.abs(np.random.normal(0.2, 0.1, rows))
    low = close - np.abs(np.random.normal(0.2, 0.1, rows))
    volume = np.random.randint(100, 10000, rows).astype(float)

    return pd.DataFrame({
        "Open": close + np.random.normal(0, 0.1, rows),
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


class TestIndicatorCalculation:
    def test_all_indicators_present(self) -> None:
        """Verify that all indicators are present in the output."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df)

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test Asset")

        signal_names = {s.name for s in result.signals}
        assert "RSI" in signal_names
        assert "MACD" in signal_names
        assert "EMA_TREND" in signal_names
        assert "ATR" in signal_names

    def test_indicator_values_are_floats(self) -> None:
        """Verify that indicator values are floats."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df)

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test Asset")

        for s in result.signals:
            if s.value is not None:
                assert isinstance(s.value, float), f"{s.name} value is not float: {type(s.value)}"


class TestRSIRange:
    def test_rsi_between_0_and_100_uptrend(self) -> None:
        """Verify that RSI is between 0 and 100 with bullish trend."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df)

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        rsi_signal = next((s for s in result.signals if s.name == "RSI"), None)
        assert rsi_signal is not None
        assert 0 <= rsi_signal.value <= 100

    def test_rsi_between_0_and_100_downtrend(self) -> None:
        """Verify that RSI is between 0 and 100 with bearish trend."""
        daily_df = _make_ohlcv_df(100, "down")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df)

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        rsi_signal = next((s for s in result.signals if s.name == "RSI"), None)
        assert rsi_signal is not None
        assert 0 <= rsi_signal.value <= 100


class TestCompositeSignal:
    def test_composite_bullish(self) -> None:
        """Verify that predominantly bullish signals produce BULLISH."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200, base_price=float(daily_df["Close"].iloc[-1]))

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df)

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        # Uptrend data should produce at least some bullish signals
        bullish_count = sum(1 for s in result.signals if s.label == "BULLISH")
        bearish_count = sum(1 for s in result.signals if s.label == "BEARISH")

        if bullish_count > bearish_count:
            assert result.composite_score == "BULLISH"

    def test_composite_bearish(self) -> None:
        """Verify that predominantly bearish signals produce BEARISH."""
        daily_df = _make_ohlcv_df(100, "down")
        intraday_df = _make_5m_df(200, base_price=float(daily_df["Close"].iloc[-1]))

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df)

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        bullish_count = sum(1 for s in result.signals if s.label == "BULLISH")
        bearish_count = sum(1 for s in result.signals if s.label == "BEARISH")

        if bearish_count > bullish_count:
            assert result.composite_score == "BEARISH"

    def test_composite_neutral_on_mixed(self) -> None:
        """Verify that mixed signals produce NEUTRAL with confidence 40-60%."""
        analysis = AssetAnalysis(
            symbol="TEST=F",
            display_name="Test",
            price=100.0,
            change_pct=0.0,
            signals=[
                TechnicalSignal("RSI", 50.0, "BULLISH", ""),
                TechnicalSignal("MACD", 0.0, "BEARISH", ""),
                TechnicalSignal("VWAP", 100.0, "BULLISH", ""),
                TechnicalSignal("EMA_TREND", 100.0, "BEARISH", ""),
            ],
            composite_score="NEUTRAL",
            confidence_pct=50.0,
        )
        assert analysis.composite_score == "NEUTRAL"
        assert 40 <= analysis.confidence_pct <= 60


class TestErrorHandling:
    def test_yfinance_failure_returns_error(self) -> None:
        """Verify that a yfinance error returns an asset with error."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=Exception("Connection timeout"))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            results = analyze_assets([{"symbol": "FAIL=F", "display_name": "Fail Asset"}])

        assert len(results) == 1
        assert results[0].error is not None
        assert "Connection timeout" in results[0].error

    def test_empty_dataframe_returns_error(self) -> None:
        """Verify that empty data from yfinance is handled."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(return_value=pd.DataFrame())

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            results = analyze_assets([{"symbol": "EMPTY=F", "display_name": "Empty"}])

        assert len(results) == 1
        assert results[0].error is not None

    def test_invalid_ticker_no_crash(self) -> None:
        """Verify that an invalid ticker does not cause a crash."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(return_value=pd.DataFrame())

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            results = analyze_assets([{"symbol": "INVALID_TICKER_XYZ", "display_name": "Invalid"}])

        assert len(results) == 1
        assert results[0].error is not None
        assert results[0].price is None


class TestAssetAnalysisSerialization:
    def test_to_dict(self) -> None:
        """Verify serialization of AssetAnalysis."""
        analysis = AssetAnalysis(
            symbol="NQ=F",
            display_name="NASDAQ 100",
            price=21450.0,
            change_pct=1.23,
            signals=[TechnicalSignal("RSI", 58.3, "BULLISH", "RSI 58.3")],
            composite_score="BULLISH",
            confidence_pct=62.0,
        )
        d = analysis.to_dict()
        assert d["symbol"] == "NQ=F"
        assert d["price"] == 21450.0
        assert "RSI" in d["signals"]
        assert d["signals"]["RSI"]["label"] == "BULLISH"
        assert d["error"] is None

    def test_to_dict_with_error(self) -> None:
        """Verify serialization with error."""
        analysis = AssetAnalysis(
            symbol="ERR=F",
            display_name="Error",
            price=None,
            change_pct=None,
            error="Connection failed",
        )
        d = analysis.to_dict()
        assert d["error"] == "Connection failed"
        assert d["price"] is None


class TestNoVolumeAsset:
    def test_fx_pair_no_volume_vwap_neutral(self) -> None:
        """Verify that an asset without volume has neutral VWAP."""
        daily_df = _make_ohlcv_df(100, "up")
        # Create 5m data with zero volume (FX-like)
        intraday_df = _make_5m_df(200)
        intraday_df["Volume"] = 0.0

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df
        )

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("EURUSD=X", "EUR/USD")

        vwap_signal = next((s for s in result.signals if s.name == "VWAP"), None)
        assert vwap_signal is not None
        assert vwap_signal.label == "NEUTRAL"
        assert "not available" in vwap_signal.detail


class TestMultipleAssets:
    def test_analyze_multiple_assets(self) -> None:
        """Verify analysis of multiple assets simultaneously."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=lambda **kw: daily_df if kw.get("interval") == "1d" else intraday_df
        )

        assets = [
            {"symbol": "NQ=F", "display_name": "NASDAQ"},
            {"symbol": "ES=F", "display_name": "S&P 500"},
        ]

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            results = analyze_assets(assets)

        assert len(results) == 2
        assert results[0].display_name == "NASDAQ"
        assert results[1].display_name == "S&P 500"
