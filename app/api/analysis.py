"""Analysis API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.engine import get_db
from app.services.analyzer import analyze_single_asset
from app.services.notifier import get_notifier

router = APIRouter()


@router.post("/analyze/{symbol}")
async def analyze_asset(
    request: Request,
    symbol: str,
    skip_llm: bool = Query(False, description="Skip LLM sentiment analysis"),
    skip_polymarket: bool = Query(False, description="Skip Polymarket data"),
):
    """Run the full analysis pipeline for a single asset."""
    config = request.app.state.config
    result = await analyze_single_asset(
        symbol=symbol,
        config=config,
        skip_llm=skip_llm,
        skip_polymarket=skip_polymarket,
    )
    return result


@router.post("/analyze/{symbol}/telegram")
async def send_analysis_telegram(request: Request, symbol: str):
    """Run analysis and send the signal to Telegram."""
    config = request.app.state.config

    notifier = get_notifier(config)
    if not notifier.enabled:
        raise HTTPException(status_code=400, detail="Telegram not enabled")

    result = await analyze_single_asset(symbol=symbol, config=config)

    setup = result.get("setup", {})
    if not setup.get("direction"):
        raise HTTPException(
            status_code=422,
            detail=f"No tradeable signal for {symbol}: {setup.get('reason', 'unknown')}",
        )

    async for session in get_db(request):
        sent = await notifier.send_signal(
            symbol=symbol,
            display_name=result.get("display_name", symbol),
            setup=setup,
            regime=result.get("regime", "NEUTRAL"),
            regime_reason=result.get("regime_reason", ""),
            sentiment=result.get("sentiment"),
            calendar=result.get("calendar"),
            session=session,
        )

    if not sent:
        raise HTTPException(status_code=502, detail="Failed to send Telegram message")

    return {"message": f"Signal sent to Telegram for {symbol}"}
