"""Analysis API endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from app.middleware.rate_limit import ANALYSIS_RATE, limiter
from app.models.database import get_all_assets
from app.models.engine import get_db
from app.services.analyzer import analyze_single_asset, _run_technicals, _format_analysis
from app.services.notifier import get_notifier

router = APIRouter()


async def _resolve_asset(request: Request, symbol: str) -> dict:
    """Resolve an asset dict from the database."""
    assets = await get_all_assets(request.app.state.session_factory)
    return next(
        (a for a in assets if a["symbol"] == symbol),
        {"symbol": symbol, "display_name": symbol},
    )


@router.get("/chart/{symbol}")
@limiter.limit(ANALYSIS_RATE)
async def get_chart_data(request: Request, symbol: str):
    """Return only price chart data (OHLC + EMA) for fast initial page load."""
    asset = await _resolve_asset(request, symbol)
    try:
        tech_result = await asyncio.to_thread(_run_technicals, asset)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    formatted = _format_analysis(tech_result)
    return {
        "chart": formatted.get("chart"),
        "price": formatted.get("price"),
    }


@router.post("/analyze/{symbol}")
@limiter.limit(ANALYSIS_RATE)
async def analyze_asset(
    request: Request,
    symbol: str,
    skip_llm: bool = Query(False, description="Skip LLM sentiment analysis"),
    skip_polymarket: bool = Query(False, description="Skip Polymarket data"),
):
    """Run the full analysis pipeline for a single asset."""
    config = request.app.state.config
    asset = await _resolve_asset(request, symbol)
    result = await analyze_single_asset(
        symbol=symbol,
        config=config,
        skip_llm=skip_llm,
        skip_polymarket=skip_polymarket,
        asset=asset,
    )
    return result


@router.post("/analyze/{symbol}/telegram")
async def send_analysis_telegram(request: Request, symbol: str):
    """Run analysis and send the signal to Telegram."""
    config = request.app.state.config

    notifier = get_notifier(config)
    if not notifier.enabled:
        raise HTTPException(status_code=400, detail="Telegram not enabled")

    asset = await _resolve_asset(request, symbol)
    result = await analyze_single_asset(symbol=symbol, config=config, asset=asset)

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
