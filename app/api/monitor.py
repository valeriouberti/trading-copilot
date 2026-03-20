"""Monitor API endpoints — start, stop, check status, and view credit budget."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.middleware.rate_limit import MONITOR_RATE, limiter

router = APIRouter()


class MonitorStart(BaseModel):
    symbol: str


@router.post("/monitor/start")
@limiter.limit(MONITOR_RATE)
async def start_monitor(request: Request, body: MonitorStart):
    """Start background monitoring for an asset.

    Uses a fixed heavy (30 min) + light (120 s) split schedule.
    Max 3 assets simultaneously (Twelve Data free-tier budget).
    """
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Monitor not initialized")

    result = await monitor.start(body.symbol)

    if result.get("status") == "REJECTED":
        raise HTTPException(status_code=429, detail=result["reason"])

    return result


@router.post("/monitor/stop")
@limiter.limit(MONITOR_RATE)
async def stop_monitor(request: Request, body: MonitorStart):
    """Stop background monitoring for an asset."""
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Monitor not initialized")

    result = await monitor.stop(body.symbol)
    return result


@router.get("/monitor/status")
async def monitor_status(request: Request):
    """Return status of all active monitors."""
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        return {"monitors": [], "ws_connections": 0}

    from app.api.websocket import manager

    statuses = await monitor.get_status()
    return {
        "monitors": statuses,
        "ws_connections": manager.count,
    }


@router.get("/monitor/budget")
async def monitor_budget(request: Request):
    """Return Twelve Data credit budget status for today."""
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        return {"error": "Monitor not initialized"}

    return monitor.get_budget()
