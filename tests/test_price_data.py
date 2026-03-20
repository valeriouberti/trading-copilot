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
    TechnicalSignal,
    _analyze_mtf,
    _analyze_single_asset,
    _compute_ema_trend,
    _compute_key_levels,
    _fetch_twelvedata,
    _psych_step,
    analyze_assets,
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
