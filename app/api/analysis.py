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


@router.get("/quote/{symbol}")
async def get_quote(request: Request, symbol: str):
    """Return just the current price for a symbol (lightweight, no analysis).

    Uses yfinance fast_info (free, no credits). Falls back to Twelve Data
    fetch_quote if yfinance fails.
    """
    import yfinance as yf

    price = None

    try:
        def _yf_price():
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            return getattr(info, "last_price", None) or getattr(info, "previous_close", None)

        price = await asyncio.to_thread(_yf_price)
    except Exception:
        pass

    if price is None:
        raise HTTPException(status_code=502, detail=f"Could not fetch price for {symbol}")

    return {"symbol": symbol, "price": price, "source": "yfinance"}


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


# Timeframe → (yfinance period, yfinance interval)
_TF_CONFIG = {
    "1d":  ("10mo", "1d"),
    "1wk": ("2y",  "1wk"),
}


@router.get("/ohlc/{symbol}")
async def get_ohlc(
    request: Request,
    symbol: str,
    tf: str = Query("1d", description="Timeframe: 5m, 15m, 1h, 4h, 1d, 1wk"),
):
    """Return OHLC + EMA data for a given timeframe (lightweight, no analysis)."""
    if tf not in _TF_CONFIG:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {tf}. Use: {', '.join(_TF_CONFIG)}")

    yf_period, yf_interval = _TF_CONFIG[tf]

    def _fetch():
        import yfinance as yf
        import pandas as pd
        import pandas_ta as ta

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=yf_period, interval=yf_interval)
        if df is None or df.empty:
            return None

        # Build OHLC
        ohlc = []
        for idx, row in df.iterrows():
            if yf_interval in ("1d", "1wk") or tf in ("1d", "1wk"):
                t = idx.strftime("%Y-%m-%d")
            else:
                t = int(idx.timestamp())
            ohlc.append({
                "time": t,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            })

        # EMA overlays
        ema20 = ta.ema(df["Close"], length=20)
        ema50 = ta.ema(df["Close"], length=50)

        def _ema_list(series):
            if series is None:
                return []
            out = []
            for idx, val in series.dropna().items():
                if yf_interval in ("1d", "1wk") or tf in ("1d", "1wk"):
                    t = idx.strftime("%Y-%m-%d")
                else:
                    t = int(idx.timestamp())
                out.append({"time": t, "value": round(float(val), 2)})
            return out

        current = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else current
        change_pct = ((current - prev) / prev * 100) if prev else 0

        return {
            "ohlc": ohlc,
            "ema20": _ema_list(ema20),
            "ema50": _ema_list(ema50),
            "price": current,
            "change_pct": round(change_pct, 4),
            "tf": tf,
            "bars": len(ohlc),
        }

    try:
        result = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if result is None:
        raise HTTPException(status_code=502, detail=f"No data for {symbol} on {tf}")

    return result


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


@router.get("/screening")
@limiter.limit(ANALYSIS_RATE)
async def screening(request: Request):
    """Run analysis on all 8 ETFs and return ranked BUY/HOLD/SELL classification."""
    config = request.app.state.config
    assets = await get_all_assets(request.app.state.session_factory)

    from app.services.signal_detector import check_entry_conditions

    tasks = [
        analyze_single_asset(symbol=a["symbol"], config=config, asset=a)
        for a in assets
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    screening_results = []
    for asset, result in zip(assets, results):
        if isinstance(result, Exception):
            screening_results.append({
                "symbol": asset["symbol"],
                "display_name": asset.get("display_name", asset["symbol"]),
                "classification": "ERROR",
                "error": str(result),
            })
            continue

        regime = result.get("regime", "NEUTRAL")
        setup = result.get("setup", {})
        detection = check_entry_conditions(result)

        if detection.fired and regime == "LONG":
            classification = "BUY"
        elif regime in ("SHORT", "BEARISH"):
            classification = "SELL_IF_HOLDING"
        else:
            classification = "HOLD"

        screening_results.append({
            "symbol": result.get("symbol"),
            "display_name": result.get("display_name"),
            "classification": classification,
            "regime": regime,
            "quality_score": setup.get("quality_score", 0),
            "entry_price": setup.get("entry_price"),
            "stop_loss": setup.get("stop_loss"),
            "take_profit": setup.get("take_profit"),
            "risk_reward": setup.get("risk_reward"),
        })

    # Sort: BUY first (by QS desc), then HOLD, then SELL
    order = {"BUY": 0, "HOLD": 1, "SELL_IF_HOLDING": 2, "ERROR": 3}
    screening_results.sort(
        key=lambda x: (order.get(x["classification"], 9), -x.get("quality_score", 0))
    )

    return {"screening": screening_results}
