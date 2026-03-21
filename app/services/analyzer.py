"""Analysis service — wraps existing modules into async-friendly functions.

All existing modules are synchronous. This service bridges them to the async
FastAPI world via asyncio.to_thread().

Includes an in-memory TTL cache to avoid redundant API calls when the same
asset is analysed within the cache window.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.services.cache import AnalysisCache

logger = logging.getLogger(__name__)

# Module-level cache singleton
_cache = AnalysisCache()


def _run_technicals(asset: dict) -> Any:
    """Run technical analysis for a single asset (sync)."""
    from modules.price_data import analyze_assets

    results = analyze_assets([asset])
    return results[0] if results else None


def _run_news(feeds: list, lookback_hours: int, asset: dict) -> list:
    """Fetch news specifically relevant to a single asset (sync)."""
    from modules.news_fetcher import fetch_news_for_asset

    return fetch_news_for_asset(feeds, lookback_hours, asset=asset)


def _run_news_summary(articles: list, asset: dict) -> list[str]:
    """Summarize news into bullet points (sync)."""
    from modules.news_fetcher import summarize_news_with_llm

    return summarize_news_with_llm(articles, asset=asset)


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


def _build_trade_thesis(
    symbol: str,
    direction: str,
    sentiment: Any,
    tech_result: Any,
    setup: dict,
    calendar_data: Any = None,
) -> dict:
    """Build a structured trade thesis explaining why to enter.

    Returns a dict with:
    - direction: LONG or SHORT
    - entry_reason: why enter at this price
    - key_risk: the primary risk to the trade
    - confluence: list of confirming factors
    - invalidation: what would invalidate the thesis
    """
    # Gather confirming factors
    confluence = []

    # Technical signals
    if tech_result and hasattr(tech_result, "signals"):
        for s in tech_result.signals:
            if s.label == "BULLISH" and s.name in ("RSI", "MACD", "EMA_TREND", "BBANDS", "STOCH"):
                confluence.append(f"{s.name}: {s.detail}")

    # Sentiment
    if sentiment:
        score = getattr(sentiment, "sentiment_score", 0)
        bias = getattr(sentiment, "directional_bias", "NEUTRAL")
        if score > 0:
            drivers = getattr(sentiment, "key_drivers", [])
            confluence.append(f"Sentiment {bias} ({score:+.1f}): {drivers[0] if drivers else '?'}")

    # Key risk
    risk_events = getattr(sentiment, "risk_events", []) if sentiment else []
    calendar_events = []
    if calendar_data:
        for ev in getattr(calendar_data, "high_impact_today", []):
            if getattr(ev, "hours_away", 99) < 6:
                calendar_events.append(f"{ev.title} in {ev.hours_away:.0f}h")

    key_risk = (
        risk_events[0] if risk_events
        else calendar_events[0] if calendar_events
        else "Unexpected macro event or data release"
    )

    # Invalidation
    sl = setup.get("stop_loss")
    invalidation = f"Price hits SL at {sl}" if sl else "Regime flips to opposite direction"

    entry_reason = (
        f"{len(confluence)} technical/sentiment factors align for {direction}. "
        f"Quality score {setup.get('quality_score', '?')}/5."
    )

    return {
        "direction": direction,
        "entry_reason": entry_reason,
        "key_risk": key_risk,
        "confluence": confluence[:5],
        "invalidation": invalidation,
    }


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
        "chart": {
            "ohlc": getattr(analysis, "ohlc_data", None),
            "ema20": getattr(analysis, "ema20_data", None),
            "ema50": getattr(analysis, "ema50_data", None),
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
        "net_score": poly_data.get("net_score", 0),
        "bullish_prob": poly_data.get("bullish_prob", 0),
        "bearish_prob": poly_data.get("bearish_prob", 0),
        "total_volume": poly_data.get("total_volume", 0),
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
    """Compute the entry/SL/TP setup for a single asset.

    Uses the unified strategy module for per-class SL/TP computation
    with adaptive ATR percentile adjustment.
    """
    from modules.data.universe import ASSET_UNIVERSE
    from modules.strategy import compute_sl_tp, is_commission_viable

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

    # LONG-only: only compute entry/SL/TP for LONG regime
    # BEARISH regime = advisory to sell if holding (not a new entry)
    if regime == "LONG":
        direction = "LONG"
    elif regime in ("SHORT", "BEARISH"):
        return {
            "tradeable": False,
            "direction": "SELL_IF_HOLDING",
            "reason": "Regime is bearish — sell if holding",
            "entry_price": price,
            "atr": round(atr_value, 2),
        }
    else:
        return {
            "tradeable": False,
            "reason": f"Regime is {regime}",
            "entry_price": price,
            "atr": round(atr_value, 2),
        }

    # Build ATR series from OHLC data for adaptive computation
    atr_series = None
    if hasattr(analysis, 'ohlc_data') and analysis.ohlc_data and len(analysis.ohlc_data) >= 34:
        try:
            import pandas as _pd
            import pandas_ta as _ta
            ohlc_df = _pd.DataFrame(analysis.ohlc_data)
            if all(c in ohlc_df.columns for c in ('high', 'low', 'close')):
                atr_series = _ta.atr(ohlc_df['high'], ohlc_df['low'], ohlc_df['close'], length=14)
        except Exception:
            pass

    # Determine asset class from universe (ETF default)
    symbol = getattr(analysis, "symbol", "")
    spec = ASSET_UNIVERSE.get(symbol)
    asset_class = spec.asset_class.value if spec else "etf"

    sl_tp = compute_sl_tp(
        atr_value=atr_value,
        atr_series=atr_series,
        asset_class=asset_class,
        adaptive=True,
    )

    # LONG-only: SL below entry, TP above entry
    stop_loss = price - sl_tp.sl_distance
    take_profit = price + sl_tp.tp_distance

    # Commission viability check
    commission_ok = is_commission_viable(
        entry_price=price,
        tp_distance=sl_tp.tp_distance,
    )

    tradeable = (
        quality_score >= 4
        and mtf_alignment == "ALIGNED"
        and commission_ok
    )

    if not tradeable:
        if quality_score < 4:
            reason = f"QS {quality_score} < 4"
        elif mtf_alignment != "ALIGNED":
            reason = f"MTF {mtf_alignment}"
        elif not commission_ok:
            reason = "Expected move below 2x commission"
        else:
            reason = "Unknown"
    else:
        reason = "OK"

    return {
        "direction": direction,
        "entry_price": round(price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "sl_distance": round(sl_tp.sl_distance, 2),
        "tp_distance": round(sl_tp.tp_distance, 2),
        "risk_reward": sl_tp.risk_reward,
        "atr": round(atr_value, 2),
        "atr_percentile": sl_tp.atr_percentile,
        "sl_multiplier": sl_tp.sl_multiplier,
        "quality_score": quality_score,
        "commission_viable": commission_ok,
        "tradeable": tradeable,
        "reason": reason,
    }


def get_cache() -> AnalysisCache:
    """Return the module-level cache singleton (for health checks / stats)."""
    return _cache


async def analyze_single_asset(
    symbol: str,
    config: dict,
    skip_llm: bool = False,
    skip_polymarket: bool = False,
    asset: dict | None = None,
) -> dict:
    """Run the full analysis pipeline for a single asset.

    Returns a structured dict with all analysis results.
    Uses the in-memory cache to skip redundant pipeline stages.
    """
    # Resolve asset dict (from DB or fallback)
    if asset is None:
        assets = config.get("assets", [])
        asset = next(
            (a for a in assets if a["symbol"] == symbol),
            {"symbol": symbol, "display_name": symbol},
        )
    feeds = config.get("rss_feeds", [])
    lookback_hours = config.get("lookback_hours", 16)
    groq_model = config.get("groq_model", "llama-3.3-70b-versatile")

    # Phase 1: Parallel data fetching — check cache first
    cached_tech = _cache.get(symbol, "price")
    cached_news = _cache.get(symbol, "news")
    cached_calendar = _cache.get(symbol, "calendar")

    tech_task = None if cached_tech else asyncio.to_thread(_run_technicals, asset)
    news_task = None if cached_news else asyncio.to_thread(_run_news, feeds, lookback_hours, asset)
    calendar_task = None if cached_calendar else asyncio.to_thread(_run_calendar)

    cached_poly = _cache.get(symbol, "polymarket") if not skip_polymarket else None
    poly_task = None
    if not skip_polymarket and cached_poly is None:
        poly_task = asyncio.to_thread(_run_polymarket, asset, groq_model)

    # Gather non-cached tasks
    tasks = [t for t in [tech_task, news_task, calendar_task, poly_task] if t is not None]
    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    # Rebuild results from cache or fresh fetch
    result_iter = iter(results)

    def _next_or_cache(cached_value, fallback=None):
        if cached_value is not None:
            return cached_value
        try:
            r = next(result_iter)
            return fallback if isinstance(r, Exception) else r
        except StopIteration:
            return fallback

    tech_result = _next_or_cache(cached_tech, None)
    news_result = _next_or_cache(cached_news, [])
    calendar_data = _next_or_cache(cached_calendar, None)
    poly_data = cached_poly if skip_polymarket or cached_poly is not None else _next_or_cache(None, None)

    # Cache fresh results
    if tech_result and cached_tech is None:
        _cache.set(symbol, "price", tech_result)
    if news_result and cached_news is None:
        _cache.set(symbol, "news", news_result)
    if calendar_data and cached_calendar is None:
        _cache.set(symbol, "calendar", calendar_data)
    if poly_data and cached_poly is None and not skip_polymarket:
        _cache.set(symbol, "polymarket", poly_data)

    # Log any exceptions from gather
    for r in results:
        if isinstance(r, Exception):
            logger.error("Pipeline task failed: %s", r)

    # Phase 2: Sentiment analysis (needs news) — check cache
    sentiment = _cache.get(symbol, "sentiment") if not skip_llm else None
    if sentiment is None and not skip_llm and news_result:
        try:
            sentiment = await asyncio.to_thread(
                _run_sentiment, news_result, asset, groq_model, poly_data
            )
            if sentiment:
                _cache.set(symbol, "sentiment", sentiment)
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

    # Phase 7: News summary — extracted from sentiment result (no extra LLM call)
    news_summary = None
    if sentiment and getattr(sentiment, "news_summary", None):
        news_summary = sentiment.news_summary
    elif news_result and not skip_llm:
        # Fallback: separate LLM call if sentiment didn't include summary
        try:
            news_summary = await asyncio.to_thread(
                _run_news_summary, news_result, asset,
            )
        except Exception as exc:
            logger.warning("News summary failed: %s", exc)

    # Phase 8: Generate trade thesis (structured reasoning) — LONG-only
    trade_thesis = None
    if regime == "LONG" and sentiment and tech_result:
        try:
            trade_thesis = _build_trade_thesis(
                symbol=symbol,
                direction=regime,
                sentiment=sentiment,
                tech_result=tech_result,
                setup=setup,
                calendar_data=calendar_data,
            )
        except Exception as exc:
            logger.warning("Trade thesis generation failed: %s", exc)

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
        "trade_thesis": trade_thesis,
        "news_summary": news_summary,
        "news_count": len(news_result),
    }
