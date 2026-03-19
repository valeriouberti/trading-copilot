"""Sentiment analysis module.

Uses Groq LLM (free tier) for macro sentiment analysis of financial news.
Falls back to FinBERT if Groq is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
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

    sentiment_score: float  # -3 to +3
    sentiment_label: str  # e.g., "Moderatamente Ribassista"
    key_drivers: list[str] = field(default_factory=list)
    directional_bias: str = ""  # "BULLISH", "BEARISH", "NEUTRAL"
    risk_events: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "groq"  # "groq" or "finbert"
    error: str | None = None

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
        }


def analyze_sentiment(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    groq_model: str = "llama-3.3-70b-versatile",
    poly_data: dict[str, Any] | None = None,
) -> SentimentResult:
    """Analizza il sentiment di mercato dalle notizie.

    Prova Groq LLM, usa FinBERT come fallback.

    Args:
        news: Lista di articoli dal news_fetcher.
        assets: Lista di dizionari asset.
        groq_model: Identificativo modello Groq.
        poly_data: Dati opzionali da Polymarket per arricchire il prompt.

    Returns:
        SentimentResult con punteggi e analisi.
    """
    if not news:
        logger.warning("No news articles to analyze")
        return SentimentResult(
            sentiment_score=0.0,
            sentiment_label="Neutro",
            key_drivers=["Nessuna notizia disponibile"],
            directional_bias="NEUTRAL",
            confidence=0.0,
        )

    # Try Groq first
    api_key = os.environ.get("GROQ_API_KEY", "")
    if api_key:
        try:
            return _analyze_with_groq(news, assets, groq_model, api_key, poly_data=poly_data)
        except Exception as exc:
            logger.warning("Groq analysis failed, falling back to FinBERT: %s", exc)

    # Fallback to FinBERT
    logger.info("Using FinBERT fallback for sentiment analysis")
    return _analyze_with_finbert(news)


def _build_prompt(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    poly_data: dict[str, Any] | None = None,
) -> str:
    """Costruisce il prompt in italiano per l'analisi sentiment."""
    asset_names = ", ".join(a.get("display_name", a["symbol"]) for a in assets)

    news_block = ""
    for i, article in enumerate(news[:20], 1):  # Limit to 20 articles
        news_block += f"{i}. [{article['source']}] {article['title']}\n"
        if article.get("summary"):
            news_block += f"   {article['summary'][:200]}\n"

    # Optional Polymarket context
    poly_block = ""
    if poly_data and poly_data.get("market_count", 0) > 0:
        top_markets = poly_data.get("top_markets", [])[:3]
        if top_markets:
            market_lines = "\n".join(
                f"- {m['question']}: {m['prob_yes']:.0f}% probabilità SÌ"
                for m in top_markets
            )
            poly_block = f"""

DATI AGGIUNTIVI — MERCATI PREDITTIVI (Polymarket):
I seguenti eventi hanno queste probabilità di accadere secondo
scommettitori reali con denaro in gioco:

{market_lines}

Tieni conto di questi dati nella tua analisi del sentiment.
"""

    return f"""Sei un analista finanziario esperto. Analizza le seguenti notizie di mercato
e fornisci un'analisi del sentiment macro per un trader CFD retail che opera su: {asset_names}.

NOTIZIE RECENTI:
{news_block}
{poly_block}
Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (senza markdown, senza ```), con questa struttura esatta:
{{
  "sentiment_score": <numero da -3 a +3, dove -3 = estremamente ribassista, +3 = estremamente rialzista>,
  "sentiment_label": "<etichetta descrittiva in italiano>",
  "key_drivers": ["<driver 1>", "<driver 2>", "<driver 3>"],
  "directional_bias": "<BULLISH|BEARISH|NEUTRAL>",
  "risk_events": ["<evento rischio 1>", "<evento rischio 2>"],
  "confidence": <numero da 0 a 100>
}}

Regole:
- sentiment_score deve essere un numero con 1 decimale
- key_drivers deve avere esattamente 3 elementi, brevi e incisivi
- risk_events puo' essere vuoto [] se non ci sono rischi particolari oggi
- confidence riflette quanto sei sicuro dell'analisi (0-100)
- Rispondi SOLO con il JSON, nessun testo aggiuntivo"""


def _analyze_with_groq(
    news: list[dict[str, Any]],
    assets: list[dict[str, str]],
    model: str,
    api_key: str,
    poly_data: dict[str, Any] | None = None,
) -> SentimentResult:
    """Esegue l'analisi sentiment via Groq API con backoff esponenziale."""
    if Groq is None:
        raise RuntimeError("groq library not installed")

    client = Groq(api_key=api_key)
    prompt = _build_prompt(news, assets, poly_data=poly_data)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "Sei un analista finanziario. Rispondi solo in JSON valido.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=500,
            )
            raw = response.choices[0].message.content.strip()
            logger.debug("Groq raw response: %s", raw)

            # Clean response — remove markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            data = json.loads(raw)
            return SentimentResult(
                sentiment_score=float(data.get("sentiment_score", 0)),
                sentiment_label=str(data.get("sentiment_label", "Neutro")),
                key_drivers=list(data.get("key_drivers", []))[:3],
                directional_bias=str(data.get("directional_bias", "NEUTRAL")),
                risk_events=list(data.get("risk_events", [])),
                confidence=float(data.get("confidence", 50)),
                source="groq",
            )
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse Groq JSON (attempt %d): %s", attempt, exc)
            if attempt == MAX_RETRIES:
                raise
        except Exception as exc:
            if "rate_limit" in str(exc).lower() or "429" in str(exc):
                wait = BACKOFF_BASE**attempt
                logger.warning(
                    "Rate limited, retrying in %.1fs (attempt %d)", wait, attempt
                )
                time.sleep(wait)
                if attempt == MAX_RETRIES:
                    raise
            else:
                raise

    raise RuntimeError("Groq analysis failed after all retries")


def _analyze_with_finbert(news: list[dict[str, Any]]) -> SentimentResult:
    """Fallback sentiment analysis using FinBERT."""
    try:
        from transformers import pipeline
    except ImportError:
        logger.error("transformers library not installed for FinBERT fallback")
        return SentimentResult(
            sentiment_score=0.0,
            sentiment_label="Non disponibile",
            key_drivers=["Analisi non disponibile — installa transformers e torch"],
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
            sentiment_label="Errore modello",
            key_drivers=["Errore nel caricamento del modello FinBERT"],
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
    neutral_count = 0
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
        else:
            neutral_count += 1

    n = len(results)
    avg_score = total_score / n if n > 0 else 0
    # Map to -3 to +3 range
    sentiment_score = round(avg_score * 3, 1)
    sentiment_score = max(-3.0, min(3.0, sentiment_score))

    if sentiment_score > 1:
        label = "Rialzista"
        bias = "BULLISH"
    elif sentiment_score > 0.3:
        label = "Moderatamente Rialzista"
        bias = "BULLISH"
    elif sentiment_score < -1:
        label = "Ribassista"
        bias = "BEARISH"
    elif sentiment_score < -0.3:
        label = "Moderatamente Ribassista"
        bias = "BEARISH"
    else:
        label = "Neutro"
        bias = "NEUTRAL"

    confidence = (max(positive_count, negative_count) / n * 100) if n > 0 else 0

    # Extract top drivers from headlines
    drivers = [texts[i] for i in range(min(3, len(texts)))]

    return SentimentResult(
        sentiment_score=sentiment_score,
        sentiment_label=label,
        key_drivers=drivers,
        directional_bias=bias,
        confidence=round(confidence, 1),
        source="finbert",
    )


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
