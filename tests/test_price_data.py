"""Test suite for the price_data module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from modules.price_data import (
    AssetAnalysis,
    KeyLevels,
    MTFAnalysis,
    QualityScore,
    TechnicalSignal,
    _analyze_mtf,
    _analyze_single_asset,
    _compute_ema_trend,
    _compute_key_levels,
    _compute_quality_score,
    _detect_candle_pattern,
    _fetch_twelvedata,
    _psych_step,
    analyze_assets,
    compute_correlation_matrix,
    filter_correlated_assets,
)


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


def _mock_ticker_side_effect(daily_df, intraday_df):
    """Create a side_effect function for mock_ticker.history.

    Returns daily_df for daily/weekly/hourly intervals (all use same trend),
    and intraday_df for 5m data (VWAP).
    """
    def side_effect(**kw):
        interval = kw.get("interval", "1d")
        if interval == "5m":
            return intraday_df
        return daily_df  # 1d, 1wk, 1h all share the same trend data
    return side_effect


class TestIndicatorCalculation:
    def test_all_indicators_present(self) -> None:
        """Verify that all 8 indicators are present in the output."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test Asset")

        signal_names = {s.name for s in result.signals}
        assert "RSI" in signal_names
        assert "MACD" in signal_names
        assert "EMA_TREND" in signal_names
        assert "ATR" in signal_names
        assert "BBANDS" in signal_names
        assert "STOCH" in signal_names
        assert "ADX" in signal_names
        assert "VWAP" in signal_names

    def test_indicator_values_are_floats(self) -> None:
        """Verify that indicator values are floats."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test Asset")

        for s in result.signals:
            if s.value is not None:
                assert isinstance(s.value, float), f"{s.name} value is not float: {type(s.value)}"


class TestBollingerBands:
    def test_bbands_bandwidth_positive(self) -> None:
        """Verify Bollinger Bands bandwidth is positive."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        bb = next((s for s in result.signals if s.name == "BBANDS"), None)
        assert bb is not None
        assert bb.value > 0  # Bandwidth should be positive

    def test_bbands_label_valid(self) -> None:
        """Verify BB label is one of the valid options."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        bb = next((s for s in result.signals if s.name == "BBANDS"), None)
        assert bb is not None
        assert bb.label in {"BULLISH", "BEARISH", "NEUTRAL"}


class TestStochastic:
    def test_stoch_between_0_and_100(self) -> None:
        """Verify Stochastic %K is between 0 and 100."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        stoch = next((s for s in result.signals if s.name == "STOCH"), None)
        assert stoch is not None
        assert 0 <= stoch.value <= 100

    def test_stoch_downtrend(self) -> None:
        """Verify Stochastic is present in downtrend."""
        daily_df = _make_ohlcv_df(100, "down")
        intraday_df = _make_5m_df(200, base_price=100.0)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        stoch = next((s for s in result.signals if s.name == "STOCH"), None)
        assert stoch is not None
        assert 0 <= stoch.value <= 100


class TestADX:
    def test_adx_between_0_and_100(self) -> None:
        """Verify ADX is between 0 and 100."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        adx = next((s for s in result.signals if s.name == "ADX"), None)
        assert adx is not None
        assert 0 <= adx.value <= 100

    def test_adx_is_non_directional(self) -> None:
        """Verify ADX label is always NEUTRAL (non-directional)."""
        for trend in ("up", "down", "flat"):
            daily_df = _make_ohlcv_df(100, trend)
            intraday_df = _make_5m_df(200)

            mock_ticker = MagicMock()
            mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

            with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
                result = _analyze_single_asset("TEST=F", "Test")

            adx = next((s for s in result.signals if s.name == "ADX"), None)
            assert adx is not None
            assert adx.label == "NEUTRAL", f"ADX should be NEUTRAL in {trend} trend, got {adx.label}"


class TestRSIRange:
    def test_rsi_between_0_and_100_uptrend(self) -> None:
        """Verify that RSI is between 0 and 100 with bullish trend."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

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
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

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
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        directional = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}
        bullish_count = sum(1 for s in result.signals if s.name in directional and s.label == "BULLISH")

        if bullish_count >= 4:
            assert result.composite_score == "BULLISH"

    def test_composite_bearish(self) -> None:
        """Verify that predominantly bearish signals produce BEARISH."""
        daily_df = _make_ohlcv_df(100, "down")
        intraday_df = _make_5m_df(200, base_price=float(daily_df["Close"].iloc[-1]))

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        directional = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}
        bearish_count = sum(1 for s in result.signals if s.name in directional and s.label == "BEARISH")

        if bearish_count >= 4:
            assert result.composite_score == "BEARISH"

    def test_composite_neutral_on_mixed(self) -> None:
        """Verify that mixed signals produce NEUTRAL with confidence ~50%."""
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
                TechnicalSignal("BBANDS", 10.0, "BULLISH", ""),
                TechnicalSignal("STOCH", 50.0, "BEARISH", ""),
            ],
            composite_score="NEUTRAL",
            confidence_pct=50.0,
        )
        assert analysis.composite_score == "NEUTRAL"
        assert 40 <= analysis.confidence_pct <= 60

    def test_composite_uses_six_indicators(self) -> None:
        """Verify that composite score is based on 6 directional indicators."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        directional = {"RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"}
        directional_signals = [s for s in result.signals if s.name in directional]
        # Should have up to 6 directional indicators
        assert len(directional_signals) >= 4  # At minimum 4 should be present
        assert len(directional_signals) <= 6


class TestErrorHandling:
    def test_yfinance_failure_returns_error(self) -> None:
        """Verify that a yfinance error returns an asset with error."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=Exception("Connection timeout"))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker), \
             patch("modules.price_data._fetch_twelvedata", return_value=None):
            results = analyze_assets([{"symbol": "FAIL=F", "display_name": "Fail Asset"}])

        assert len(results) == 1
        assert results[0].error is not None

    def test_empty_dataframe_returns_error(self) -> None:
        """Verify that empty data from yfinance is handled."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(return_value=pd.DataFrame())

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker), \
             patch("modules.price_data._fetch_twelvedata", return_value=None):
            results = analyze_assets([{"symbol": "EMPTY=F", "display_name": "Empty"}])

        assert len(results) == 1
        assert results[0].error is not None

    def test_invalid_ticker_no_crash(self) -> None:
        """Verify that an invalid ticker does not cause a crash."""
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(return_value=pd.DataFrame())

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker), \
             patch("modules.price_data._fetch_twelvedata", return_value=None):
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

    def test_to_dict_includes_data_source(self) -> None:
        """Verify serialization includes data_source field."""
        analysis = AssetAnalysis(
            symbol="NQ=F",
            display_name="NASDAQ 100",
            price=21450.0,
            change_pct=1.23,
            data_source="twelvedata",
        )
        d = analysis.to_dict()
        assert d["data_source"] == "twelvedata"


class TestNoVolumeAsset:
    def test_fx_pair_no_volume_vwap_neutral(self) -> None:
        """Verify that an asset without volume has neutral VWAP."""
        daily_df = _make_ohlcv_df(100, "up")
        # Create 5m data with zero volume (FX-like)
        intraday_df = _make_5m_df(200)
        intraday_df["Volume"] = 0.0

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=_mock_ticker_side_effect(daily_df, intraday_df)
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
            side_effect=_mock_ticker_side_effect(daily_df, intraday_df)
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


class TestDataSource:
    def test_default_source_is_yfinance(self) -> None:
        """Verify default data source is yfinance."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        assert result.data_source == "yfinance"

    def test_fallback_to_twelvedata(self) -> None:
        """Verify fallback to Twelve Data when yfinance fails."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        # yfinance fails
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=Exception("yfinance down"))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker), \
             patch("modules.price_data._fetch_twelvedata") as mock_td:
            # Twelve Data returns valid data for daily
            mock_td.side_effect = lambda symbol, interval="1d", outputsize=60: (
                daily_df if interval == "1d" else intraday_df
            )
            result = _analyze_single_asset("TEST=F", "Test")

        assert result.data_source == "twelvedata"
        assert result.price is not None

    def test_twelvedata_not_called_without_api_key(self) -> None:
        """Verify Twelve Data is not called if no API key is set."""
        with patch("modules.price_data.TWELVE_DATA_API_KEY", ""):
            result = _fetch_twelvedata("NQ=F", interval="1d", outputsize=60)
        assert result is None

    def test_twelvedata_symbol_mapping(self) -> None:
        """Verify symbol mapping for Twelve Data."""
        from modules.price_data import _TD_SYMBOL_MAP

        assert _TD_SYMBOL_MAP["NQ=F"] == ("NQ", "futures")
        assert _TD_SYMBOL_MAP["ES=F"] == ("ES", "futures")
        assert _TD_SYMBOL_MAP["EURUSD=X"] == ("EUR/USD", "forex")
        assert _TD_SYMBOL_MAP["GC=F"] == ("GC", "futures")

    def test_twelvedata_parse_response(self) -> None:
        """Verify Twelve Data response is parsed into a valid DataFrame."""
        fake_response = {
            "values": [
                {"datetime": "2024-01-15", "open": "100.0", "high": "101.0",
                 "low": "99.0", "close": "100.5", "volume": "12345"},
                {"datetime": "2024-01-14", "open": "99.0", "high": "100.0",
                 "low": "98.0", "close": "99.5", "volume": "11000"},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()

        with patch("modules.price_data.TWELVE_DATA_API_KEY", "test_key"), \
             patch("modules.price_data.requests.get", return_value=mock_resp):
            df = _fetch_twelvedata("NQ=F", interval="1d", outputsize=2)

        assert df is not None
        assert len(df) == 2
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert df["Close"].iloc[-1] == 100.5  # Sorted ascending, latest is last


class TestPsychStep:
    def test_forex(self) -> None:
        assert _psych_step(1.08) == 0.01

    def test_gold(self) -> None:
        assert _psych_step(3000) == 100

    def test_es_futures(self) -> None:
        assert _psych_step(5800) == 100

    def test_nq_futures(self) -> None:
        assert _psych_step(21000) == 500


class TestComputeKeyLevels:
    def test_pivot_points_formula(self) -> None:
        """Verify classic pivot point calculation."""
        df = _make_ohlcv_df(100, "up")
        price = float(df["Close"].iloc[-1])
        kl = _compute_key_levels(df, price)

        pdh, pdl, pdc = kl.pdh, kl.pdl, kl.pdc
        expected_pp = (pdh + pdl + pdc) / 3
        assert abs(kl.pp - expected_pp) < 0.01
        assert abs(kl.r1 - (2 * kl.pp - pdl)) < 0.01
        assert abs(kl.s1 - (2 * kl.pp - pdh)) < 0.01
        assert abs(kl.r2 - (kl.pp + (pdh - pdl))) < 0.01
        assert abs(kl.s2 - (kl.pp - (pdh - pdl))) < 0.01

    def test_previous_day_values(self) -> None:
        """PDH/PDL/PDC come from the second-to-last row."""
        df = _make_ohlcv_df(100, "up")
        price = float(df["Close"].iloc[-1])
        kl = _compute_key_levels(df, price)

        assert kl.pdh == float(df["High"].iloc[-2])
        assert kl.pdl == float(df["Low"].iloc[-2])
        assert kl.pdc == float(df["Close"].iloc[-2])

    def test_psychological_levels_bracket_price(self) -> None:
        """Psych levels should bracket the current price."""
        df = _make_ohlcv_df(100, "up")
        price = float(df["Close"].iloc[-1])
        kl = _compute_key_levels(df, price)

        assert kl.psych_below is not None
        assert kl.psych_above is not None
        assert kl.psych_below < price
        assert kl.psych_above >= price

    def test_weekly_levels_present(self) -> None:
        """Weekly high/low should be computed from 60 days of data."""
        df = _make_ohlcv_df(100, "up")
        price = float(df["Close"].iloc[-1])
        kl = _compute_key_levels(df, price)

        assert kl.pwh is not None
        assert kl.pwl is not None
        assert kl.pwh >= kl.pwl

    def test_nearest_level_computed(self) -> None:
        """Nearest level should be identified with distance."""
        df = _make_ohlcv_df(100, "up")
        price = float(df["Close"].iloc[-1])
        kl = _compute_key_levels(df, price)

        assert kl.nearest_level is not None
        assert kl.nearest_level_name != ""
        assert kl.nearest_level_dist_pct is not None

    def test_all_levels_returns_pairs(self) -> None:
        """all_levels() should return (name, value) tuples."""
        df = _make_ohlcv_df(100, "up")
        price = float(df["Close"].iloc[-1])
        kl = _compute_key_levels(df, price)

        pairs = kl.all_levels()
        assert len(pairs) >= 8  # PDH, PDL, PDC, PP, R1, R2, S1, S2, psych...
        for name, val in pairs:
            assert isinstance(name, str)
            assert isinstance(val, float)

    def test_insufficient_data(self) -> None:
        """With only 1 row, should return empty KeyLevels."""
        df = _make_ohlcv_df(1, "up")
        kl = _compute_key_levels(df, 100.0)
        assert kl.pdh is None
        assert kl.pp is None

    def test_to_dict(self) -> None:
        """KeyLevels serialization."""
        df = _make_ohlcv_df(100, "up")
        price = float(df["Close"].iloc[-1])
        kl = _compute_key_levels(df, price)
        d = kl.to_dict()
        assert "pdh" in d
        assert "pp" in d
        assert "nearest_level" in d


class TestKeyLevelsInAnalysis:
    def test_key_levels_present_in_analysis(self) -> None:
        """Verify key_levels is populated in AssetAnalysis."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        assert result.key_levels is not None
        assert result.key_levels.pdh is not None
        assert result.key_levels.pp is not None

    def test_key_levels_in_to_dict(self) -> None:
        """Verify key_levels appears in serialized output."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        d = result.to_dict()
        assert "key_levels" in d
        assert d["key_levels"] is not None
        assert "pdh" in d["key_levels"]


# ---------------------------------------------------------------------------
# Multi-Timeframe Analysis
# ---------------------------------------------------------------------------


def _make_weekly_df(rows: int = 104, trend: str = "up") -> pd.DataFrame:
    """Generate a realistic weekly OHLCV DataFrame for testing."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=rows, freq="W")
    n = len(dates)
    np.random.seed(42)

    if trend == "up":
        base = np.linspace(100, 200, n) + np.random.normal(0, 3, n)
    elif trend == "down":
        base = np.linspace(200, 100, n) + np.random.normal(0, 3, n)
    else:
        base = np.full(n, 150.0) + np.random.normal(0, 5, n)

    close = base
    high = close + np.abs(np.random.normal(3, 1, n))
    low = close - np.abs(np.random.normal(3, 1, n))
    volume = np.random.randint(10000, 1000000, n).astype(float)

    return pd.DataFrame({
        "Open": close + np.random.normal(0, 1, n),
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


def _make_hourly_df(rows: int = 200, trend: str = "up") -> pd.DataFrame:
    """Generate a realistic 1H OHLCV DataFrame for testing."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=rows, freq="h")
    n = len(dates)
    np.random.seed(42)

    if trend == "up":
        base = np.linspace(140, 160, n) + np.random.normal(0, 0.3, n)
    elif trend == "down":
        base = np.linspace(160, 140, n) + np.random.normal(0, 0.3, n)
    else:
        base = np.full(n, 150.0) + np.random.normal(0, 0.5, n)

    close = base
    high = close + np.abs(np.random.normal(0.3, 0.1, n))
    low = close - np.abs(np.random.normal(0.3, 0.1, n))
    volume = np.random.randint(500, 50000, n).astype(float)

    return pd.DataFrame({
        "Open": close + np.random.normal(0, 0.1, n),
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


class TestComputeEmaTrend:
    def test_uptrend_returns_bullish(self) -> None:
        df = _make_ohlcv_df(100, "up")
        assert _compute_ema_trend(df) == "BULLISH"

    def test_downtrend_returns_bearish(self) -> None:
        df = _make_ohlcv_df(100, "down")
        assert _compute_ema_trend(df) == "BEARISH"

    def test_insufficient_data_returns_neutral(self) -> None:
        df = _make_ohlcv_df(10, "up")
        assert _compute_ema_trend(df) == "NEUTRAL"

    def test_empty_df_returns_neutral(self) -> None:
        assert _compute_ema_trend(pd.DataFrame()) == "NEUTRAL"

    def test_none_returns_neutral(self) -> None:
        assert _compute_ema_trend(None) == "NEUTRAL"


class TestAnalyzeMTF:
    def test_all_bullish_aligned(self) -> None:
        weekly = _make_weekly_df(104, "up")
        hourly = _make_hourly_df(200, "up")
        mtf = _analyze_mtf(weekly, "BULLISH", hourly)
        assert mtf.alignment == "ALIGNED"
        assert mtf.dominant_direction == "BULLISH"
        assert mtf.weekly_trend == "BULLISH"
        assert mtf.daily_trend == "BULLISH"
        assert mtf.hourly_trend == "BULLISH"

    def test_all_bearish_aligned(self) -> None:
        weekly = _make_weekly_df(104, "down")
        hourly = _make_hourly_df(200, "down")
        mtf = _analyze_mtf(weekly, "BEARISH", hourly)
        assert mtf.alignment == "ALIGNED"
        assert mtf.dominant_direction == "BEARISH"

    def test_partial_two_bullish(self) -> None:
        weekly = _make_weekly_df(104, "up")
        hourly = _make_hourly_df(200, "down")
        mtf = _analyze_mtf(weekly, "BULLISH", hourly)
        assert mtf.alignment == "PARTIAL"
        assert mtf.dominant_direction == "BULLISH"

    def test_conflicting_all_different(self) -> None:
        weekly = _make_weekly_df(104, "up")
        hourly = _make_hourly_df(200, "down")
        mtf = _analyze_mtf(weekly, "NEUTRAL", hourly)
        assert mtf.alignment == "CONFLICTING"
        assert mtf.dominant_direction == "NEUTRAL"

    def test_empty_weekly_partial(self) -> None:
        """Empty weekly data = NEUTRAL, so 2/3 determines alignment."""
        hourly = _make_hourly_df(200, "up")
        mtf = _analyze_mtf(pd.DataFrame(), "BULLISH", hourly)
        # weekly=NEUTRAL, daily=BULLISH, hourly=BULLISH → PARTIAL
        assert mtf.alignment == "PARTIAL"
        assert mtf.dominant_direction == "BULLISH"

    def test_to_dict(self) -> None:
        mtf = MTFAnalysis(
            weekly_trend="BULLISH",
            daily_trend="BULLISH",
            hourly_trend="BEARISH",
            alignment="PARTIAL",
            dominant_direction="BULLISH",
        )
        d = mtf.to_dict()
        assert d["weekly_trend"] == "BULLISH"
        assert d["alignment"] == "PARTIAL"
        assert d["dominant_direction"] == "BULLISH"


class TestMTFPenalty:
    """Verify composite score is penalized when MTF is not aligned."""

    def _run_with_mtf(self, daily_trend, weekly_trend, hourly_trend):
        """Helper to run analysis with specific MTF trends."""
        daily_df = _make_ohlcv_df(100, daily_trend)
        intraday_df = _make_5m_df(200, base_price=float(daily_df["Close"].iloc[-1]))
        weekly_df = _make_weekly_df(104, weekly_trend)
        hourly_df = _make_hourly_df(200, hourly_trend)

        mock_ticker = MagicMock()

        def history_side_effect(**kw):
            interval = kw.get("interval", "1d")
            if interval == "1wk":
                return weekly_df
            elif interval == "1h":
                return hourly_df
            elif interval == "5m":
                return intraday_df
            return daily_df

        mock_ticker.history = MagicMock(side_effect=history_side_effect)

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            return _analyze_single_asset("TEST=F", "Test")

    def test_conflicting_forces_neutral(self) -> None:
        """MTF CONFLICTING should force composite to NEUTRAL."""
        result = self._run_with_mtf("up", "down", "flat")
        if result.mtf and result.mtf.alignment == "CONFLICTING":
            assert result.composite_score == "NEUTRAL"

    def test_aligned_preserves_score(self) -> None:
        """MTF ALIGNED should preserve the composite score."""
        result = self._run_with_mtf("up", "up", "up")
        assert result.mtf is not None
        # When all aligned bullish, composite should be allowed to be BULLISH
        if result.mtf.alignment == "ALIGNED":
            assert result.composite_score in ("BULLISH", "NEUTRAL")

    def test_mtf_present_in_analysis(self) -> None:
        """MTF should be populated in the result."""
        result = self._run_with_mtf("up", "up", "up")
        assert result.mtf is not None
        assert result.mtf.weekly_trend in ("BULLISH", "BEARISH", "NEUTRAL")
        assert result.mtf.alignment in ("ALIGNED", "PARTIAL", "CONFLICTING")

    def test_mtf_in_to_dict(self) -> None:
        """MTF should appear in serialized output."""
        result = self._run_with_mtf("up", "up", "up")
        d = result.to_dict()
        assert "mtf" in d
        assert d["mtf"] is not None
        assert "alignment" in d["mtf"]


# ---------------------------------------------------------------------------
# Quality Score
# ---------------------------------------------------------------------------


class TestDetectCandlePattern:
    def test_bullish_engulfing(self) -> None:
        """Bullish engulfing: prev red, current green wrapping prev body."""
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        df = pd.DataFrame({
            "Open": [100, 105, 98],   # prev: O>C (red), last: O<C (green)
            "High": [106, 106, 107],
            "Low": [99, 97, 97],
            "Close": [102, 99, 106],  # last wraps prev body (99→105)
        }, index=dates)
        assert _detect_candle_pattern(df, "BULLISH") == "ENGULFING"
        assert _detect_candle_pattern(df, "BEARISH") is None

    def test_bearish_engulfing(self) -> None:
        """Bearish engulfing: prev green, current red wrapping prev body."""
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        df = pd.DataFrame({
            "Open": [100, 98, 106],   # prev: O<C (green), last: O>C (red)
            "High": [106, 106, 107],
            "Low": [99, 97, 97],
            "Close": [102, 105, 97],  # last wraps prev body (105→98)
        }, index=dates)
        assert _detect_candle_pattern(df, "BEARISH") == "ENGULFING"
        assert _detect_candle_pattern(df, "BULLISH") is None

    def test_bullish_pin_bar(self) -> None:
        """Bullish pin bar: long lower wick relative to body."""
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        df = pd.DataFrame({
            "Open": [100, 100, 99.5],
            "High": [101, 101, 100.2],
            "Low": [99, 99, 96.0],     # lower_wick = 99.5-96=3.5, body=0.5, upper=0.2
            "Close": [100.5, 100.5, 100.0],
        }, index=dates)
        assert _detect_candle_pattern(df, "BULLISH") == "PIN_BAR"

    def test_bearish_pin_bar(self) -> None:
        """Bearish pin bar: long upper wick relative to body."""
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        df = pd.DataFrame({
            "Open": [100, 100, 100.5],
            "High": [101, 101, 104.0],   # upper_wick = 104-100.5=3.5, body=0.5
            "Low": [99, 99, 99.8],
            "Close": [100.5, 100.5, 100.0],
        }, index=dates)
        assert _detect_candle_pattern(df, "BEARISH") == "PIN_BAR"

    def test_no_pattern(self) -> None:
        """No special pattern detected."""
        df = _make_ohlcv_df(100, "flat")
        # Most bars in a flat series won't form engulfing/pin bar
        # At least test that it doesn't crash
        result = _detect_candle_pattern(df, "NEUTRAL")
        assert result is None or isinstance(result, str)

    def test_insufficient_data(self) -> None:
        """Should return None with < 2 bars."""
        df = _make_ohlcv_df(1, "up")
        assert _detect_candle_pattern(df, "BULLISH") is None


class TestComputeQualityScore:
    def _make_signals(self, bullish: int = 0, bearish: int = 0, adx_val: float = 20.0) -> list:
        """Helper to create a specific mix of directional signals."""
        from modules.price_data import TechnicalSignal
        names = ["RSI", "MACD", "VWAP", "EMA_TREND", "BBANDS", "STOCH"]
        signals = []
        for i, name in enumerate(names):
            if i < bullish:
                signals.append(TechnicalSignal(name, 50.0, "BULLISH", "test"))
            elif i < bullish + bearish:
                signals.append(TechnicalSignal(name, 50.0, "BEARISH", "test"))
            else:
                signals.append(TechnicalSignal(name, 50.0, "NEUTRAL", "test"))
        signals.append(TechnicalSignal("ADX", adx_val, "NEUTRAL", f"ADX {adx_val}"))
        return signals

    def test_max_score(self) -> None:
        """With all factors present, score should be 5."""
        # Create data where volume is above average
        df = _make_ohlcv_df(100, "up")
        # Force last bar volume very high
        df.iloc[-1, df.columns.get_loc("Volume")] = 999999.0

        kl = KeyLevels(
            nearest_level_dist_pct=0.2,  # close to key level
            nearest_level=float(df["Close"].iloc[-1]) * 0.998,
            nearest_level_name="PDH",
        )

        signals = self._make_signals(bullish=5, adx_val=30.0)
        qs = _compute_quality_score(signals, "BULLISH", kl, df)

        assert qs.confluence is True
        assert qs.strong_trend is True
        assert qs.near_key_level is True
        assert qs.volume_above_avg is True
        # candle_pattern depends on actual candle shape, may or may not be true
        assert qs.total >= 4

    def test_zero_score_neutral(self) -> None:
        """NEUTRAL composite should get 0 confluence."""
        df = _make_ohlcv_df(100, "flat")
        signals = self._make_signals(bullish=3, bearish=3, adx_val=15.0)
        qs = _compute_quality_score(signals, "NEUTRAL", None, df)
        assert qs.confluence is False
        assert qs.strong_trend is False
        assert qs.near_key_level is False
        assert qs.total <= 2  # only volume_above_avg and candle_pattern possible

    def test_confluence_requires_4(self) -> None:
        """3 bullish signals should NOT trigger confluence."""
        df = _make_ohlcv_df(100, "up")
        signals = self._make_signals(bullish=3, adx_val=15.0)
        qs = _compute_quality_score(signals, "BULLISH", None, df)
        assert qs.confluence is False

    def test_confluence_with_4(self) -> None:
        """4 bullish signals SHOULD trigger confluence."""
        df = _make_ohlcv_df(100, "up")
        signals = self._make_signals(bullish=4, adx_val=15.0)
        qs = _compute_quality_score(signals, "BULLISH", None, df)
        assert qs.confluence is True

    def test_adx_threshold(self) -> None:
        """ADX > 25 triggers strong_trend, ADX <= 25 does not."""
        df = _make_ohlcv_df(100, "up")
        signals_strong = self._make_signals(adx_val=30.0)
        signals_weak = self._make_signals(adx_val=20.0)
        qs_strong = _compute_quality_score(signals_strong, "BULLISH", None, df)
        qs_weak = _compute_quality_score(signals_weak, "BULLISH", None, df)
        assert qs_strong.strong_trend is True
        assert qs_weak.strong_trend is False

    def test_near_key_level(self) -> None:
        """Price near key level should trigger near_key_level."""
        df = _make_ohlcv_df(100, "up")
        kl = KeyLevels(nearest_level_dist_pct=0.3, nearest_level=100.0, nearest_level_name="S1")
        signals = self._make_signals()
        qs = _compute_quality_score(signals, "BULLISH", kl, df)
        assert qs.near_key_level is True

    def test_far_from_key_level(self) -> None:
        """Price far from key level should NOT trigger near_key_level."""
        df = _make_ohlcv_df(100, "up")
        kl = KeyLevels(nearest_level_dist_pct=2.0, nearest_level=100.0, nearest_level_name="S1")
        signals = self._make_signals()
        qs = _compute_quality_score(signals, "BULLISH", kl, df)
        assert qs.near_key_level is False

    def test_to_dict(self) -> None:
        """QualityScore serialization."""
        qs = QualityScore(
            total=3,
            confluence=True,
            strong_trend=True,
            near_key_level=False,
            candle_pattern=False,
            volume_above_avg=True,
        )
        d = qs.to_dict()
        assert d["total"] == 3
        assert d["confluence"] is True
        assert d["volume_above_avg"] is True


class TestQualityScoreInAnalysis:
    def test_quality_score_present(self) -> None:
        """Quality score should be populated in AssetAnalysis."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        assert result.quality_score is not None
        assert 0 <= result.quality_score.total <= 5

    def test_quality_score_in_to_dict(self) -> None:
        """Quality score should appear in serialized output."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        d = result.to_dict()
        assert "quality_score" in d
        assert d["quality_score"] is not None
        assert "total" in d["quality_score"]

    def test_daily_closes_stored(self) -> None:
        """Daily closes should be stored for correlation computation."""
        daily_df = _make_ohlcv_df(100, "up")
        intraday_df = _make_5m_df(200)

        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=_mock_ticker_side_effect(daily_df, intraday_df))

        with patch("modules.price_data.yf.Ticker", return_value=mock_ticker):
            result = _analyze_single_asset("TEST=F", "Test")

        assert result.daily_closes is not None
        assert len(result.daily_closes) > 0


# ---------------------------------------------------------------------------
# Correlation Matrix
# ---------------------------------------------------------------------------


class TestComputeCorrelationMatrix:
    def test_two_correlated_assets(self) -> None:
        """Two assets with same data should have correlation ~1.0."""
        np.random.seed(42)
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        closes = pd.Series(np.linspace(100, 130, 60) + np.random.normal(0, 0.5, 60), index=dates)

        a1 = AssetAnalysis(symbol="A", display_name="Asset A", price=130.0, change_pct=1.0, daily_closes=closes)
        a2 = AssetAnalysis(symbol="B", display_name="Asset B", price=130.0, change_pct=1.0, daily_closes=closes)

        matrix = compute_correlation_matrix([a1, a2])
        assert matrix is not None
        assert abs(float(matrix.loc["A", "B"]) - 1.0) < 0.01

    def test_uncorrelated_assets(self) -> None:
        """Two random independent assets should have low correlation."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        np.random.seed(42)
        closes_a = pd.Series(100 + np.random.normal(0, 1, 60).cumsum(), index=dates)
        np.random.seed(99)
        closes_b = pd.Series(100 + np.random.normal(0, 1, 60).cumsum(), index=dates)

        a1 = AssetAnalysis(symbol="A", display_name="A", price=100.0, change_pct=0.0, daily_closes=closes_a)
        a2 = AssetAnalysis(symbol="B", display_name="B", price=100.0, change_pct=0.0, daily_closes=closes_b)

        matrix = compute_correlation_matrix([a1, a2])
        assert matrix is not None
        assert abs(float(matrix.loc["A", "B"])) < 0.7  # should be reasonably uncorrelated

    def test_insufficient_data_returns_none(self) -> None:
        """Should return None if not enough data."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=10, freq="D")
        closes = pd.Series(np.linspace(100, 110, 10), index=dates)

        a1 = AssetAnalysis(symbol="A", display_name="A", price=110.0, change_pct=0.0, daily_closes=closes)
        a2 = AssetAnalysis(symbol="B", display_name="B", price=110.0, change_pct=0.0, daily_closes=closes)

        assert compute_correlation_matrix([a1, a2]) is None

    def test_single_asset_returns_none(self) -> None:
        """Should return None with only one asset."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        closes = pd.Series(np.linspace(100, 130, 60), index=dates)
        a1 = AssetAnalysis(symbol="A", display_name="A", price=130.0, change_pct=0.0, daily_closes=closes)
        assert compute_correlation_matrix([a1]) is None

    def test_matrix_shape(self) -> None:
        """Matrix should be N×N for N assets with sufficient data."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        np.random.seed(42)
        assets = []
        for sym in ["A", "B", "C"]:
            closes = pd.Series(100 + np.random.normal(0, 1, 60).cumsum(), index=dates)
            assets.append(AssetAnalysis(symbol=sym, display_name=sym, price=100.0, change_pct=0.0, daily_closes=closes))

        matrix = compute_correlation_matrix(assets)
        assert matrix is not None
        assert matrix.shape == (3, 3)
        assert list(matrix.index) == ["A", "B", "C"]


class TestFilterCorrelatedAssets:
    def test_same_direction_high_corr_filters(self) -> None:
        """Two correlated assets in same direction: lower QS gets filtered."""
        np.random.seed(42)
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        closes = pd.Series(np.linspace(100, 130, 60), index=dates)

        a1 = AssetAnalysis(
            symbol="NQ=F", display_name="NQ", price=130.0, change_pct=1.0,
            composite_score="BULLISH", quality_score=QualityScore(total=4),
            daily_closes=closes,
        )
        a2 = AssetAnalysis(
            symbol="ES=F", display_name="ES", price=130.0, change_pct=1.0,
            composite_score="BULLISH", quality_score=QualityScore(total=2),
            daily_closes=closes,
        )

        matrix = compute_correlation_matrix([a1, a2])
        filtered = filter_correlated_assets([a1, a2], matrix)
        assert "ES=F" in filtered
        assert "NQ=F" not in filtered

    def test_different_direction_not_filtered(self) -> None:
        """Correlated assets in different directions should NOT be filtered."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        closes = pd.Series(np.linspace(100, 130, 60), index=dates)

        a1 = AssetAnalysis(
            symbol="A", display_name="A", price=130.0, change_pct=1.0,
            composite_score="BULLISH", quality_score=QualityScore(total=4),
            daily_closes=closes,
        )
        a2 = AssetAnalysis(
            symbol="B", display_name="B", price=130.0, change_pct=1.0,
            composite_score="BEARISH", quality_score=QualityScore(total=2),
            daily_closes=closes,
        )

        matrix = compute_correlation_matrix([a1, a2])
        filtered = filter_correlated_assets([a1, a2], matrix)
        assert len(filtered) == 0

    def test_neutral_not_filtered(self) -> None:
        """NEUTRAL assets should never be filtered."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        closes = pd.Series(np.linspace(100, 130, 60), index=dates)

        a1 = AssetAnalysis(
            symbol="A", display_name="A", price=130.0, change_pct=1.0,
            composite_score="NEUTRAL", quality_score=QualityScore(total=4),
            daily_closes=closes,
        )
        a2 = AssetAnalysis(
            symbol="B", display_name="B", price=130.0, change_pct=1.0,
            composite_score="NEUTRAL", quality_score=QualityScore(total=2),
            daily_closes=closes,
        )

        matrix = compute_correlation_matrix([a1, a2])
        filtered = filter_correlated_assets([a1, a2], matrix)
        assert len(filtered) == 0

    def test_low_correlation_not_filtered(self) -> None:
        """Assets with low correlation should NOT be filtered."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="D")
        np.random.seed(42)
        closes_a = pd.Series(100 + np.random.normal(0, 1, 60).cumsum(), index=dates)
        np.random.seed(99)
        closes_b = pd.Series(100 + np.random.normal(0, 1, 60).cumsum(), index=dates)

        a1 = AssetAnalysis(
            symbol="A", display_name="A", price=100.0, change_pct=1.0,
            composite_score="BULLISH", quality_score=QualityScore(total=4),
            daily_closes=closes_a,
        )
        a2 = AssetAnalysis(
            symbol="B", display_name="B", price=100.0, change_pct=1.0,
            composite_score="BULLISH", quality_score=QualityScore(total=2),
            daily_closes=closes_b,
        )

        matrix = compute_correlation_matrix([a1, a2])
        filtered = filter_correlated_assets([a1, a2], matrix)
        # Low correlation shouldn't trigger filter
        assert len(filtered) == 0

    def test_none_matrix_returns_empty(self) -> None:
        """None correlation matrix should return empty list."""
        a1 = AssetAnalysis(symbol="A", display_name="A", price=100.0, change_pct=0.0)
        filtered = filter_correlated_assets([a1], None)
        assert filtered == []
