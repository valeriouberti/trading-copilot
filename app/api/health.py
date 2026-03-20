"""Health check endpoint for Docker and monitoring."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Extended health check — verifies DB, monitor, cache, and circuit breakers.

    Returns 200 if all critical systems are OK, 503 otherwise.
    """
    checks: dict = {}
    overall = "ok"

    # --- Database connectivity ---
    try:
        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            await session.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        overall = "degraded"

    # --- Monitor heartbeat ---
    try:
        monitor = getattr(request.app.state, "monitor", None)
        if monitor and monitor._started:
            checks["monitor"] = "running"
        elif monitor:
            checks["monitor"] = "stopped"
        else:
            checks["monitor"] = "not initialized"
    except Exception as exc:
        checks["monitor"] = f"error: {exc}"

    # --- Cache stats ---
    try:
        from app.services.analyzer import get_cache
        cache = get_cache()
        checks["cache"] = cache.stats()
    except Exception:
        checks["cache"] = "unavailable"

    # --- Circuit breakers ---
    try:
        from modules.circuit_breaker import (
            yfinance_breaker,
            groq_breaker,
            polymarket_breaker,
        )
        breakers = {
            "yfinance": yfinance_breaker.state.value,
            "groq": groq_breaker.state.value,
            "polymarket": polymarket_breaker.state.value,
        }
        checks["circuit_breakers"] = breakers
        if any(v == "OPEN" for v in breakers.values()):
            overall = "degraded"
    except Exception:
        checks["circuit_breakers"] = "unavailable"

    # --- Drawdown breaker ---
    try:
        if monitor and hasattr(monitor, "_drawdown_breaker") and monitor._drawdown_breaker:
            dd_status = await monitor._drawdown_breaker.status()
            checks["drawdown_breaker"] = dd_status
    except Exception:
        pass

    status_code = 200 if overall == "ok" else 503
    return JSONResponse(
        content={"status": overall, "checks": checks},
        status_code=status_code,
    )
