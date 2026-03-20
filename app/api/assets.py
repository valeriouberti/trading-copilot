"""Asset management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import get_config

router = APIRouter()


@router.get("/assets")
async def list_assets(config: dict = Depends(get_config)):
    """Return the list of configured assets."""
    assets = config.get("assets", [])
    return {
        "assets": assets,
        "count": len(assets),
    }
