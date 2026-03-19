"""Modulo Polymarket — segnale da mercati predittivi.

Interroga l'API pubblica di Polymarket per ottenere probabilità
di eventi macro, Fed, geopolitici e crypto, e calcola un segnale
direzionale da usare come terza conferma nel pipeline di trading.

Miglioramenti rispetto alla v1:
- Paginazione: recupera fino a MAX_PAGES * MARKETS_PER_PAGE mercati
- Tag-based filtering: usa il parametro 'tag' dell'API Gamma
- Volume weighting: il segnale è pesato per volume (mercati più liquidi contano di più)
- LLM classification: usa Groq per classificare se YES è bullish o bearish
  (fallback a keyword se Groq non disponibile)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

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

# ---------------------------------------------------------------------------
# Keyword-based Bearish / Bullish event classification (fallback)
# ---------------------------------------------------------------------------
from modules.keywords import BEARISH_EVENT_KEYWORDS, BULLISH_EVENT_KEYWORDS


def _classify_category(question: str) -> str:
    """Classifica la domanda del mercato in una categoria tematica."""
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
                "Polymarket API errore (tentativo %d/%d): %s",
                attempt, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                logger.warning(
                    "Polymarket API non raggiungibile dopo %d tentativi",
                    MAX_RETRIES,
                )
                return []
    return []


def fetch_markets(
    keywords: list[str],
    min_volume_usd: float = 10_000,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Recupera mercati Polymarket con paginazione, filtro per tag e keyword.

    Args:
        keywords: Parole chiave per filtrare i mercati (client-side).
        min_volume_usd: Volume minimo in USD per considerare un mercato.
        tags: Tag API per filtrare server-side (es. "economics", "politics").

    Returns:
        Lista di mercati filtrati, ordinati per volume decrescente (max 20).
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
# LLM-based classification (with keyword fallback)
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
    return markets


def classify_markets_with_llm(
    markets: list[dict[str, Any]],
    groq_model: str = "llama-3.3-70b-versatile",
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Use Groq LLM to classify whether YES outcome is bullish or bearish.

    Handles semantic ambiguity (e.g. "Will US avoid recession?" YES = bullish).
    Falls back to keyword-based classification if Groq is unavailable.

    Args:
        markets: List of market dicts with 'question'.
        groq_model: Groq model ID.
        api_key: Groq API key (reads from env if not provided).

    Returns:
        Same markets list with added 'impact' field.
    """
    if not markets:
        return markets

    # Pre-populate ALL markets with keyword fallback to avoid race condition
    # (ensures every market has an 'impact' field even if LLM fails mid-way)
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
        f"{i + 1}. {m['question']}" for i, m in enumerate(batch)
    )

    prompt = f"""Classifica ogni mercato predittivo: se l'evento SI' si verifica,
e' BULLISH o BEARISH per i mercati finanziari (azioni, indici)?

MERCATI:
{questions_block}

Rispondi ESCLUSIVAMENTE con un array JSON (senza markdown, senza ```):
[
  {{"index": 1, "impact": "BULLISH_IF_YES"}},
  {{"index": 2, "impact": "BEARISH_IF_YES"}},
  ...
]

Regole:
- impact deve essere "BULLISH_IF_YES" o "BEARISH_IF_YES"
- Considera l'impatto sui mercati azionari/indici
- "Fed taglia tassi" -> BULLISH_IF_YES
- "Recessione USA" -> BEARISH_IF_YES
- "USA evita recessione" -> BULLISH_IF_YES
- Rispondi SOLO con il JSON"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=groq_model,
            messages=[
                {
                    "role": "system",
                    "content": "Classifica eventi come bullish o bearish "
                               "per i mercati. Rispondi solo in JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        classifications = json.loads(raw)

        impact_map: dict[int, str] = {}
        for c in classifications:
            idx = c.get("index", 0) - 1
            impact_map[idx] = c.get("impact", "BEARISH_IF_YES")

        for i, market in enumerate(batch):
            market["impact"] = impact_map.get(i, market.get("impact", "BEARISH_IF_YES"))

        logger.info("LLM classified %d Polymarket markets", len(batch))
        return markets

    except Exception as exc:
        logger.warning("LLM classification failed, using keyword fallback: %s", exc)
        return markets  # Already pre-populated with keyword classifications


# ---------------------------------------------------------------------------
# Signal computation (volume-weighted)
# ---------------------------------------------------------------------------

def compute_signal(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcola il segnale direzionale aggregato, pesato per volume.

    Ogni mercato contribuisce in proporzione al proprio volume.
    La classificazione bullish/bearish viene dal campo 'impact'
    (impostato da classify_markets_with_llm o dal fallback keyword).

    Args:
        markets: Lista di mercati con campo 'impact' opzionale.

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

    total_volume = sum(m["volume_usd"] for m in markets)
    if total_volume == 0:
        total_volume = 1.0

    bearish_weighted = 0.0
    bullish_weighted = 0.0

    for market in markets:
        prob_yes = market["prob_yes"]
        weight = market["volume_usd"] / total_volume
        impact = market.get("impact", "")

        # If no LLM impact, fall back to keyword classification inline
        if not impact:
            impact = _keyword_classify_single(market["question"])

        if impact == "BEARISH_IF_YES":
            bearish_weighted += prob_yes * weight
        elif impact == "BULLISH_IF_YES":
            bullish_weighted += prob_yes * weight

    net_score = bullish_weighted - bearish_weighted

    if net_score < -10:
        signal = "BEARISH"
        confidence = min(100.0, abs(net_score) * 2)
    elif net_score > 10:
        signal = "BULLISH"
        confidence = min(100.0, net_score * 2)
    else:
        signal = "NEUTRAL"
        confidence = 50.0

    confidence = max(0.0, min(100.0, confidence))

    top_markets = sorted(
        markets, key=lambda m: m["volume_usd"], reverse=True,
    )[:5]

    return {
        "signal": signal,
        "confidence": round(confidence, 1),
        "net_score": round(net_score, 1),
        "bullish_prob": round(bullish_weighted, 1),
        "bearish_prob": round(bearish_weighted, 1),
        "top_markets": top_markets,
        "total_volume": round(total_volume, 2),
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
    """Funzione di alto livello chiamata da main.py.

    Costruisce tag e keyword in base agli asset configurati, recupera
    i mercati Polymarket con paginazione, classifica con LLM (o keyword),
    e calcola il segnale aggregato pesato per volume.

    Args:
        assets: Lista di dizionari asset con 'symbol' e 'display_name'.
        groq_model: Modello Groq per classificazione LLM.
        groq_api_key: API key Groq (opzionale, legge da env se assente).

    Returns:
        Dizionario con dati mercati e segnale direzionale.
    """
    tags = _get_tags_for_assets(assets)
    keywords = _get_keywords_for_assets(assets)

    logger.info("Polymarket: ricerca con tag %s, keyword %s", tags, keywords)
    markets = fetch_markets(keywords, tags=tags)

    # Classify with LLM (falls back to keywords if unavailable)
    markets = classify_markets_with_llm(
        markets, groq_model=groq_model, api_key=groq_api_key,
    )

    signal_data = compute_signal(markets)

    logger.info(
        "Polymarket: %d mercati analizzati, signal=%s",
        signal_data["market_count"],
        signal_data["signal"],
    )

    return signal_data
