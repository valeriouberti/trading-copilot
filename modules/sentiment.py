"""Sentiment analysis module — v2.

Two-pass chain-of-thought LLM analysis with per-asset scoring.
Pass 1: Free-text reasoning (better quality through step-by-step thinking)
Pass 2: Structured JSON extraction from the reasoning output.

Features:
- Temporal weighting: recent news weighted more heavily
- Per-asset scores: each asset gets its own directional score
- Few-shot calibration: anchored scoring examples
- FinBERT ensemble: cross-validation when Groq succeeds
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2.0


@dataclass
class SentimentResult:
    """Structured sentiment analysis output."""

    sentiment_score: float  # -3 to +3 (global macro)
    sentiment_label: str  # e.g., "Moderately Bearish"
    key_drivers: list[str] = field(default_factory=list)
    directional_bias: str = ""  # "BULLISH", "BEARISH", "NEUTRAL"
    risk_events: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "groq"  # "groq", "groq-2pass", "finbert"
    error: str | None = None
    # v2: per-asset scoring
    asset_scores: dict[str, float] = field(default_factory=dict)
    asset_biases: dict[str, str] = field(default_factory=dict)
    # v2: FinBERT ensemble
    finbert_score: float | None = None
    finbert_agreement: str = ""  # "AGREE", "PARTIAL", "DISAGREE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentiment_score": self.sentiment_score,
            "sentiment_label": self.sentiment_label,
            "key_drivers": self.key_drivers,
            "directional_bias": self.directional_bias,
            "risk_events": self.risk_events,
            "confidence": self.confidence,
            "source": self.source,
            "error": self.error,
            "asset_scores": self.asset_scores,
            "asset_biases": self.asset_biases,
            "finbert_score": self.finbert_score,
            "finbert_agreement": self.finbert_agreement,
        }


# ---------------------------------------------------------------------------
# News temporal tagging
# ---------------------------------------------------------------------------

def _tag_news_with_recency(
    news: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add temporal recency tags to news for the LLM prompt."""
    now = datetime.now(timezone.utc)
    tagged: list[dict[str, Any]] = []
    for article in news:
        pub = article.get("published_at")
        hours_ago = 99.0
        tag = ""
        if hasattr(pub, "timestamp"):
            try:
                hours_ago = (now - pub).total_seconds() / 3600
                if hours_ago < 1:
                    tag = f"[{max(1, int(hours_ago * 60))}m ago]"
                else:
                    tag = f"[{int(hours_ago)}h ago]"
            except (TypeError, ValueError):
                pass
        tagged.append({**article, "_time_tag": tag, "_hours_ago": hours_ago})
    return tagged


# ---------------------------------------------------------------------------
# Two-pass prompts
# ---------------------------------------------------------------------------

def _build_reasoning_prompt(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    poly_data: dict[str, Any] | None = None,
) -> str:
    """Pass 1: Chain-of-thought reasoning prompt."""
    asset_names = ", ".join(
        f"{a.get('display_name', a['symbol'])} ({a['symbol']})"
        for a in assets
    )

    news_block = ""
    for i, article in enumerate(news[:20], 1):
        tag = article.get("_time_tag", "")
        src = article.get("source", "")
        title = article.get("title", "")
        news_block += f"{i}. {tag} [{src}] {title}\n"
        summary = article.get("summary", "")
        if summary:
            news_block += f"   {summary[:200]}\n"

    poly_block = ""
    if poly_data and poly_data.get("market_count", 0) > 0:
        top = poly_data.get("top_markets", [])[:5]
        if top:
            lines = "\n".join(
                f"- {m['question']}: {m['prob_yes']:.0f}% YES"
                for m in top
            )
            poly_block = f"""
PREDICTION MARKET DATA (Polymarket — real money at stake):
{lines}
"""

    return f"""You are a senior quant analyst specializing in macro analysis for CFD trading.
Analyze these news articles step-by-step.

FUNDAMENTAL RULE: Recent news ([1h ago], [2h ago]) weighs MUCH more heavily
than older news ([10h ago], [15h ago]). A news item from 1 hour ago counts 3x
compared to one from 8 hours ago.

NEWS (sorted by recency):
{news_block}
{poly_block}
ASSETS TO ANALYZE: {asset_names}

Reason through these points:
1. KEY NEWS: What are the 3 most market-moving news items and WHY?
2. PER-ASSET ANALYSIS: For EACH asset, what is the specific impact?
   (e.g.: "Fed hawkish" is bearish for NQ but can be bullish for USD)
3. RISK EVENTS: Are there high-impact events in the next 24h?
4. MACRO CONTEXT: Risk-on, risk-off, or indeterminate?

Respond in a structured way, reasoning step-by-step."""


def _build_extraction_prompt(
    reasoning: str,
    assets: list[dict[str, str]],
) -> str:
    """Pass 2: JSON extraction from reasoning, with few-shot calibration."""
    asset_symbols = [a["symbol"] for a in assets]
    asset_score_lines = ",\n    ".join(
        f'"{s}": <-3.0 to +3.0>' for s in asset_symbols
    )

    return f"""Given your previous analysis, produce EXCLUSIVELY a valid JSON.

ANALYSIS:
{reasoning}

SCORE CALIBRATION — use these examples as reference:
+3.0 = Extremely bullish (e.g.: Fed surprise rate cut + record employment + CPI below expectations)
+2.0 = Very bullish (e.g.: CPI below expectations + widespread positive corporate guidance)
+1.5 = Bullish (e.g.: solid employment data, market in positive trend)
+1.0 = Moderately bullish (e.g.: mixed data but slightly positive)
+0.5 = Slightly bullish (e.g.: no negative news, momentum continues)
 0.0 = Neutral (no relevant news or perfectly contrasting signals)
-0.5 = Slightly bearish (e.g.: growing uncertainty, mixed data)
-1.0 = Moderately bearish (e.g.: weak employment data, trade tensions)
-1.5 = Bearish (e.g.: Fed hawkish + data below expectations)
-2.0 = Very bearish (e.g.: geopolitical escalation + negative GDP)
-3.0 = Extremely bearish (e.g.: banking crisis + confirmed recession + panic selling)

FORMAT — respond ONLY with this JSON (NO markdown, NO ```):
{{
  "sentiment_score": <-3.0 to +3.0>,
  "sentiment_label": "<descriptive label in English>",
  "key_drivers": ["<driver 1>", "<driver 2>", "<driver 3>"],
  "directional_bias": "<BULLISH|BEARISH|NEUTRAL>",
  "risk_events": ["<risk event 1>"],
  "confidence": <0-100>,
  "asset_scores": {{
    {asset_score_lines}
  }}
}}

Rules:
- sentiment_score: weighted average, recent news counts 3x
- asset_scores: SPECIFIC score for each asset (CAN diverge)
- key_drivers: exactly 3 elements
- risk_events: can be empty [] if there are no risks
- confidence: analysis certainty (0-100)
- Respond ONLY with JSON"""


# Backward-compatible single-pass prompt
def _build_prompt(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    poly_data: dict[str, Any] | None = None,
) -> str:
    """Single-pass prompt (fallback if two-pass fails)."""
    asset_names = ", ".join(a.get("display_name", a["symbol"]) for a in assets)

    news_block = ""
    for i, article in enumerate(news[:20], 1):
        tag = article.get("_time_tag", "")
        news_block += f"{i}. {tag} [{article['source']}] {article['title']}\n"
        if article.get("summary"):
            news_block += f"   {article['summary'][:200]}\n"

    poly_block = ""
    if poly_data and poly_data.get("market_count", 0) > 0:
        top_markets = poly_data.get("top_markets", [])[:3]
        if top_markets:
            market_lines = "\n".join(
                f"- {m['question']}: {m['prob_yes']:.0f}% probability YES"
                for m in top_markets
            )
            poly_block = f"""

ADDITIONAL DATA — PREDICTION MARKETS (Polymarket):
{market_lines}

Take this data into account in your sentiment analysis.
"""

    asset_symbols = [a["symbol"] for a in assets]
    asset_score_lines = ",\n    ".join(
        f'"{s}": <-3.0 to +3.0>' for s in asset_symbols
    )

    return f"""You are an expert financial analyst. Analyze the following market news
and provide a macro sentiment analysis for a retail CFD trader operating on: {asset_names}.

IMPORTANT: More recent news (lower time tag) weighs more heavily.

RECENT NEWS:
{news_block}
{poly_block}
Respond EXCLUSIVELY with a valid JSON object (no markdown, no ```), with this exact structure:
{{
  "sentiment_score": <number from -3 to +3, where -3 = extremely bearish, +3 = extremely bullish>,
  "sentiment_label": "<descriptive label in English>",
  "key_drivers": ["<driver 1>", "<driver 2>", "<driver 3>"],
  "directional_bias": "<BULLISH|BEARISH|NEUTRAL>",
  "risk_events": ["<risk event 1>", "<risk event 2>"],
  "confidence": <number from 0 to 100>,
  "asset_scores": {{
    {asset_score_lines}
  }}
}}

Rules:
- sentiment_score must be a number with 1 decimal
- asset_scores: SPECIFIC score per asset (can diverge!)
- key_drivers must have exactly 3 elements, brief and impactful
- risk_events can be empty [] if there are no particular risks today
- confidence reflects how certain you are of the analysis (0-100)
- Respond ONLY with the JSON, no additional text"""


# ---------------------------------------------------------------------------
# Helper to parse and clean LLM JSON
# ---------------------------------------------------------------------------

def _clean_json_response(raw: str) -> str:
    """Strip markdown fences and whitespace from LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return raw


def _parse_sentiment_json(
    data: dict[str, Any],
    assets: list[dict[str, str]],
    source: str = "groq",
) -> SentimentResult:
    """Parse a validated JSON dict into a SentimentResult."""
    # Per-asset scores
    raw_asset_scores = data.get("asset_scores", {})
    asset_scores: dict[str, float] = {}
    asset_biases: dict[str, str] = {}

    for a in assets:
        sym = a["symbol"]
        score = float(raw_asset_scores.get(sym, data.get("sentiment_score", 0)))
        score = max(-3.0, min(3.0, score))
        asset_scores[sym] = score
        if score >= 0.5:
            asset_biases[sym] = "BULLISH"
        elif score <= -0.5:
            asset_biases[sym] = "BEARISH"
        else:
            asset_biases[sym] = "NEUTRAL"

    return SentimentResult(
        sentiment_score=float(data.get("sentiment_score", 0)),
        sentiment_label=str(data.get("sentiment_label", "Neutral")),
        key_drivers=list(data.get("key_drivers", []))[:3],
        directional_bias=str(data.get("directional_bias", "NEUTRAL")),
        risk_events=list(data.get("risk_events", [])),
        confidence=float(data.get("confidence", 50)),
        source=source,
        asset_scores=asset_scores,
        asset_biases=asset_biases,
    )


# ---------------------------------------------------------------------------
# Groq LLM call with retry
# ---------------------------------------------------------------------------

def _groq_call(
    client: Any,
    model: str,
    system_msg: str,
    user_msg: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> str:
    """Make a single Groq API call with retry logic. Returns raw text."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            if "rate_limit" in str(exc).lower() or "429" in str(exc):
                wait = BACKOFF_BASE ** attempt
                logger.warning(
                    "Rate limited, retrying in %.1fs (attempt %d)", wait, attempt,
                )
                time.sleep(wait)
                if attempt == MAX_RETRIES:
                    raise
            else:
                raise
    raise RuntimeError("Groq call failed after all retries")


# ---------------------------------------------------------------------------
# Two-pass Groq analysis
# ---------------------------------------------------------------------------

def _analyze_with_groq_two_pass(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    model: str,
    api_key: str,
    poly_data: dict[str, Any] | None = None,
) -> SentimentResult:
    """Two-pass chain-of-thought analysis for higher quality."""
    if Groq is None:
        raise RuntimeError("groq library not installed")

    client = Groq(api_key=api_key)

    # Pass 1: Chain-of-thought reasoning
    reasoning_prompt = _build_reasoning_prompt(news, assets, poly_data)
    logger.info("Groq Pass 1: chain-of-thought reasoning...")
    reasoning = _groq_call(
        client, model,
        system_msg="You are a senior quant analyst. Reason step-by-step about the impact "
                   "of news on financial markets.",
        user_msg=reasoning_prompt,
        max_tokens=1000,
        temperature=0.4,
    )
    logger.debug("Groq Pass 1 reasoning: %s", reasoning[:200])

    # Pass 2: Structured JSON extraction
    extraction_prompt = _build_extraction_prompt(reasoning, assets)
    logger.info("Groq Pass 2: structured extraction...")
    raw_json = _groq_call(
        client, model,
        system_msg="You are a data extraction engine. Convert the analysis to valid JSON. "
                   "Respond ONLY with JSON.",
        user_msg=extraction_prompt,
        max_tokens=600,
        temperature=0.1,
    )
    logger.debug("Groq Pass 2 raw: %s", raw_json[:200])

    cleaned = _clean_json_response(raw_json)
    data = json.loads(cleaned)
    result = _parse_sentiment_json(data, assets, source="groq-2pass")
    logger.info("Two-pass analysis complete: score=%.1f, bias=%s",
                result.sentiment_score, result.directional_bias)
    return result


def _analyze_with_groq_single_pass(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    model: str,
    api_key: str,
    poly_data: dict[str, Any] | None = None,
) -> SentimentResult:
    """Single-pass fallback (used if two-pass fails)."""
    if Groq is None:
        raise RuntimeError("groq library not installed")

    client = Groq(api_key=api_key)
    prompt = _build_prompt(news, assets, poly_data=poly_data)

    raw = _groq_call(
        client, model,
        system_msg="You are a financial analyst. Respond only in valid JSON.",
        user_msg=prompt,
        max_tokens=600,
        temperature=0.3,
    )

    cleaned = _clean_json_response(raw)
    data = json.loads(cleaned)
    return _parse_sentiment_json(data, assets, source="groq")


def _analyze_with_groq(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    model: str,
    api_key: str,
    poly_data: dict[str, Any] | None = None,
) -> SentimentResult:
    """Main Groq analysis: tries two-pass, falls back to single-pass."""
    # Try two-pass first (better quality)
    try:
        return _analyze_with_groq_two_pass(
            news, assets, model, api_key, poly_data,
        )
    except Exception as exc:
        logger.warning(
            "Two-pass analysis failed, trying single-pass: %s", exc,
        )

    # Fallback to single-pass
    return _analyze_with_groq_single_pass(
        news, assets, model, api_key, poly_data,
    )


# ---------------------------------------------------------------------------
# FinBERT (fallback + ensemble cross-validation)
# ---------------------------------------------------------------------------

def _get_finbert_score(news: list[dict[str, Any]]) -> float | None:
    """Run FinBERT on headlines and return a -3 to +3 score, or None on failure."""
    try:
        from transformers import pipeline
    except ImportError:
        return None

    try:
        classifier = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            truncation=True,
            max_length=512,
        )
    except Exception as exc:
        logger.warning("Failed to load FinBERT: %s", exc)
        return None

    texts = [a["title"] for a in news[:30]]
    if not texts:
        return None

    results = classifier(texts)
    total_score = 0.0
    for res in results:
        label = res["label"].lower()
        score = res["score"]
        if label == "positive":
            total_score += score
        elif label == "negative":
            total_score -= score

    avg = total_score / len(results) if results else 0
    return round(max(-3.0, min(3.0, avg * 3)), 1)


def _compute_finbert_agreement(
    groq_score: float, finbert_score: float | None,
) -> tuple[str, float]:
    """Compute agreement level between Groq and FinBERT.

    Returns (agreement_label, confidence_modifier).
    - AGREE: scores within 1.0 → boost confidence
    - PARTIAL: scores within 2.0 → no change
    - DISAGREE: scores diverge > 2.0 → reduce confidence
    """
    if finbert_score is None:
        return "", 0.0

    divergence = abs(groq_score - finbert_score)
    if divergence <= 1.0:
        return "AGREE", 5.0  # boost
    elif divergence <= 2.0:
        return "PARTIAL", 0.0
    else:
        return "DISAGREE", -15.0  # reduce


def _analyze_with_finbert(news: list[dict[str, Any]]) -> SentimentResult:
    """Fallback sentiment analysis using FinBERT."""
    try:
        from transformers import pipeline
    except ImportError:
        logger.error("transformers library not installed for FinBERT fallback")
        return SentimentResult(
            sentiment_score=0.0,
            sentiment_label="Not available",
            key_drivers=["Analysis not available — install transformers and torch"],
            directional_bias="NEUTRAL",
            confidence=0.0,
            source="finbert",
            error="transformers not installed",
        )

    try:
        classifier = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            truncation=True,
            max_length=512,
        )
    except Exception as exc:
        logger.error("Failed to load FinBERT model: %s", exc)
        return SentimentResult(
            sentiment_score=0.0,
            sentiment_label="Model error",
            key_drivers=["Error loading FinBERT model"],
            directional_bias="NEUTRAL",
            confidence=0.0,
            source="finbert",
            error=str(exc),
        )

    # Analyze each headline
    texts = [a["title"] for a in news[:30]]
    results = classifier(texts)

    positive_count = 0
    negative_count = 0
    total_score = 0.0

    for res in results:
        label = res["label"].lower()
        score = res["score"]
        if label == "positive":
            positive_count += 1
            total_score += score
        elif label == "negative":
            negative_count += 1
            total_score -= score

    n = len(results)
    avg_score = total_score / n if n > 0 else 0
    sentiment_score = round(max(-3.0, min(3.0, avg_score * 3)), 1)

    if sentiment_score > 1:
        label = "Bullish"
        bias = "BULLISH"
    elif sentiment_score > 0.3:
        label = "Moderately Bullish"
        bias = "BULLISH"
    elif sentiment_score < -1:
        label = "Bearish"
        bias = "BEARISH"
    elif sentiment_score < -0.3:
        label = "Moderately Bearish"
        bias = "BEARISH"
    else:
        label = "Neutral"
        bias = "NEUTRAL"

    confidence = (max(positive_count, negative_count) / n * 100) if n > 0 else 0
    drivers = [texts[i] for i in range(min(3, len(texts)))]

    return SentimentResult(
        sentiment_score=sentiment_score,
        sentiment_label=label,
        key_drivers=drivers,
        directional_bias=bias,
        confidence=round(confidence, 1),
        source="finbert",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_sentiment(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    groq_model: str = "llama-3.3-70b-versatile",
    poly_data: dict[str, Any] | None = None,
) -> SentimentResult:
    """Analyze market sentiment from news.

    Pipeline:
    1. Tag news with temporal recency
    2. Try two-pass Groq LLM (chain-of-thought → extraction)
    3. If Groq succeeds, run FinBERT ensemble cross-validation
    4. If Groq fails, use FinBERT as fallback

    Args:
        news: List of articles from news_fetcher.
        assets: List of asset dicts.
        groq_model: Groq model identifier.
        poly_data: Optional Polymarket data to enrich the prompt.

    Returns:
        SentimentResult with scores and analysis.
    """
    if not news:
        logger.warning("No news articles to analyze")
        return SentimentResult(
            sentiment_score=0.0,
            sentiment_label="Neutral",
            key_drivers=["No news available"],
            directional_bias="NEUTRAL",
            confidence=0.0,
        )

    # Step 1: Tag news with temporal recency
    tagged_news = _tag_news_with_recency(news)

    # Step 2: Try Groq LLM
    api_key = os.environ.get("GROQ_API_KEY", "")
    result: SentimentResult | None = None

    if api_key:
        try:
            result = _analyze_with_groq(
                tagged_news, assets, groq_model, api_key, poly_data=poly_data,
            )
        except Exception as exc:
            logger.warning("Groq analysis failed, falling back to FinBERT: %s", exc)

    # Step 3: FinBERT ensemble (if Groq succeeded) or fallback
    if result is not None:
        # Run FinBERT as cross-validation
        try:
            finbert_score = _get_finbert_score(news)
            if finbert_score is not None:
                agreement, conf_mod = _compute_finbert_agreement(
                    result.sentiment_score, finbert_score,
                )
                result.finbert_score = finbert_score
                result.finbert_agreement = agreement
                result.confidence = max(
                    0.0, min(100.0, result.confidence + conf_mod),
                )
                logger.info(
                    "FinBERT ensemble: score=%.1f, agreement=%s (Groq=%.1f)",
                    finbert_score, agreement, result.sentiment_score,
                )
        except Exception as exc:
            logger.debug("FinBERT ensemble skipped: %s", exc)
        return result

    # Step 4: FinBERT fallback
    logger.info("Using FinBERT fallback for sentiment analysis")
    return _analyze_with_finbert(news)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_news = [
        {
            "title": "Fed holds rates steady, signals cautious approach",
            "summary": "",
            "source": "Reuters",
            "published_at": "2024-01-15",
        },
        {
            "title": "Tech stocks rally on strong earnings",
            "summary": "",
            "source": "Yahoo",
            "published_at": "2024-01-15",
        },
        {
            "title": "Oil prices drop on demand concerns",
            "summary": "",
            "source": "Investing",
            "published_at": "2024-01-15",
        },
    ]
    sample_assets = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]
    result = analyze_sentiment(sample_news, sample_assets)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
