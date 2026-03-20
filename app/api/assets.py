"""Asset management API endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from app.models.database import Asset, get_all_assets

logger = logging.getLogger(__name__)

router = APIRouter()


class AssetCreate(BaseModel):
    symbol: str
    display_name: str = ""


@router.get("/assets")
async def list_assets(request: Request):
    """Return the list of configured assets."""
    assets = await get_all_assets(request.app.state.session_factory)
    return {
        "assets": assets,
        "count": len(assets),
    }


@router.post("/assets", status_code=201)
async def add_asset(request: Request, body: AssetCreate):
    """Add a new asset after validating the symbol via yfinance."""
    symbol = body.symbol.strip().upper()
    display_name = body.display_name.strip()

    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol cannot be empty")

    session_factory = request.app.state.session_factory

    # Check for duplicates
    async with session_factory() as session:
        existing = await session.execute(
            select(Asset).where(Asset.symbol == symbol)
        )
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail=f"{symbol} already exists")

    # Validate symbol via yfinance (run in thread — it's sync)
    try:
        valid, info = await asyncio.to_thread(_validate_symbol, symbol)
    except Exception as exc:
        logger.error("Symbol validation error: %s", exc)
        raise HTTPException(status_code=502, detail="Could not validate symbol") from exc

    if not valid:
        raise HTTPException(status_code=422, detail=f"Symbol '{symbol}' not found on yfinance")

    # Auto-fill display_name from yfinance if not provided
    if not display_name:
        display_name = info.get("shortName") or info.get("longName") or symbol

    async with session_factory() as session:
        asset = Asset(symbol=symbol, display_name=display_name)
        session.add(asset)
        await session.commit()

    new_asset = {"symbol": symbol, "display_name": display_name}
    return {"asset": new_asset, "message": f"{symbol} added"}


@router.delete("/assets/{symbol}")
async def remove_asset(request: Request, symbol: str):
    """Remove an asset from the database."""
    session_factory = request.app.state.session_factory

    async with session_factory() as session:
        # Check exists
        existing = await session.execute(
            select(Asset).where(Asset.symbol == symbol)
        )
        if not existing.scalars().first():
            raise HTTPException(status_code=404, detail=f"{symbol} not found")

        # Check not last
        count = await session.scalar(select(func.count()).select_from(Asset))
        if count is not None and count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove last asset")

        await session.execute(delete(Asset).where(Asset.symbol == symbol))
        await session.commit()

    return {"message": f"{symbol} removed"}


def _validate_symbol(symbol: str) -> tuple[bool, dict]:
    """Check that a symbol exists on yfinance. Returns (valid, info_dict)."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    valid = bool(
        info.get("regularMarketPrice")
        or info.get("previousClose")
        or info.get("ask")
    )
    return valid, info
