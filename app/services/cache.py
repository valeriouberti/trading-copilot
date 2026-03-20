"""In-memory TTL cache for analysis pipeline stages.

Thread-safe, async-compatible cache to avoid redundant API calls.
Each cache entry has a per-key TTL (time-to-live in seconds).

Default TTLs:
- price:     60s   (market data changes frequently)
- news:     300s   (5 min — RSS feeds update ~every 5 min)
- sentiment: 600s  (10 min — LLM calls are expensive)
- calendar: 3600s  (1 hour — calendar events are daily)
- polymarket: 600s (10 min — prediction markets are relatively stable)

Usage::

    cache = AnalysisCache()
    result = cache.get("NQ=F", "price")
    if result is None:
        result = expensive_fetch()
        cache.set("NQ=F", "price", result)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default TTLs in seconds
DEFAULT_TTLS: dict[str, int] = {
    "price": 60,
    "news": 300,
    "sentiment": 600,
    "calendar": 3600,
    "polymarket": 600,
    "heavy_analysis": 1800,  # 30 min — full indicator + signal analysis
}


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.monotonic)


class AnalysisCache:
    """Thread-safe in-memory cache with per-type TTL."""

    def __init__(self, ttls: dict[str, int] | None = None):
        self._store: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._ttls = {**DEFAULT_TTLS, **(ttls or {})}
        self._hits = 0
        self._misses = 0

    def _make_key(self, symbol: str, data_type: str) -> str:
        return f"{symbol}:{data_type}"

    def get(self, symbol: str, data_type: str) -> Any | None:
        """Return cached value or None if expired/missing."""
        key = self._make_key(symbol, data_type)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    def set(self, symbol: str, data_type: str, value: Any, ttl: int | None = None) -> None:
        """Cache a value with the given or default TTL."""
        key = self._make_key(symbol, data_type)
        if ttl is None:
            ttl = self._ttls.get(data_type, 300)
        now = time.monotonic()
        with self._lock:
            self._store[key] = CacheEntry(
                value=value,
                expires_at=now + ttl,
                created_at=now,
            )

    def invalidate(self, symbol: str, data_type: str | None = None) -> int:
        """Remove cache entries. If data_type is None, remove all for the symbol."""
        removed = 0
        with self._lock:
            if data_type:
                key = self._make_key(symbol, data_type)
                if key in self._store:
                    del self._store[key]
                    removed = 1
            else:
                keys_to_remove = [
                    k for k in self._store if k.startswith(f"{symbol}:")
                ]
                for k in keys_to_remove:
                    del self._store[k]
                    removed += 1
        return removed

    def clear(self) -> int:
        """Remove all cache entries."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            self._hits = 0
            self._misses = 0
            return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Call periodically."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired = [k for k, v in self._store.items() if now > v.expires_at]
            for k in expired:
                del self._store[k]
                removed += 1
        if removed:
            logger.debug("Cache cleanup: removed %d expired entries", removed)
        return removed

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            now = time.monotonic()
            active = sum(1 for v in self._store.values() if now <= v.expires_at)
            expired = len(self._store) - active
            total = self._hits + self._misses
            return {
                "entries": len(self._store),
                "active": active,
                "expired": expired,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0.0,
            }
