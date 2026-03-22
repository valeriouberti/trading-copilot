"""Tests for the split monitor architecture: credit tracker, fetch_quote, merge_price."""

from __future__ import annotations

import pytest


# ─── Credit Tracker ───────────────────────────────────────────────────

class TestCreditTracker:
    def test_initial_state(self):
        from modules.data.credit_tracker import CreditTracker
        ct = CreditTracker(daily_limit=100)
        assert ct.remaining == 100
        assert ct.used == 0

    def test_try_spend_success(self):
        from modules.data.credit_tracker import CreditTracker
        ct = CreditTracker(daily_limit=10)
        assert ct.try_spend(5) is True
        assert ct.used == 5
        assert ct.remaining == 5

    def test_try_spend_over_budget(self):
        from modules.data.credit_tracker import CreditTracker
        ct = CreditTracker(daily_limit=5)
        assert ct.try_spend(3) is True
        assert ct.try_spend(3) is False  # would exceed
        assert ct.used == 3

    def test_spend_unconditional(self):
        from modules.data.credit_tracker import CreditTracker
        ct = CreditTracker(daily_limit=5)
        ct.spend(3)
        assert ct.used == 3

    def test_stats(self):
        from modules.data.credit_tracker import CreditTracker
        ct = CreditTracker(daily_limit=100)
        ct.spend(25)
        s = ct.stats()
        assert s["used"] == 25
        assert s["remaining"] == 75
        assert s["limit"] == 100
        assert s["pct_used"] == 25.0

    def test_max_assets_estimation(self):
        from modules.data.credit_tracker import CreditTracker
        ct = CreditTracker(daily_limit=750)
        # Should be able to monitor at least 1 asset
        assert ct.max_assets() >= 1


# ─── Twelve Data fetch_quote ──────────────────────────────────────────

class TestFetchQuote:
    def test_no_api_key_returns_none(self):
        from modules.data.twelvedata_provider import TwelveDataProvider
        provider = TwelveDataProvider(api_key="")
        assert provider.fetch_quote("EURUSD") is None

    def test_fetch_quote_parses_response(self, monkeypatch):
        from modules.data.twelvedata_provider import TwelveDataProvider
        import requests

        class MockResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"price": "1.08542"}

        def mock_get(*a, **kw):
            return MockResp()

        monkeypatch.setattr(requests, "get", mock_get)

        provider = TwelveDataProvider(api_key="test_key")
        price = provider.fetch_quote("EURUSD")
        assert price == pytest.approx(1.08542)

    def test_fetch_quote_handles_error(self, monkeypatch):
        from modules.data.twelvedata_provider import TwelveDataProvider
        import requests

        def mock_get(*a, **kw):
            raise requests.ConnectionError("timeout")

        monkeypatch.setattr(requests, "get", mock_get)

        provider = TwelveDataProvider(api_key="test_key")
        assert provider.fetch_quote("EURUSD") is None


# ─── Merge Price (removed — AssetMonitor replaced by ETFScheduler) ────


# ─── Cache TTL ────────────────────────────────────────────────────────

class TestCacheTTL:
    def test_heavy_analysis_ttl_exists(self):
        from app.services.cache import DEFAULT_TTLS
        assert "heavy_analysis" in DEFAULT_TTLS
        assert DEFAULT_TTLS["heavy_analysis"] == 1800
