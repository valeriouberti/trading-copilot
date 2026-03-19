"""Shared keyword lists for sentiment classification.

Single source of truth for bullish/bearish keywords used by
both the hallucination guard and the Polymarket classifier.
"""

from __future__ import annotations

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

# More specific event-level keywords for Polymarket classification
BEARISH_EVENT_KEYWORDS = [
    "recession", "crash", "rate hike", "hawkish", "default",
    "war", "conflict", "tariff", "unemployment rise", "contraction",
]

BULLISH_EVENT_KEYWORDS = [
    "rate cut", "dovish", "soft landing", "growth", "rally",
    "recovery", "expansion",
]
