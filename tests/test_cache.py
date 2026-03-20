"""Tests for the in-memory TTL cache."""

from __future__ import annotations

import time
from unittest.mock import patch

from app.services.cache import AnalysisCache


class TestAnalysisCache:
    def test_set_and_get(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", {"current": 21000})
        assert cache.get("NQ=F", "price") == {"current": 21000}

    def test_get_missing_returns_none(self):
        cache = AnalysisCache()
        assert cache.get("NQ=F", "price") is None

    def test_expired_entry_returns_none(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", {"current": 21000}, ttl=0)
        # Entry expires immediately (ttl=0 means now + 0)
        time.sleep(0.01)
        assert cache.get("NQ=F", "price") is None

    def test_default_ttls(self):
        cache = AnalysisCache()
        assert cache._ttls["price"] == 60
        assert cache._ttls["news"] == 300
        assert cache._ttls["sentiment"] == 600
        assert cache._ttls["calendar"] == 3600

    def test_custom_ttls(self):
        cache = AnalysisCache(ttls={"price": 10})
        assert cache._ttls["price"] == 10
        assert cache._ttls["news"] == 300  # default preserved

    def test_invalidate_single(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", 100)
        cache.set("NQ=F", "news", [])
        assert cache.invalidate("NQ=F", "price") == 1
        assert cache.get("NQ=F", "price") is None
        assert cache.get("NQ=F", "news") == []

    def test_invalidate_all_for_symbol(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", 100)
        cache.set("NQ=F", "news", [])
        cache.set("ES=F", "price", 200)
        assert cache.invalidate("NQ=F") == 2
        assert cache.get("NQ=F", "price") is None
        assert cache.get("ES=F", "price") == 200

    def test_clear(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", 100)
        cache.set("ES=F", "price", 200)
        assert cache.clear() == 2
        assert cache.get("NQ=F", "price") is None
        assert cache.get("ES=F", "price") is None

    def test_cleanup_expired(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", 100, ttl=0)
        cache.set("ES=F", "price", 200, ttl=3600)
        time.sleep(0.01)
        assert cache.cleanup_expired() == 1
        assert cache.get("ES=F", "price") == 200

    def test_stats(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", 100)
        cache.get("NQ=F", "price")  # hit
        cache.get("NQ=F", "news")   # miss

        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0

    def test_overwrite_existing(self):
        cache = AnalysisCache()
        cache.set("NQ=F", "price", 100)
        cache.set("NQ=F", "price", 200)
        assert cache.get("NQ=F", "price") == 200
