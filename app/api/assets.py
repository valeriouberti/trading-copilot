"""Asset management API endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import reload_config, save_config

logger = logging.getLogger(__name__)

router = APIRouter()


class AssetCreate(BaseModel):
    symbol: str
    display_name: str = ""


@router.get("/assets")
async def list_assets(request: Request):
    """Return the list of configured assets."""
    config = request.app.state.config
    assets = config.get("assets", [])
    return {
        "assets": assets,
        "count": len(assets),
    }


@router.post("/assets", status_code=201)
async def add_asset(request: Request, body: AssetCreate):
    """Add a new asset to config.yaml after validating the symbol."""
    symbol = body.symbol.strip().upper()
    display_name = body.display_name.strip()

    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol cannot be empty")

    config = request.app.state.config
    assets = config.get("assets", [])

    # Check for duplicates
    if any(a["symbol"] == symbol for a in assets):
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

    new_asset = {"symbol": symbol, "display_name": display_name}
    assets.append(new_asset)
    config["assets"] = assets

    # Persist to config.yaml and refresh app state
    save_config(config)
    request.app.state.config = reload_config()

    return {"asset": new_asset, "message": f"{symbol} added"}


@router.delete("/assets/{symbol}")
async def remove_asset(request: Request, symbol: str):
    """Remove an asset from config.yaml."""
    config = request.app.state.config
    assets = config.get("assets", [])

    original_len = len(assets)
    assets = [a for a in assets if a["symbol"] != symbol]

    if len(assets) == original_len:
        raise HTTPException(status_code=404, detail=f"{symbol} not found")

    if len(assets) == 0:
        raise HTTPException(status_code=400, detail="Cannot remove last asset")

    config["assets"] = assets
    save_config(config)
    request.app.state.config = reload_config()

    return {"message": f"{symbol} removed", "remaining": len(assets)}


def _validate_symbol(symbol: str) -> tuple[bool, dict]:
    """Check that a symbol exists on yfinance. Returns (valid, info_dict)."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    # yfinance returns a dict with only 'trailingPegRatio' or similar for invalid symbols
    # A valid ticker has 'regularMarketPrice' or 'previousClose'
    valid = bool(
        info.get("regularMarketPrice")
        or info.get("previousClose")
        or info.get("ask")
    )
    return valid, info
