"""Hallucination guard module.

Validates LLM sentiment output against news content and technical signals
to detect potential hallucinations or inconsistencies.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

BEARISH_KEYWORDS = [
    "crash", "drop", "fall", "fear", "sell", "decline", "loss", "plunge",
    "recession", "crisis", "bear", "collapse", "dump", "panic", "risk",
    "warning", "slump", "tumble", "weak", "down", "cut", "lower",
    "calo", "crollo", "ribasso", "paura", "vendita", "perdita", "crisi",
]

BULLISH_KEYWORDS = [
    "rally", "surge", "rise", "gain", "bull", "growth", "record", "high",
    "boost", "jump", "soar", "strong", "up", "buy", "profit", "recovery",
    "rialzo", "crescita", "record", "guadagno", "rimbalzo", "acquisto",
]


@dataclass
class ValidationResult:
    """Result of hallucination guard validation."""
    validated: bool
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"validated": self.validated, "flags": self.flags}


def validate(
    sentiment: Any,
    news: list[dict[str, Any]],
    asset_analyses: list[Any],
) -> ValidationResult:
    """Validate LLM sentiment against news content and technicals.

    Args:
        sentiment: SentimentResult object.
        news: List of news article dicts.
        asset_analyses: List of AssetAnalysis objects.

    Returns:
        ValidationResult with validated flag and list of issue flags.
    """
    flags: list[str] = []

    score = getattr(sentiment, "sentiment_score", 0)
    bias = getattr(sentiment, "directional_bias", "FLAT")

    # Check 1: Sentiment score vs news keyword analysis
    keyword_score = _keyword_sentiment(news)
    if _is_sentiment_mismatch(score, keyword_score):
        flags.append("SENTIMENT_MISMATCH")
        logger.warning(
            "Sentiment mismatch: LLM score=%.1f, keyword score=%.1f",
            score, keyword_score,
        )

    # Check 2: LLM directional bias vs technical composite
    if asset_analyses:
        tech_direction = _aggregate_technical_direction(asset_analyses)
        if _is_direction_conflict(bias, tech_direction):
            flags.append("DIRECTION_CONFLICT")
            logger.warning(
                "Direction conflict: LLM bias=%s, technicals=%s",
                bias, tech_direction,
            )

    # Check 3: Extreme score on neutral news
    if abs(score) >= 2.5 and abs(keyword_score) < 0.5:
        flags.append("EXTREME_SCORE_NEUTRAL_NEWS")
        logger.warning(
            "Extreme score (%.1f) on neutral news (keyword=%.1f)",
            score, keyword_score,
        )

    validated = len(flags) == 0
    return ValidationResult(validated=validated, flags=flags)


def validate_polymarket_consistency(
    sentiment: Any,
    poly_signal: dict[str, Any] | None,
    asset_analyses: list[Any] | None = None,
) -> list[str]:
    """Valida la coerenza tra segnale LLM e segnale Polymarket.

    Controlla conflitti tra bias direzionale LLM e segnale Polymarket,
    e rileva confluenza tripla quando tutti i segnali concordano.

    Args:
        sentiment: SentimentResult dell'analisi LLM.
        poly_signal: Dizionario con segnale Polymarket da compute_signal().
        asset_analyses: Lista di AssetAnalysis per la confluenza tripla.

    Returns:
        Lista di flag di validazione (stringhe).
    """
    flags: list[str] = []

    if not poly_signal or poly_signal.get("market_count", 0) == 0:
        return flags

    llm_direction = getattr(sentiment, "directional_bias", "NEUTRAL")
    poly_dir = poly_signal.get("signal", "NEUTRAL")
    poly_confidence = poly_signal.get("confidence", 0)

    # Check for conflict
    if llm_direction == "BULLISH" and poly_dir == "BEARISH" and poly_confidence > 65:
        flags.append(
            f"POLYMARKET_CONFLICT: Polymarket bearish {poly_confidence:.0f}% vs LLM bullish"
        )
        logger.warning(
            "Polymarket conflict: poly=%s (%.0f%%) vs LLM=%s",
            poly_dir, poly_confidence, llm_direction,
        )

    if llm_direction == "BEARISH" and poly_dir == "BULLISH" and poly_confidence > 65:
        flags.append(
            f"POLYMARKET_CONFLICT: Polymarket bullish {poly_confidence:.0f}% vs LLM bearish"
        )
        logger.warning(
            "Polymarket conflict: poly=%s (%.0f%%) vs LLM=%s",
            poly_dir, poly_confidence, llm_direction,
        )

    # Check for triple confluence (LLM + technicals + Polymarket all agree)
    if asset_analyses and llm_direction != "NEUTRAL" and poly_dir != "NEUTRAL":
        tech_direction = _aggregate_technical_direction(asset_analyses)
        if llm_direction == poly_dir == tech_direction:
            flags.append(
                f"TRIPLE_CONFLUENCE: All signals aligned {llm_direction}"
            )
            logger.info(
                "Triple confluence detected: all signals %s", llm_direction
            )

    return flags


def _keyword_sentiment(news: list[dict[str, Any]]) -> float:
    """Compute a simple keyword-based sentiment score from news titles.

    Returns a score in roughly the -3 to +3 range.
    """
    if not news:
        return 0.0

    bullish_count = 0
    bearish_count = 0

    for article in news:
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        text = f"{title} {summary}"

        for kw in BULLISH_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                bullish_count += 1
                break

        for kw in BEARISH_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                bearish_count += 1
                break

    total = bullish_count + bearish_count
    if total == 0:
        return 0.0

    # Normalize to -3..+3 range
    ratio = (bullish_count - bearish_count) / len(news)
    return round(ratio * 3.0, 1)


def _aggregate_technical_direction(asset_analyses: list[Any]) -> str:
    """Get the majority technical direction across all assets."""
    bullish = 0
    bearish = 0
    for a in asset_analyses:
        score = getattr(a, "composite_score", "NEUTRAL")
        if score == "BULLISH":
            bullish += 1
        elif score == "BEARISH":
            bearish += 1

    if bullish > bearish:
        return "BULLISH"
    elif bearish > bullish:
        return "BEARISH"
    return "NEUTRAL"


def _is_sentiment_mismatch(llm_score: float, keyword_score: float) -> bool:
    """Check if LLM sentiment diverges more than 3 points from keyword baseline."""
    return abs(llm_score - keyword_score) > 3.0


def _is_direction_conflict(llm_bias: str, tech_direction: str) -> bool:
    """Check if LLM directional bias contradicts all technicals."""
    if tech_direction == "NEUTRAL" or llm_bias == "NEUTRAL":
        return False
    if llm_bias == "BULLISH" and tech_direction == "BEARISH":
        return True
    if llm_bias == "BEARISH" and tech_direction == "BULLISH":
        return True
    return False


def determine_regime(
    sentiment: Any,
    asset_analyses: list[Any],
    validation_flags: list[str],
) -> tuple[str, str]:
    """Determine the day's operational regime based on all signals.

    Returns:
        Tuple of (regime, reason) where regime is "LONG", "SHORT", or "NEUTRAL".
    """
    score = getattr(sentiment, "sentiment_score", 0)

    # Red flags force NEUTRAL regime
    red_flags = [
        f for f in validation_flags
        if any(x in f for x in ["SENTIMENT_MISMATCH", "DIRECTION_CONFLICT"])
    ]
    if red_flags:
        return "NEUTRAL", "Flag rossi presenti"

    tech_direction = _aggregate_technical_direction(asset_analyses) if asset_analyses else "NEUTRAL"

    if score >= 1.0 and tech_direction in ("BULLISH", "NEUTRAL"):
        return "LONG", "LLM bullish + tecnici favorevoli"
    elif score <= -1.0 and tech_direction in ("BEARISH", "NEUTRAL"):
        return "SHORT", "LLM bearish + tecnici favorevoli"
    else:
        return "NEUTRAL", "Segnali non direzionali o in conflitto"
