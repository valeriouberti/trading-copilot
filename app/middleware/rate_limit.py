"""Rate limiting middleware using slowapi.

Limits:
- Analysis endpoints: 60 req/min
- Monitor control endpoints: 10 req/min
- General API: 120 req/min
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Rate limit strings (slowapi format)
ANALYSIS_RATE = "60/minute"
MONITOR_RATE = "10/minute"
GENERAL_RATE = "120/minute"
