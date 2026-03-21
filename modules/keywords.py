"""Shared keyword lists for sentiment classification.

Single source of truth for bullish/bearish keywords used by
both the hallucination guard and the Polymarket classifier.

v2: Replaced ambiguous unigrams (down, up, cut, high, etc.) with
precise bigrams to reduce false positives in headline matching.
"""

from __future__ import annotations

BEARISH_KEYWORDS = [
    # Clear single words (unlikely to false-match in financial headlines)
    "crash", "drop", "fear", "sell", "decline", "plunge",
    "recession", "crisis", "bear", "collapse", "dump", "panic",
    "warning", "slump", "tumble", "weak",
    # Bigrams replacing removed ambiguous unigrams: down, cut, lower, loss, risk, fall
    "sell-off", "selloff", "bear market", "market drop",
    "rate hike", "sharp decline",
]

BULLISH_KEYWORDS = [
    # Clear single words
    "rally", "surge", "gain", "bull", "growth", "record",
    "boost", "jump", "soar", "profit", "recovery",
    # Bigrams replacing removed ambiguous unigrams: up, high, buy, strong, rise
    "bull market", "record high", "all-time high", "market rally",
    "breakout", "rebound",
]

# More specific event-level keywords for Polymarket classification
BEARISH_EVENT_KEYWORDS = [
    "recession", "crash", "rate hike", "hawkish", "default",
    "war", "conflict", "tariff", "unemployment rise", "contraction",
    "debt ceiling", "government shutdown", "banking crisis",
    "trade war", "sanctions", "stagflation",
]

BULLISH_EVENT_KEYWORDS = [
    "rate cut", "dovish", "soft landing", "growth", "rally",
    "recovery", "expansion", "stimulus", "quantitative easing",
    "trade deal", "ceasefire", "peace deal",
]
