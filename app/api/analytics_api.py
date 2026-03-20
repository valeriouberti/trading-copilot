"""Analytics API endpoints — correlation heatmap and portfolio analysis."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request

from app.middleware.rate_limit import GENERAL_RATE, limiter
from app.models.database import get_all_assets

logger = logging.getLogger(__name__)

router = APIRouter()


def _compute_heatmap(assets: list[dict]) -> dict:
    """Run technical analysis on all assets and return correlation matrix data.

    Returns a dict with ``symbols`` (list[str]) and ``matrix`` (list[list[float]]).
    """
    from modules.price_data import analyze_assets, compute_correlation_matrix

    analyses = analyze_assets(assets)
    corr = compute_correlation_matrix(analyses)

    if corr is None:
        return {"symbols": [], "matrix": []}

    symbols = list(corr.index)
    matrix = corr.values.tolist()

    # Round values for cleaner JSON output
    matrix = [
        [round(float(v), 4) for v in row]
        for row in matrix
    ]

    return {"symbols": symbols, "matrix": matrix}


@router.get("/analytics/heatmap")
@limiter.limit(GENERAL_RATE)
async def heatmap(request: Request):
    """Return correlation matrix data for all monitored assets.

    Response format::

        {
            "symbols": ["NQ=F", "ES=F", ...],
            "matrix": [[1.0, 0.3, ...], ...]
        }
    """
    assets = await get_all_assets(request.app.state.session_factory)
    if not assets:
        return {"symbols": [], "matrix": []}

    result = await asyncio.to_thread(_compute_heatmap, assets)
    return result
