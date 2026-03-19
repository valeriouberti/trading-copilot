"""Modulo Polymarket — segnale da mercati predittivi.

Interroga l'API pubblica di Polymarket per ottenere probabilità
di eventi macro, Fed, geopolitici e crypto, e calcola un segnale
direzionale da usare come terza conferma nel pipeline di trading.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# ---------------------------------------------------------------------------
# Category classification keywords
# ---------------------------------------------------------------------------
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("FED", ["fed", "federal reserve", "rate", "fomc", "interest", "inflation", "cpi"]),
    ("MACRO", ["recession", "gdp", "unemployment", "economy", "growth", "debt", "default"]),
    ("GEOPOLITICAL", ["war", "russia", "china", "ukraine", "iran", "israel", "nato", "conflict", "tariff", "trade"]),
    ("CRYPTO", ["bitcoin", "btc", "eth", "crypto", "coinbase"]),
]

# ---------------------------------------------------------------------------
# Bearish / Bullish event classification
# ---------------------------------------------------------------------------
BEARISH_EVENT_KEYWORDS = [
    "recession", "crash", "rate hike", "hawkish", "default",
    "war", "conflict", "tariff", "unemployment rise", "contraction",
]

BULLISH_EVENT_KEYWORDS = [
    "rate cut", "dovish", "soft landing", "growth", "rally",
    "recovery", "expansion",
]


def _classify_category(question: str) -> str:
    """Classifica la domanda del mercato in una categoria tematica."""
    q_lower = question.lower()
    for category, keywords in _CATEGORY_RULES:
        for kw in keywords:
            if kw in q_lower:
                return category
    return "OTHER"


def fetch_markets(
    keywords: list[str],
    min_volume_usd: float = 10_000,
) -> list[dict[str, Any]]:
    """Recupera mercati Polymarket filtrati per parole chiave e volume.

    Args:
        keywords: Lista di parole chiave per filtrare i mercati.
        min_volume_usd: Volume minimo in USD per considerare un mercato.

    Returns:
        Lista di mercati filtrati, ordinati per volume decrescente (max 10).
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                f"{GAMMA_API_BASE}/markets",
                params={"limit": 100, "active": "true", "closed": "false"},
                timeout=15,
            )
            resp.raise_for_status()
            raw_markets = resp.json()
            break
        except Exception as exc:
            logger.warning(
                "Polymarket API errore (tentativo %d/%d): %s",
                attempt, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                logger.warning("Polymarket API non raggiungibile dopo %d tentativi", MAX_RETRIES)
                return []

    results: list[dict[str, Any]] = []
    for market in raw_markets:
        question = market.get("question", "")
        q_lower = question.lower()

        # Filter by keyword match
        if not any(kw.lower() in q_lower for kw in keywords):
            continue

        # Parse volume
        try:
            volume = float(market.get("volume", 0) or 0)
        except (ValueError, TypeError):
            volume = 0.0

        if volume < min_volume_usd:
            continue

        # Parse outcome prices
        try:
            outcome_prices_raw = market.get("outcomePrices", "[]")
            if isinstance(outcome_prices_raw, str):
                # Often stored as JSON string like '["0.55","0.45"]'
                import json
                outcome_prices = json.loads(outcome_prices_raw)
            else:
                outcome_prices = outcome_prices_raw

            prob_yes = round(float(outcome_prices[0]) * 100, 1) if len(outcome_prices) > 0 else 50.0
            prob_no = round(float(outcome_prices[1]) * 100, 1) if len(outcome_prices) > 1 else round(100 - prob_yes, 1)
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            prob_yes = 50.0
            prob_no = 50.0

        # Build URL
        slug = market.get("slug", "")
        url = f"https://polymarket.com/event/{slug}" if slug else ""

        # End date
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

    # Sort by volume descending, return top 10
    results.sort(key=lambda m: m["volume_usd"], reverse=True)
    return results[:10]


def compute_signal(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcola il segnale direzionale aggregato dai mercati predittivi.

    Separa gli eventi in bullish e bearish, calcola le probabilità medie,
    e produce un segnale netto con livello di confidenza.

    Args:
        markets: Lista di mercati dal risultato di fetch_markets().

    Returns:
        Dizionario con segnale, confidenza, punteggi e top mercati.
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

    bearish_score = 0.0
    bullish_score = 0.0
    bearish_count = 0
    bullish_count = 0

    for market in markets:
        q_lower = market["question"].lower()
        prob_yes = market["prob_yes"]

        is_bearish = any(kw in q_lower for kw in BEARISH_EVENT_KEYWORDS)
        is_bullish = any(kw in q_lower for kw in BULLISH_EVENT_KEYWORDS)

        if is_bearish:
            bearish_score += prob_yes
            bearish_count += 1
        if is_bullish:
            bullish_score += prob_yes
            bullish_count += 1

    avg_bearish = bearish_score / max(bearish_count, 1)
    avg_bullish = bullish_score / max(bullish_count, 1)
    net_score = avg_bullish - avg_bearish

    if net_score < -20:
        signal = "BEARISH"
        confidence = abs(net_score)
    elif net_score > 20:
        signal = "BULLISH"
        confidence = net_score
    else:
        signal = "NEUTRAL"
        confidence = 50.0

    # Clamp confidence to 0-100
    confidence = max(0.0, min(100.0, confidence))

    total_volume = sum(m["volume_usd"] for m in markets)
    top_markets = sorted(markets, key=lambda m: m["volume_usd"], reverse=True)[:5]

    return {
        "signal": signal,
        "confidence": round(confidence, 1),
        "net_score": round(net_score, 1),
        "bullish_prob": round(avg_bullish, 1),
        "bearish_prob": round(avg_bearish, 1),
        "top_markets": top_markets,
        "total_volume": round(total_volume, 2),
        "market_count": len(markets),
    }


def get_polymarket_context(assets: list[dict[str, str]]) -> dict[str, Any]:
    """Funzione di alto livello chiamata da main.py.

    Costruisce le keyword in base agli asset configurati, recupera
    i mercati Polymarket e calcola il segnale aggregato.

    Args:
        assets: Lista di dizionari asset con 'symbol' e 'display_name'.

    Returns:
        Dizionario con dati mercati e segnale direzionale.
    """
    # Build keyword list based on configured assets
    keywords: list[str] = []
    for asset in assets:
        symbol = asset.get("symbol", "").upper()
        display_name = asset.get("display_name", "").lower()

        if any(s in symbol for s in ("NQ", "NAS", "IXIC")):
            keywords.extend(["fed", "recession", "rate", "inflation", "nasdaq", "sp500", "economy"])
        elif any(s in symbol for s in ("ES", "SPX", "GSPC")):
            keywords.extend(["fed", "recession", "rate", "inflation", "nasdaq", "sp500", "economy"])
        elif "EUR" in symbol:
            keywords.extend(["ecb", "euro", "federal reserve", "europe", "dollar"])
        elif "GC" in symbol or "gold" in display_name:
            keywords.extend(["gold", "inflation", "fed", "geopolitical", "war"])
        else:
            keywords.extend(["recession", "fed", "economy", "market"])

    # Deduplicate
    keywords = list(dict.fromkeys(keywords))

    logger.info("Polymarket: ricerca con keyword %s", keywords)
    markets = fetch_markets(keywords)
    signal_data = compute_signal(markets)

    logger.info(
        "Polymarket: %d mercati analizzati, signal=%s",
        signal_data["market_count"],
        signal_data["signal"],
    )

    return signal_data
