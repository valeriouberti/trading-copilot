"""Polymarket module — prediction market signal (v3).

Queries the Polymarket Gamma API /events endpoint with curated
tag_slugs to obtain probabilities of macro, Fed, geopolitical,
and commodity events, and computes a directional signal to use
as a third confirmation in the trading pipeline.

v3 improvements over v2:
- Uses /events endpoint with tag_slug for accurate server-side filtering
  (the /markets endpoint ignores tag filters entirely)
- Curated tag_slug mapping per asset class (fed, gdp, tariffs, gold, etc.)
- Category gate rejects non-financial markets (OTHER)
- Extracts markets from nested event responses

v2 improvements (retained):
- Fixed probability inversion: accounts for BOTH sides of each market
- Temporal decay: markets resolving sooner weighted more heavily
- Impact magnitude: LLM scores each event's market impact (1-5)
- Proper net directional score per market
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any

import requests

from modules.exceptions import ExternalAPITransient, LLMResponseInvalid
from modules.groq_client import get_groq_client
from modules.keywords import BEARISH_EVENT_KEYWORDS, BULLISH_EVENT_KEYWORDS
from modules.retry import retry_external_api

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

MAX_RETRIES = 3
EVENTS_PER_TAG = 20  # Max events per tag_slug query
MAX_MARKETS = 20  # Final cap on returned markets

# ---------------------------------------------------------------------------
# Tag-slug mapping per asset class
# ---------------------------------------------------------------------------
# These map to real Polymarket tag_slugs on the /events endpoint.
_ASSET_TAG_SLUGS: list[tuple[str, list[str]]] = [
    # Order matters: longer/more specific keys first to avoid substring false matches
    # (e.g. "ES" in "futures" would wrongly match Gold Futures)
    (
        "IXIC",
        [
            "fed",
            "inflation",
            "gdp",
            "unemployment",
            "tariffs",
            "stocks",
            "economy",
            "geopolitics",
        ],
    ),
    (
        "NAS",
        [
            "fed",
            "inflation",
            "gdp",
            "unemployment",
            "tariffs",
            "stocks",
            "economy",
            "geopolitics",
        ],
    ),
    (
        "NQ",
        [
            "fed",
            "inflation",
            "gdp",
            "unemployment",
            "tariffs",
            "stocks",
            "economy",
            "geopolitics",
        ],
    ),
    (
        "GSPC",
        [
            "fed",
            "inflation",
            "gdp",
            "unemployment",
            "tariffs",
            "stocks",
            "economy",
            "geopolitics",
        ],
    ),
    (
        "SPX",
        [
            "fed",
            "inflation",
            "gdp",
            "unemployment",
            "tariffs",
            "stocks",
            "economy",
            "geopolitics",
        ],
    ),
    ("GOLD", ["gold", "commodities", "geopolitics", "fed", "inflation", "oil"]),
    ("GC", ["gold", "commodities", "geopolitics", "fed", "inflation", "oil"]),
    ("OIL", ["oil", "commodities", "geopolitics", "fed"]),
    ("CL", ["oil", "commodities", "geopolitics", "fed"]),
    (
        "EUR",
        ["fed", "inflation", "interest-rates", "economy", "tariffs", "geopolitics"],
    ),
    (
        "ES",
        [
            "fed",
            "inflation",
            "gdp",
            "unemployment",
            "tariffs",
            "stocks",
            "economy",
            "geopolitics",
        ],
    ),
]

_DEFAULT_TAG_SLUGS = ["fed", "inflation", "gdp", "economy", "geopolitics", "tariffs"]

# ---------------------------------------------------------------------------
# Category classification keywords
# ---------------------------------------------------------------------------
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    (
        "FED",
        [
            "fed",
            "federal reserve",
            "rate hike",
            "rate cut",
            "fomc",
            "interest rate",
            "inflation",
            "cpi",
            "monetary policy",
            "powell",
        ],
    ),
    (
        "MACRO",
        [
            "recession",
            "gdp",
            "unemployment",
            "jobs",
            "nonfarm",
            "economy",
            "growth",
            "debt",
            "default",
            "fiscal",
            "treasury",
            "s&p",
            "sp500",
            "nasdaq",
            "stock market",
            "bear market",
            "bull market",
            "negative gdp",
            "company",
            "nvidia",
            "tesla",
            "apple",
            "google",
            "amazon",
            "microsoft",
        ],
    ),
    (
        "COMMODITY",
        [
            "gold",
            "silver",
            "crude oil",
            "oil",
            "commodity",
            "commodities",
            "natural gas",
        ],
    ),
    (
        "GEOPOLITICAL",
        [
            "war",
            "russia",
            "china",
            "ukraine",
            "iran",
            "israel",
            "nato",
            "conflict",
            "tariff",
            "sanctions",
            "trade war",
            "invasion",
            "military",
            "ceasefire",
            "hormuz",
        ],
    ),
    ("CRYPTO", ["bitcoin", "btc", "eth", "crypto", "coinbase"]),
]


def _classify_category(question: str) -> str:
    """Classify the market question into a thematic category."""
    q_lower = question.lower()
    for category, keywords in _CATEGORY_RULES:
        for kw in keywords:
            if kw in q_lower:
                return category
    return "OTHER"


def _get_tag_slugs_for_assets(assets: list[dict[str, str]]) -> list[str]:
    """Derive Polymarket /events tag_slugs from configured assets."""
    slugs: list[str] = []
    for asset in assets:
        symbol = asset.get("symbol", "").upper()
        # Match on symbol only (not display_name) to avoid substring issues
        # e.g. "ES" matching "Gold Futures" via "futurES"
        matched = False
        for key, tag_slugs in _ASSET_TAG_SLUGS:
            if key in symbol:
                slugs.extend(tag_slugs)
                matched = True
                break
        if not matched:
            slugs.extend(_DEFAULT_TAG_SLUGS)
    return list(dict.fromkeys(slugs))


# Keep for backward compatibility with tests
def _get_tags_for_assets(assets: list[dict[str, str]]) -> list[str]:
    """Derive Polymarket API tag_slugs from configured assets."""
    return _get_tag_slugs_for_assets(assets)


def _get_keywords_for_assets(assets: list[dict[str, str]]) -> list[str]:
    """Build keyword list based on configured assets for client-side filtering.

    Used only as a secondary safety net — the /events tag_slug endpoint
    already provides good server-side filtering.
    """
    keywords: list[str] = []
    for asset in assets:
        symbol = asset.get("symbol", "").upper()
        display_name = asset.get("display_name", "").lower()

        if any(s in symbol for s in ("NQ", "NAS", "IXIC")):
            keywords.extend(
                [
                    "federal reserve",
                    "fed rate",
                    "fomc",
                    "recession",
                    "inflation",
                    "cpi",
                    "nasdaq",
                    "s&p 500",
                    "sp500",
                    "gdp",
                    "unemployment",
                    "tariff",
                    "trade war",
                    "interest rate",
                ]
            )
        elif any(s in symbol for s in ("ES", "SPX", "GSPC")):
            keywords.extend(
                [
                    "federal reserve",
                    "fed rate",
                    "fomc",
                    "recession",
                    "inflation",
                    "cpi",
                    "s&p 500",
                    "sp500",
                    "gdp",
                    "unemployment",
                    "tariff",
                    "trade war",
                    "interest rate",
                ]
            )
        elif "EUR" in symbol:
            keywords.extend(
                [
                    "ecb",
                    "euro",
                    "federal reserve",
                    "eurozone",
                    "dollar",
                    "tariff",
                    "interest rate",
                ]
            )
        elif "GC" in symbol or "gold" in display_name:
            keywords.extend(
                [
                    "gold",
                    "inflation",
                    "federal reserve",
                    "geopolitical",
                    "war",
                    "tariff",
                    "interest rate",
                ]
            )
        else:
            keywords.extend(
                ["recession", "federal reserve", "gdp", "interest rate", "inflation"]
            )

    return list(dict.fromkeys(keywords))


# ---------------------------------------------------------------------------
# API fetching via /events endpoint
# ---------------------------------------------------------------------------


def _fetch_events(tag_slug: str) -> list[dict[str, Any]]:
    """Fetch events from the Gamma /events endpoint with retry."""
    params: dict[str, Any] = {
        "limit": EVENTS_PER_TAG,
        "active": "true",
        "closed": "false",
        "tag_slug": tag_slug,
        "order": "volume",
        "ascending": "false",
    }
    try:
        return _fetch_events_with_retry(params)
    except ExternalAPITransient:
        logger.warning("Polymarket API unreachable for tag_slug=%s", tag_slug)
        return []


@retry_external_api(max_attempts=MAX_RETRIES)
def _fetch_events_with_retry(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Inner retry-wrapped fetch for Polymarket events."""
    try:
        resp = requests.get(
            f"{GAMMA_API_BASE}/events",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ExternalAPITransient(
            service="polymarket",
            detail=str(exc),
        ) from exc


def _parse_market(market_raw: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a raw market dict from the API into our standard format.

    Returns None if the market should be skipped (OTHER category,
    missing data, etc.).
    """
    question = market_raw.get("question", "")
    if not question:
        return None

    category = _classify_category(question)
    if category == "OTHER":
        return None

    try:
        volume = float(market_raw.get("volume", 0) or 0)
    except (ValueError, TypeError):
        volume = 0.0

    try:
        outcome_prices_raw = market_raw.get("outcomePrices", "[]")
        if isinstance(outcome_prices_raw, str):
            outcome_prices = json.loads(outcome_prices_raw)
        else:
            outcome_prices = outcome_prices_raw

        prob_yes = (
            round(float(outcome_prices[0]) * 100, 1)
            if len(outcome_prices) > 0
            else 50.0
        )
        prob_no = (
            round(float(outcome_prices[1]) * 100, 1)
            if len(outcome_prices) > 1
            else round(100 - prob_yes, 1)
        )
    except (ValueError, TypeError, IndexError, json.JSONDecodeError):
        prob_yes = 50.0
        prob_no = 50.0

    slug = market_raw.get("slug", "")
    url = f"https://polymarket.com/event/{slug}" if slug else ""
    end_date = market_raw.get("endDate", "") or ""

    return {
        "question": question,
        "prob_yes": prob_yes,
        "prob_no": prob_no,
        "volume_usd": volume,
        "end_date": end_date,
        "url": url,
        "category": category,
    }


def fetch_markets(
    keywords: list[str] | None = None,
    min_volume_usd: float = 0,
    tags: list[str] | None = None,
    *,
    tag_slugs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch Polymarket markets via the /events endpoint with tag_slug filtering.

    Primary approach: queries /events with each tag_slug, extracts nested
    markets, deduplicates, classifies by category, and rejects non-financial.

    Args:
        keywords: Optional keywords for additional client-side filtering.
        min_volume_usd: Minimum USD volume to consider a market.
        tags: Alias for tag_slugs (backward compatibility).
        tag_slugs: Tag slugs for the /events endpoint
                   (e.g. "fed", "gdp", "tariffs").

    Returns:
        List of filtered markets, sorted by descending volume (max 20).
    """
    slug_list = tag_slugs or tags or []
    if not slug_list:
        slug_list = list(_DEFAULT_TAG_SLUGS)

    # Fetch events from all tag_slugs
    all_raw_markets: list[dict[str, Any]] = []
    for slug in slug_list:
        events = _fetch_events(slug)
        for event in events:
            # Events contain nested markets
            nested = event.get("markets", [])
            if nested:
                all_raw_markets.extend(nested)
            else:
                # Some endpoints return flat market objects
                all_raw_markets.append(event)

    # Deduplicate by question text
    seen_questions: set[str] = set()
    unique_markets: list[dict[str, Any]] = []
    for market_raw in all_raw_markets:
        q = market_raw.get("question", "")
        if q and q not in seen_questions:
            seen_questions.add(q)
            unique_markets.append(market_raw)

    logger.info(
        "Polymarket: %d raw -> %d unique after dedup",
        len(all_raw_markets),
        len(unique_markets),
    )

    # Parse, classify, and filter
    results: list[dict[str, Any]] = []
    for market_raw in unique_markets:
        parsed = _parse_market(market_raw)
        if parsed is None:
            continue

        if parsed["volume_usd"] < min_volume_usd:
            continue

        # Optional keyword filter (secondary safety net)
        if keywords:
            q_lower = parsed["question"].lower()
            if not any(kw.lower() in q_lower for kw in keywords):
                continue

        results.append(parsed)

    results.sort(key=lambda m: m["volume_usd"], reverse=True)

    logger.info(
        "Polymarket: %d markets after filtering (from %d unique)",
        min(len(results), MAX_MARKETS),
        len(unique_markets),
    )

    return results[:MAX_MARKETS]


# ---------------------------------------------------------------------------
# Temporal decay
# ---------------------------------------------------------------------------


def _compute_time_weight(end_date_str: str) -> float:
    """Compute temporal decay weight based on market resolution date.

    Markets resolving sooner are more relevant for day-trading decisions.
    Uses a 2-week half-life: a market resolving today has weight ~1.0,
    one resolving in 14 days has weight ~0.5.
    """
    if not end_date_str:
        return 0.5  # Unknown end date gets moderate weight

    try:
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_to_resolution = max(0, (end_date - now).days)
        return 1.0 / (1.0 + days_to_resolution / 14.0)
    except (ValueError, TypeError):
        return 0.5


# ---------------------------------------------------------------------------
# LLM-based classification with impact magnitude
# ---------------------------------------------------------------------------


def _keyword_classify_single(question: str) -> tuple[str, bool]:
    """Classify a single market question using keywords.

    Returns (impact, is_ambiguous) where is_ambiguous=True when both
    bullish and bearish keywords match, or neither matches.
    """
    q_lower = question.lower()
    is_bearish = any(kw in q_lower for kw in BEARISH_EVENT_KEYWORDS)
    is_bullish = any(kw in q_lower for kw in BULLISH_EVENT_KEYWORDS)

    ambiguous = (is_bullish == is_bearish)  # Both True or both False
    if is_bullish and not is_bearish:
        return "BULLISH_IF_YES", False
    return "BEARISH_IF_YES", ambiguous


def _classify_markets_with_keywords(
    markets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify all markets using keyword heuristic. Flags ambiguous ones."""
    for market in markets:
        impact, ambiguous = _keyword_classify_single(market["question"])
        market["impact"] = impact
        market["_ambiguous"] = ambiguous
        market.setdefault("impact_magnitude", 3)  # Default magnitude
    return markets


def classify_markets_with_llm(
    markets: list[dict[str, Any]],
    groq_model: str = "llama-3.3-70b-versatile",
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Use Groq LLM to classify markets with direction AND impact magnitude.

    Only sends ambiguous markets (where keyword heuristic is uncertain) to
    the LLM — clear bullish/bearish keyword matches are kept as-is.

    Falls back to keyword-based classification if Groq is unavailable.
    """
    if not markets:
        return markets

    # Pre-populate ALL markets with keyword fallback
    _classify_markets_with_keywords(markets)

    # Only send ambiguous markets to LLM
    ambiguous = [m for m in markets if m.get("_ambiguous", False)]
    if not ambiguous:
        logger.info("No ambiguous markets — keyword classification sufficient")
        return markets

    if not api_key:
        api_key = os.environ.get("GROQ_API_KEY", "")

    if not api_key:
        logger.info("No Groq API key — keyword classification for Polymarket")
        return markets

    client = get_groq_client(api_key)
    if client is None:
        logger.warning("Groq client unavailable — keyword classification")
        return markets

    batch = ambiguous[:15]
    questions_block = "\n".join(
        f"{i + 1}. {m['question']} (prob YES: {m['prob_yes']:.0f}%)"
        for i, m in enumerate(batch)
    )

    prompt = f"""Classify each prediction market with TWO criteria:
1. impact: if the YES event occurs, is it BULLISH or BEARISH for markets?
2. magnitude: how market-moving is this event? (1-5)

MAGNITUDE SCALE:
1 = marginal (minor politics, local event)
2 = minor (legislative bill, appointment)
3 = moderate (economic data, trade tensions)
4 = significant (Fed decisions, employment data, CPI)
5 = market-moving (banking crisis, war, surprise rate cut/hike)

MARKETS:
{questions_block}

Respond EXCLUSIVELY with a JSON array (no markdown, no ```):
[
  {{"index": 1, "impact": "BULLISH_IF_YES", "magnitude": 4}},
  {{"index": 2, "impact": "BEARISH_IF_YES", "magnitude": 3}},
  ...
]

Rules:
- impact: "BULLISH_IF_YES" or "BEARISH_IF_YES"
- magnitude: integer from 1 to 5
- "Fed cuts rates" -> BULLISH_IF_YES, magnitude 5
- "US recession" -> BEARISH_IF_YES, magnitude 5
- "US avoids recession" -> BULLISH_IF_YES, magnitude 4
- "New semiconductor tariff" -> BEARISH_IF_YES, magnitude 3
- Respond ONLY with the JSON"""

    try:
        response = client.chat.completions.create(
            model=groq_model,
            messages=[
                {
                    "role": "system",
                    "content": "Classify events as bullish/bearish for markets "
                    "and assign an impact score 1-5. Respond only in JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        classifications = json.loads(raw)

        for c in classifications:
            idx = c.get("index", 0) - 1
            if 0 <= idx < len(batch):
                batch[idx]["impact"] = c.get(
                    "impact", batch[idx].get("impact", "BEARISH_IF_YES")
                )
                batch[idx]["impact_magnitude"] = max(
                    1, min(5, int(c.get("magnitude", 3)))
                )
                batch[idx]["_ambiguous"] = False  # Resolved by LLM

        logger.info(
            "LLM classified %d/%d ambiguous Polymarket markets",
            len(batch), len(markets),
        )
        return markets

    except (LLMResponseInvalid, json.JSONDecodeError) as exc:
        logger.warning("LLM classification response invalid: %s", exc)
        return markets  # Already pre-populated
    except Exception as exc:
        logger.warning("LLM classification failed, using keyword fallback: %s", exc)
        return markets  # Already pre-populated


# ---------------------------------------------------------------------------
# Signal computation v2 — fixed probability interpretation
# ---------------------------------------------------------------------------


def compute_signal(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the aggregate directional signal (v2).

    v2 fixes:
    - Accounts for BOTH sides of each market (YES and NO probabilities)
    - Temporal decay: markets resolving sooner weighted more
    - Impact magnitude: higher-impact events contribute more
    - Net directional score: positive = bullish, negative = bearish

    Formula per market:
        If BEARISH_IF_YES:  score = -(prob_yes - 50) / 50   (range: -1 to +1)
        If BULLISH_IF_YES:  score = +(prob_yes - 50) / 50   (range: -1 to +1)

        weighted_score = score x volume_weight x time_weight x magnitude

    Args:
        markets: List of markets with fields 'impact' and 'impact_magnitude'.

    Returns:
        Dict with signal, confidence, scores and top markets.
    """
    if not markets:
        return {
            "signal": "NEUTRAL",
            "confidence": 50.0,
            "net_score": 0.0,
            "bullish_prob": 0.0,
            "bearish_prob": 0.0,
            "top_markets": [],
            "total_volume": 0.0,
            "market_count": 0,
        }

    total_weight = 0.0
    bullish_score = 0.0
    bearish_score = 0.0

    for market in markets:
        prob_yes = market["prob_yes"]
        volume = market["volume_usd"]
        impact = market.get("impact", "")
        magnitude = market.get("impact_magnitude", 3)

        if not impact:
            impact, _ = _keyword_classify_single(market["question"])

        # Temporal decay based on resolution date
        time_weight = _compute_time_weight(market.get("end_date", ""))

        # Combined weight
        w = volume * time_weight * magnitude
        total_weight += w

        # Directional contribution — accounts for BOTH sides
        if impact == "BEARISH_IF_YES":
            # prob_yes = chance of bad event happening
            bearish_score += prob_yes * w
            bullish_score += (100 - prob_yes) * w
        elif impact == "BULLISH_IF_YES":
            # prob_yes = chance of good event happening
            bullish_score += prob_yes * w
            bearish_score += (100 - prob_yes) * w

    # Normalize to percentages
    if total_weight > 0:
        bullish_pct = bullish_score / total_weight
        bearish_pct = bearish_score / total_weight
    else:
        bullish_pct = 50.0
        bearish_pct = 50.0

    net_score = bullish_pct - bearish_pct

    # Directional threshold (+/-15 for signal, sigmoid confidence)
    if net_score > 15:
        signal = "BULLISH"
        confidence = 50 + 50 * math.tanh(net_score / 30)
    elif net_score < -15:
        signal = "BEARISH"
        confidence = 50 + 50 * math.tanh(abs(net_score) / 30)
    else:
        signal = "NEUTRAL"
        confidence = 50.0

    confidence = max(0.0, min(100.0, confidence))

    # Sort top markets by effective weight (volume * time * magnitude)
    for m in markets:
        m["_effective_weight"] = (
            m["volume_usd"]
            * _compute_time_weight(m.get("end_date", ""))
            * m.get("impact_magnitude", 3)
        )
    top_markets = sorted(markets, key=lambda m: m["_effective_weight"], reverse=True)[
        :5
    ]
    # Clean up temp field
    for m in markets:
        m.pop("_effective_weight", None)

    raw_volume = sum(m["volume_usd"] for m in markets)

    return {
        "signal": signal,
        "confidence": round(confidence, 1),
        "net_score": round(net_score, 1),
        "bullish_prob": round(bullish_pct, 1),
        "bearish_prob": round(bearish_pct, 1),
        "top_markets": top_markets,
        "total_volume": round(raw_volume, 2),
        "market_count": len(markets),
    }


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------


def get_polymarket_context(
    assets: list[dict[str, str]],
    groq_model: str = "llama-3.3-70b-versatile",
    groq_api_key: str | None = None,
) -> dict[str, Any]:
    """High-level function called from main.py.

    Builds tag_slugs based on configured assets, fetches Polymarket
    events via /events endpoint, extracts markets, classifies with
    LLM (or keywords), and computes the aggregate signal.
    """
    tag_slugs = _get_tag_slugs_for_assets(assets)

    logger.info("Polymarket: searching with tag_slugs %s", tag_slugs)
    markets = fetch_markets(tag_slugs=tag_slugs)

    # Classify with LLM (falls back to keywords if unavailable)
    markets = classify_markets_with_llm(
        markets,
        groq_model=groq_model,
        api_key=groq_api_key,
    )

    signal_data = compute_signal(markets)

    logger.info(
        "Polymarket: %d markets analyzed, signal=%s (net=%.1f)",
        signal_data["market_count"],
        signal_data["signal"],
        signal_data["net_score"],
    )

    return signal_data
