"""Health check endpoint for Docker and monitoring."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Return OK if the service is running."""
    return {"status": "ok"}
