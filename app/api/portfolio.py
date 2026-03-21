"""Portfolio API — manage open and closed ETF positions."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.models.database import (
    close_position,
    create_position,
    get_open_positions,
)

router = APIRouter()


class PositionCreate(BaseModel):
    symbol: str
    entry_price: float = Field(gt=0)
    shares: int = Field(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    notes: str | None = None


class PositionClose(BaseModel):
    exit_price: float = Field(gt=0)
    notes: str | None = None


@router.get("/portfolio")
async def list_positions(request: Request):
    """List all open positions with current prices."""
    session_factory = request.app.state.session_factory
    positions = await get_open_positions(session_factory)

    from app.config import get_settings
    settings = get_settings()

    return {
        "positions": positions,
        "count": len(positions),
        "max_positions": settings.max_positions,
    }


@router.post("/portfolio")
async def open_position(request: Request, body: PositionCreate):
    """Record a new open position."""
    session_factory = request.app.state.session_factory

    # Check max positions
    from app.config import get_settings
    settings = get_settings()
    existing = await get_open_positions(session_factory)
    if len(existing) >= settings.max_positions:
        raise HTTPException(
            status_code=400,
            detail=f"Max {settings.max_positions} open positions reached",
        )

    pos_id = await create_position(
        session_factory,
        symbol=body.symbol,
        entry_price=body.entry_price,
        shares=body.shares,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
        notes=body.notes,
    )

    return {"id": pos_id, "status": "OPEN", "symbol": body.symbol}


@router.put("/portfolio/{position_id}/close")
async def close_pos(request: Request, position_id: int, body: PositionClose):
    """Close an open position with exit price."""
    session_factory = request.app.state.session_factory

    result = await close_position(
        session_factory,
        position_id=position_id,
        exit_price=body.exit_price,
        notes=body.notes,
    )

    if result is None:
        raise HTTPException(status_code=404, detail="Position not found or already closed")

    return result


@router.delete("/portfolio/{position_id}")
async def delete_position(request: Request, position_id: int):
    """Delete a position record."""
    from sqlalchemy import select
    from app.models.database import Position

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        pos = await session.get(Position, position_id)
        if pos is None:
            raise HTTPException(status_code=404, detail="Position not found")
        await session.delete(pos)
        await session.commit()

    return {"deleted": position_id}
