"""Monitor API endpoints — start, stop, and check status of background monitors."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.middleware.rate_limit import MONITOR_RATE, limiter

router = APIRouter()


class MonitorStart(BaseModel):
    symbol: str
    interval_seconds: int = 60


@router.post("/monitor/start")
@limiter.limit(MONITOR_RATE)
async def start_monitor(request: Request, body: MonitorStart):
    """Start background monitoring for an asset."""
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Monitor not initialized")

    if body.interval_seconds < 30:
        raise HTTPException(status_code=400, detail="Minimum interval is 30 seconds")
    if body.interval_seconds > 600:
        raise HTTPException(status_code=400, detail="Maximum interval is 600 seconds")

    result = await monitor.start(body.symbol, body.interval_seconds)
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
