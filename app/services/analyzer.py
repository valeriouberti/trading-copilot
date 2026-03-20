"""Analysis service — wraps existing modules into async-friendly functions.

All existing modules are synchronous. This service bridges them to the async
FastAPI world via asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _run_technicals(asset: dict) -> Any:
    """Run technical analysis for a single asset (sync)."""
    from modules.price_data import analyze_assets

    results = analyze_assets([asset])
    return results[0] if results else None


def _run_news(feeds: list, lookback_hours: int, asset: dict) -> list:
    """Fetch news filtered for a single asset (sync)."""
    from modules.news_fetcher import fetch_news

    return fetch_news(feeds, lookback_hours, assets=[asset])


def _run_sentiment(
    news: list, asset: dict, groq_model: str, poly_data: dict | None
) -> Any:
    """Run sentiment analysis for a single asset (sync)."""
    from modules.sentiment import analyze_sentiment

    return analyze_sentiment(news, [asset], groq_model, poly_data=poly_data)


def _run_polymarket(asset: dict, groq_model: str) -> dict | None:
    """Fetch Polymarket context for a single asset (sync)."""
    from modules.polymarket import get_polymarket_context

    return get_polymarket_context([asset], groq_model=groq_model)


def _run_calendar() -> Any:
    """Fetch economic calendar (sync)."""
    from modules.economic_calendar import fetch_calendar

    return fetch_calendar()


def _run_validation(sentiment: Any, news: list, analyses: list) -> Any:
    """Run hallucination guard validation (sync)."""
    from modules.hallucination_guard import validate

    return validate(sentiment, news, analyses)


def _run_poly_validation(
    sentiment: Any, poly_data: dict | None, analyses: list
) -> list[str]:
    """Run Polymarket consistency validation (sync)."""
    from modules.hallucination_guard import validate_polymarket_consistency

    return validate_polymarket_consistency(sentiment, poly_data, analyses)


def _run_regime(
    sentiment: Any, analyses: list, flags: list[str]
) -> tuple[str, str]:
    """Determine daily regime (sync)."""
    from modules.hallucination_guard import determine_regime

    return determine_regime(sentiment, analyses, flags)


def _run_correlation(analyses: list) -> tuple[Any, list[str]]:
    """Compute correlation matrix and filter (sync)."""
    from modules.price_data import (
        compute_correlation_matrix,
        filter_correlated_assets,
    )

    matrix = compute_correlation_matrix(analyses)
    filtered = filter_correlated_assets(analyses, matrix)
    return matrix, filtered


def _format_signal(signal: Any) -> dict:
    """Convert a TechnicalSignal to a JSON-friendly dict."""
    return {
        "name": signal.name,
        "value": signal.value,
        "label": signal.label,
        "detail": signal.detail,
    }


def _format_analysis(analysis: Any) -> dict:
    """Convert an AssetAnalysis to a structured dict for the API."""
    if analysis is None or getattr(analysis, "error", True):
        return {
            "error": getattr(analysis, "error", "Analysis failed") if analysis else "No data",
        }

    signals_dict = {}
    for s in (analysis.signals or []):
        signals_dict[s.name.lower().replace(" ", "_")] = _format_signal(s)

    key_levels = analysis.key_levels.to_dict() if analysis.key_levels else None
    mtf = analysis.mtf.to_dict() if analysis.mtf else None
    qs = analysis.quality_score.to_dict() if analysis.quality_score else None

    return {
        "symbol": analysis.symbol,
        "display_name": analysis.display_name,
        "price": {
            "current": analysis.price,
            "change_pct": analysis.change_pct,
            "data_source": analysis.data_source,
        },
        "technicals": {
            "composite_score": analysis.composite_score,
            "confidence_pct": analysis.confidence_pct,
            "signals": signals_dict,
            "key_levels": key_levels,
            "mtf": mtf,
            "quality_score": qs,
        },
    }


def _format_sentiment(sentiment: Any) -> dict:
    """Convert a SentimentResult to a structured dict."""
    if sentiment is None:
        return {"error": "No sentiment data"}

    return {
        "score": sentiment.sentiment_score,
        "label": sentiment.sentiment_label,
        "bias": sentiment.directional_bias,
        "confidence": sentiment.confidence,
        "key_drivers": sentiment.key_drivers,
        "risk_events": getattr(sentiment, "risk_events", []),
        "source": sentiment.source,
        "asset_biases": getattr(sentiment, "asset_biases", {}),
    }


def _format_polymarket(poly_data: dict | None) -> dict | None:
    """Format Polymarket data for the API."""
    if not poly_data:
        return None

    return {
        "signal": poly_data.get("signal", "N/A"),
        "confidence": poly_data.get("confidence", 0),
        "market_count": poly_data.get("market_count", 0),
        "top_markets": poly_data.get("top_markets", [])[:5],
    }


def _format_calendar(calendar_data: Any) -> dict | None:
    """Format calendar data for the API."""
    if not calendar_data:
        return None

    events = []
    for ev in getattr(calendar_data, "high_impact_today", []):
        events.append({
            "title": ev.title,
            "country": ev.country,
            "datetime_utc": str(ev.datetime_utc) if ev.datetime_utc else None,
            "impact": ev.impact,
            "forecast": ev.forecast,
            "previous": ev.previous,
            "hours_away": round(ev.hours_away, 1) if ev.hours_away is not None else None,
        })

    return {
        "events_today": events,
        "regime_override": getattr(calendar_data, "regime_override", False),
        "override_reason": getattr(calendar_data, "override_reason", ""),
    }


def _compute_setup(
    analysis: Any,
    sentiment: Any,
    regime: str,
    quality_score: int,
    mtf_alignment: str | None,
) -> dict:
    """Compute the entry/SL/TP setup for a single asset."""
    if analysis is None or getattr(analysis, "error", True):
        return {"tradeable": False, "reason": "No technical data"}

    price = analysis.price
    if not price or price <= 0:
        return {"tradeable": False, "reason": "Invalid price"}

    # Find ATR from signals
    atr_value = None
    for s in (analysis.signals or []):
        if s.name == "ATR":
            atr_value = s.value
            break

    if not atr_value or atr_value <= 0:
        return {"tradeable": False, "reason": "No ATR data"}

    direction = regime if regime in ("LONG", "SHORT") else None
    if not direction:
        return {
            "tradeable": False,
            "reason": f"Regime is {regime}",
            "entry_price": price,
            "atr": round(atr_value, 2),
        }

    sl_distance = atr_value * 1.5
    tp_distance = sl_distance * 2.0

    if direction == "LONG":
        stop_loss = price - sl_distance
        take_profit = price + tp_distance
    else:
        stop_loss = price + sl_distance
        take_profit = price - tp_distance

    tradeable = quality_score >= 4 and (mtf_alignment in ("ALIGNED", None))

    return {
        "direction": direction,
        "entry_price": round(price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "sl_distance": round(sl_distance, 2),
        "tp_distance": round(tp_distance, 2),
        "risk_reward": "1:2.0",
        "atr": round(atr_value, 2),
        "quality_score": quality_score,
        "tradeable": tradeable,
        "reason": "OK" if tradeable else (
            f"QS {quality_score} < 4" if quality_score < 4 else f"MTF {mtf_alignment}"
        ),
    }


async def analyze_single_asset(
    symbol: str,
    config: dict,
    skip_llm: bool = False,
    skip_polymarket: bool = False,
) -> dict:
    """Run the full analysis pipeline for a single asset.

    Returns a structured dict with all analysis results.
    """
    # Find asset in config
    assets = config.get("assets", [])
    asset = next(
        (a for a in assets if a["symbol"] == symbol),
        {"symbol": symbol, "display_name": symbol},
    )
    feeds = config.get("rss_feeds", [])
    lookback_hours = config.get("lookback_hours", 16)
    groq_model = config.get("groq_model", "llama-3.3-70b-versatile")

    # Phase 1: Parallel data fetching
    tech_task = asyncio.to_thread(_run_technicals, asset)
    news_task = asyncio.to_thread(_run_news, feeds, lookback_hours, asset)
    calendar_task = asyncio.to_thread(_run_calendar)

    poly_task = None
    if not skip_polymarket:
        poly_task = asyncio.to_thread(_run_polymarket, asset, groq_model)

    # Gather parallel tasks
    tasks = [tech_task, news_task, calendar_task]
    if poly_task:
        tasks.append(poly_task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Unpack results
    tech_result = results[0] if not isinstance(results[0], Exception) else None
    news_result = results[1] if not isinstance(results[1], Exception) else []
    calendar_data = results[2] if not isinstance(results[2], Exception) else None

    poly_data = None
    if poly_task and len(results) > 3:
        poly_data = results[3] if not isinstance(results[3], Exception) else None

    # Log any exceptions
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("Task %d failed: %s", i, r)

    # Phase 2: Sentiment analysis (needs news)
    sentiment = None
    if not skip_llm and news_result:
        try:
            sentiment = await asyncio.to_thread(
                _run_sentiment, news_result, asset, groq_model, poly_data
            )
        except Exception as exc:
            logger.error("Sentiment analysis failed: %s", exc)

    # Phase 3: Validation
    analyses_list = [tech_result] if tech_result else []
    validation_flags: list[str] = []

    if sentiment and analyses_list:
        try:
            validation = await asyncio.to_thread(
                _run_validation, sentiment, news_result, analyses_list
            )
            validation_flags = list(validation.flags)
        except Exception as exc:
            logger.error("Validation failed: %s", exc)

    # Polymarket consistency
    if sentiment and poly_data:
        try:
            poly_flags = await asyncio.to_thread(
                _run_poly_validation, sentiment, poly_data, analyses_list
            )
            validation_flags.extend(poly_flags)
        except Exception as exc:
            logger.error("Polymarket validation failed: %s", exc)

    # Phase 4: Regime determination
    regime = "NEUTRAL"
    regime_reason = "No data"
    if sentiment:
        try:
            regime, regime_reason = await asyncio.to_thread(
                _run_regime, sentiment, analyses_list, validation_flags
            )
        except Exception as exc:
            logger.error("Regime determination failed: %s", exc)

    # Calendar override
    if calendar_data and getattr(calendar_data, "regime_override", False):
        if regime != "NEUTRAL":
            original = regime
            regime = "NEUTRAL"
            regime_reason = (
                f"{calendar_data.override_reason} (was {original}: {regime_reason})"
            )

    # Phase 5: Correlation (single asset — informational only)
    corr_matrix = None
    filtered_symbols: list[str] = []

    # Phase 6: Format response
    qs = 0
    mtf_align = None
    if tech_result and not getattr(tech_result, "error", True):
        if tech_result.quality_score:
            qs = tech_result.quality_score.total
        if tech_result.mtf:
            mtf_align = tech_result.mtf.alignment

    setup = _compute_setup(tech_result, sentiment, regime, qs, mtf_align)

    return {
        "symbol": symbol,
        "display_name": asset.get("display_name", symbol),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis": _format_analysis(tech_result),
        "sentiment": _format_sentiment(sentiment) if sentiment else None,
        "polymarket": _format_polymarket(poly_data),
        "calendar": _format_calendar(calendar_data),
        "regime": regime,
        "regime_reason": regime_reason,
        "validation_flags": validation_flags,
        "setup": setup,
        "news_count": len(news_result),
    }
