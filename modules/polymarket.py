"""Polymarket module — prediction market signal (v2).

Queries the public Polymarket API to obtain probabilities of macro,
Fed, geopolitical, and crypto events, and computes a directional
signal to use as a third confirmation in the trading pipeline.

v2 improvements:
- Fixed probability inversion: accounts for BOTH sides of each market
- Temporal decay: markets resolving sooner weighted more heavily
- Impact magnitude: LLM scores each event's market impact (1-5)
- Proper net directional score per market
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from modules.keywords import BEARISH_EVENT_KEYWORDS, BULLISH_EVENT_KEYWORDS

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
MARKETS_PER_PAGE = 100
MAX_PAGES = 3  # Fetch up to 300 markets per tag

# ---------------------------------------------------------------------------
# Tag mapping per asset class
# ---------------------------------------------------------------------------
_ASSET_TAG_MAP: dict[str, list[str]] = {
    "NQ": ["economics", "politics"],
    "NAS": ["economics", "politics"],
    "IXIC": ["economics", "politics"],
    "ES": ["economics", "politics"],
    "SPX": ["economics", "politics"],
    "GSPC": ["economics", "politics"],
    "EUR": ["economics", "politics"],
    "GC": ["economics", "politics"],
    "GOLD": ["economics", "politics"],
}

_DEFAULT_TAGS = ["economics", "politics"]

# ---------------------------------------------------------------------------
# Category classification keywords
# ---------------------------------------------------------------------------
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("FED", ["fed", "federal reserve", "rate", "fomc", "interest", "inflation", "cpi"]),
    ("MACRO", ["recession", "gdp", "unemployment", "economy", "growth", "debt", "default"]),
    ("GEOPOLITICAL", ["war", "russia", "china", "ukraine", "iran", "israel", "nato", "conflict", "tariff", "trade"]),
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


def _get_tags_for_assets(assets: list[dict[str, str]]) -> list[str]:
    """Derive Polymarket API tags from configured assets."""
    tags: list[str] = []
    for asset in assets:
        symbol = asset.get("symbol", "").upper()
        display_name = asset.get("display_name", "").lower()
        matched = False
        for key, asset_tags in _ASSET_TAG_MAP.items():
            if key in symbol or key.lower() in display_name:
                tags.extend(asset_tags)
                matched = True
                break
        if not matched:
            tags.extend(_DEFAULT_TAGS)
    return list(dict.fromkeys(tags))


def _get_keywords_for_assets(assets: list[dict[str, str]]) -> list[str]:
    """Build keyword list based on configured assets for client-side filtering."""
    keywords: list[str] = []
    for asset in assets:
        symbol = asset.get("symbol", "").upper()
        display_name = asset.get("display_name", "").lower()

        if any(s in symbol for s in ("NQ", "NAS", "IXIC")):
            keywords.extend(["fed", "recession", "rate", "inflation", "nasdaq",
                             "sp500", "economy", "tariff", "trade"])
        elif any(s in symbol for s in ("ES", "SPX", "GSPC")):
            keywords.extend(["fed", "recession", "rate", "inflation", "nasdaq",
                             "sp500", "economy", "tariff", "trade"])
        elif "EUR" in symbol:
            keywords.extend(["ecb", "euro", "federal reserve", "europe",
                             "dollar", "tariff"])
        elif "GC" in symbol or "gold" in display_name:
            keywords.extend(["gold", "inflation", "fed", "geopolitical",
                             "war", "tariff"])
        else:
            keywords.extend(["recession", "fed", "economy", "market"])

    return list(dict.fromkeys(keywords))


# ---------------------------------------------------------------------------
# API fetching with pagination and tag support
# ---------------------------------------------------------------------------

def _fetch_page(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch a single page from the Gamma API with retry."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                f"{GAMMA_API_BASE}/markets",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning(
                "Polymarket API error (attempt %d/%d): %s",
                attempt, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                logger.warning(
                    "Polymarket API unreachable after %d attempts",
                    MAX_RETRIES,
                )
                return []
    return []


def fetch_markets(
    keywords: list[str],
    min_volume_usd: float = 10_000,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch Polymarket markets with pagination, tag and keyword filtering.

    Args:
        keywords: Keywords to filter markets (client-side).
        min_volume_usd: Minimum USD volume to consider a market.
        tags: API tags for server-side filtering (e.g. "economics", "politics").

    Returns:
        List of filtered markets, sorted by descending volume (max 20).
    """
    all_raw_markets: list[dict[str, Any]] = []
    tag_list = tags if tags else [None]

    for tag in tag_list:
        for page in range(MAX_PAGES):
            offset = page * MARKETS_PER_PAGE
            params: dict[str, Any] = {
                "limit": MARKETS_PER_PAGE,
                "offset": offset,
                "active": "true",
                "closed": "false",
                "order": "volume",
                "ascending": "false",
            }
            if tag:
                params["tag"] = tag

            fetched = _fetch_page(params)
            if not fetched:
                break
            all_raw_markets.extend(fetched)
            if len(fetched) < MARKETS_PER_PAGE:
                break  # Last page

    # Deduplicate by question text
    seen_questions: set[str] = set()
    unique_markets: list[dict[str, Any]] = []
    for market in all_raw_markets:
        q = market.get("question", "")
        if q and q not in seen_questions:
            seen_questions.add(q)
            unique_markets.append(market)

    logger.info(
        "Polymarket: %d raw -> %d unique after dedup",
        len(all_raw_markets), len(unique_markets),
    )

    # Client-side keyword filtering and parsing
    results: list[dict[str, Any]] = []
    for market in unique_markets:
        question = market.get("question", "")
        q_lower = question.lower()

        if not any(kw.lower() in q_lower for kw in keywords):
            continue

        try:
            volume = float(market.get("volume", 0) or 0)
        except (ValueError, TypeError):
            volume = 0.0

        if volume < min_volume_usd:
            continue

        try:
            outcome_prices_raw = market.get("outcomePrices", "[]")
            if isinstance(outcome_prices_raw, str):
                outcome_prices = json.loads(outcome_prices_raw)
            else:
                outcome_prices = outcome_prices_raw

            prob_yes = round(float(outcome_prices[0]) * 100, 1) if len(outcome_prices) > 0 else 50.0
            prob_no = round(float(outcome_prices[1]) * 100, 1) if len(outcome_prices) > 1 else round(100 - prob_yes, 1)
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            prob_yes = 50.0
            prob_no = 50.0

        slug = market.get("slug", "")
        url = f"https://polymarket.com/event/{slug}" if slug else ""
        end_date = market.get("endDate", "") or ""

        results.append({
            "question": question,
            "prob_yes": prob_yes,
            "prob_no": prob_no,
            "volume_usd": volume,
            "end_date": end_date,
            "url": url,
            "category": _classify_category(question),
        })

    results.sort(key=lambda m: m["volume_usd"], reverse=True)
    return results[:20]


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

def _keyword_classify_single(question: str) -> str:
    """Classify a single market question using keywords (fallback)."""
    q_lower = question.lower()
    is_bearish = any(kw in q_lower for kw in BEARISH_EVENT_KEYWORDS)
    is_bullish = any(kw in q_lower for kw in BULLISH_EVENT_KEYWORDS)

    if is_bullish and not is_bearish:
        return "BULLISH_IF_YES"
    return "BEARISH_IF_YES"


def _classify_markets_with_keywords(
    markets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fallback: classify all markets using keyword heuristic."""
    for market in markets:
        market["impact"] = _keyword_classify_single(market["question"])
        market.setdefault("impact_magnitude", 3)  # Default magnitude
    return markets


def classify_markets_with_llm(
    markets: list[dict[str, Any]],
    groq_model: str = "llama-3.3-70b-versatile",
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Use Groq LLM to classify markets with direction AND impact magnitude.

    Now returns both impact direction (BULLISH_IF_YES/BEARISH_IF_YES) and
    impact_magnitude (1-5) for more accurate signal weighting.

    Falls back to keyword-based classification if Groq is unavailable.
    """
    if not markets:
        return markets

    # Pre-populate ALL markets with keyword fallback
    _classify_markets_with_keywords(markets)

    if not api_key:
        api_key = os.environ.get("GROQ_API_KEY", "")

    if not api_key:
        logger.info("No Groq API key — keyword classification for Polymarket")
        return markets

    try:
        from groq import Groq
    except ImportError:
        logger.warning("groq library not installed — keyword classification")
        return markets

    batch = markets[:15]
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
        client = Groq(api_key=api_key)
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
                batch[idx]["impact"] = c.get("impact", batch[idx].get("impact", "BEARISH_IF_YES"))
                batch[idx]["impact_magnitude"] = max(1, min(5, int(c.get("magnitude", 3))))

        logger.info("LLM classified %d Polymarket markets with magnitude", len(batch))
        return markets

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

        weighted_score = score × volume_weight × time_weight × magnitude

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
            impact = _keyword_classify_single(market["question"])

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

    # Directional threshold (±15 for signal, scaling confidence)
    if net_score > 15:
        signal = "BULLISH"
        confidence = min(100.0, 50 + net_score)
    elif net_score < -15:
        signal = "BEARISH"
        confidence = min(100.0, 50 + abs(net_score))
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
    top_markets = sorted(markets, key=lambda m: m["_effective_weight"], reverse=True)[:5]
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

    Builds tags and keywords based on configured assets, fetches
    Polymarket markets with pagination, classifies with LLM (or keywords),
    and computes the aggregate signal weighted by volume, time and magnitude.
    """
    tags = _get_tags_for_assets(assets)
    keywords = _get_keywords_for_assets(assets)

    logger.info("Polymarket: searching with tags %s, keywords %s", tags, keywords)
    markets = fetch_markets(keywords, tags=tags)

    # Classify with LLM (falls back to keywords if unavailable)
    markets = classify_markets_with_llm(
        markets, groq_model=groq_model, api_key=groq_api_key,
    )

    signal_data = compute_signal(markets)

    logger.info(
        "Polymarket: %d markets analyzed, signal=%s (net=%.1f)",
        signal_data["market_count"],
        signal_data["signal"],
        signal_data["net_score"],
    )

    return signal_data
