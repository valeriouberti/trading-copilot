"""Analysis API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.services.analyzer import analyze_single_asset

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
