"""Monitor API endpoints — start/stop scheduler, view schedule, trigger analysis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.middleware.rate_limit import MONITOR_RATE, limiter

router = APIRouter()


@router.post("/monitor/start")
@limiter.limit(MONITOR_RATE)
async def start_scheduler(request: Request):
    """Start the ETF cron scheduler (08:00 / 13:00 / 17:00 CET)."""
    scheduler = getattr(request.app.state, "monitor", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    scheduler.start()
    return {"status": "RUNNING", "schedule": scheduler.get_schedule()}


@router.post("/monitor/stop")
@limiter.limit(MONITOR_RATE)
async def stop_scheduler(request: Request):
    """Stop the ETF cron scheduler."""
    scheduler = getattr(request.app.state, "monitor", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    scheduler.stop()
    return {"status": "STOPPED"}


@router.get("/monitor/status")
async def monitor_status(request: Request):
    """Return scheduler status and next scheduled runs."""
    scheduler = getattr(request.app.state, "monitor", None)
    if scheduler is None:
        return {"status": "NOT_INITIALIZED", "schedule": []}

    from app.api.websocket import manager

    return {
        "status": "RUNNING" if scheduler._started else "STOPPED",
        "schedule": scheduler.get_schedule(),
        "ws_connections": manager.count,
    }


@router.get("/monitor/schedule")
async def monitor_schedule(request: Request):
    """Show next scheduled analysis times."""
    scheduler = getattr(request.app.state, "monitor", None)
    if scheduler is None:
        return {"schedule": []}

    return {"schedule": scheduler.get_schedule()}


@router.post("/analyze-all")
@limiter.limit(MONITOR_RATE)
async def analyze_all_now(request: Request):
    """Trigger the morning briefing on demand (Analyze Now button)."""
    scheduler = getattr(request.app.state, "monitor", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    result = await scheduler.run_morning_briefing()
    return {
        "status": "completed",
        "buy_count": len(result.get("buy", [])),
        "sell_count": len(result.get("sell", [])),
        "hold_count": len(result.get("hold", [])),
        "buy_signals": result.get("buy", []),
        "sell_signals": result.get("sell", []),
    }
