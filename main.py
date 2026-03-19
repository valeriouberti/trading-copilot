"""Trading Assistant — Entry point.

Orchestrates the full pipeline: fetch news, get price data,
analyze sentiment, and generate an HTML report.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

from modules.hallucination_guard import validate, validate_polymarket_consistency, determine_regime
from modules.news_fetcher import fetch_news
from modules.polymarket import get_polymarket_context
from modules.price_data import analyze_assets
from modules.report import generate_report, print_terminal_summary
from modules.sentiment import analyze_sentiment

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_FILE = "trading_assistant.log"


def setup_logging() -> None:
    """Configure logging to file and stderr."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # File handler — detailed
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(fh)

    # Console handler — warnings and above only
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(ch)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trading Assistant — analisi pre-market per trader CFD retail"
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        help="Override asset symbols (e.g., --assets ES=F GC=F)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        help="Override lookback hours for news (default from config)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip Groq LLM analysis, use only technicals",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open the report in the browser automatically",
    )
    parser.add_argument(
        "--no-polymarket",
        action="store_true",
        help="Skip Polymarket prediction markets fetch (for offline use)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def load_config(path: str) -> dict:
    """Load and validate the YAML config file."""
    config_path = Path(path)
    if not config_path.exists():
        print(f"ERRORE: File di configurazione '{path}' non trovato.")
        print("Crea il file config.yaml o specifica un percorso con --config.")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        print(f"ERRORE: Il file '{path}' e' vuoto o non valido.")
        sys.exit(1)

    return config


def main() -> None:
    args = parse_args()
    setup_logging()
    logger.info("Trading Assistant avviato")

    # 1. Load config
    config = load_config(args.config)
    assets = config.get("assets", [])
    feeds = config.get("rss_feeds", [])
    lookback_hours = args.hours or config.get("lookback_hours", 16)
    groq_model = config.get("groq_model", "llama-3.3-70b-versatile")

    # Override assets if specified via CLI
    if args.assets:
        assets = [{"symbol": s, "display_name": s} for s in args.assets]

    if not assets:
        print("ERRORE: Nessun asset configurato. Controlla config.yaml.")
        sys.exit(1)

    # 2. Fetch news
    print("[1/5] Recupero notizie dai feed RSS...")
    try:
        news = fetch_news(feeds, lookback_hours, assets=assets)
        print(f"      {len(news)} articoli trovati (ultime {lookback_hours}h)")
    except Exception as exc:
        logger.error("Errore nel recupero notizie: %s", exc)
        print(f"      ATTENZIONE: Errore nel recupero notizie: {exc}")
        news = []

    # 3. Get price data and technicals
    print("[2/5] Analisi tecnica assets...")
    try:
        asset_analyses = analyze_assets(assets)
        ok_count = sum(1 for a in asset_analyses if not a.error)
        print(f"      {ok_count}/{len(assets)} assets analizzati con successo")
    except Exception as exc:
        logger.error("Errore nell'analisi tecnica: %s", exc)
        print(f"      ERRORE: Analisi tecnica fallita: {exc}")
        asset_analyses = []

    # 3b. Polymarket prediction markets
    poly_data: dict | None = None
    if args.no_polymarket:
        print("[2b/5] Polymarket SALTATO (--no-polymarket)")
    else:
        print("[2b/5] Recupero dati Polymarket...")
        try:
            poly_data = get_polymarket_context(assets, groq_model=groq_model)
            p_count = poly_data.get("market_count", 0)
            p_signal = poly_data.get("signal", "NEUTRAL")
            print(f"      Polymarket: {p_count} mercati analizzati, signal={p_signal}")
            logger.info(
                "Polymarket: %d mercati analizzati, signal=%s", p_count, p_signal
            )
        except Exception as exc:
            logger.error("Errore nel recupero dati Polymarket: %s", exc)
            print(f"      ATTENZIONE: Errore Polymarket: {exc}")
            poly_data = None

    # 4. Sentiment analysis
    if args.no_llm:
        print("[3/5] Analisi sentiment SALTATA (--no-llm)")
        from modules.sentiment import SentimentResult

        sentiment = SentimentResult(
            sentiment_score=0.0,
            sentiment_label="N/A — LLM disabilitato",
            key_drivers=["Analisi LLM disabilitata dall'utente"],
            directional_bias="NEUTRAL",
            confidence=0.0,
            source="none",
        )
    else:
        print("[3/5] Analisi sentiment con LLM...")
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            print("      ATTENZIONE: GROQ_API_KEY non impostata. Uso FinBERT fallback.")
        try:
            sentiment = analyze_sentiment(news, assets, groq_model, poly_data=poly_data)
            print(
                f"      Sentiment: {sentiment.sentiment_score:+.1f} — {sentiment.sentiment_label}"
            )
            print(f"      Fonte: {sentiment.source}")
        except Exception as exc:
            logger.error("Errore nell'analisi sentiment: %s", exc)
            print(f"      ERRORE: Analisi sentiment fallita: {exc}")
            from modules.sentiment import SentimentResult

            sentiment = SentimentResult(
                sentiment_score=0.0,
                sentiment_label="Errore",
                key_drivers=["Errore nell'analisi del sentiment"],
                directional_bias="NEUTRAL",
                confidence=0.0,
                error=str(exc),
            )

    # 4b. Validation (including Polymarket consistency)
    print("[4/5] Validazione segnali...")
    validation = validate(sentiment, news, asset_analyses)
    validation_flags = list(validation.flags)

    # Add Polymarket consistency checks
    poly_flags = validate_polymarket_consistency(sentiment, poly_data, asset_analyses)
    validation_flags.extend(poly_flags)

    if validation_flags:
        for flag in validation_flags:
            print(f"      FLAG: {flag}")
    else:
        print("      Nessun flag di validazione")

    # 4c. Determine daily regime
    regime, regime_reason = determine_regime(sentiment, asset_analyses, validation_flags)
    print(f"      REGIME: {regime} — {regime_reason}")

    # 5. Generate report
    print("[5/5] Generazione report...")
    try:
        report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        report_path = generate_report(
            sentiment,
            asset_analyses,
            news,
            report_dir,
            poly_data=poly_data,
            validation_flags=validation_flags,
            regime=regime,
            regime_reason=regime_reason,
        )
        print(f"      Report salvato: {report_path}")
    except Exception as exc:
        logger.error("Errore nella generazione del report: %s", exc)
        print(f"      ERRORE: Generazione report fallita: {exc}")
        report_path = None

    # 6. Terminal summary
    print_terminal_summary(
        sentiment, asset_analyses, len(news),
        poly_data=poly_data, regime=regime, regime_reason=regime_reason,
    )

    # 7. Open in browser
    if report_path and not args.no_browser:
        try:
            webbrowser.open(f"file://{report_path}")
        except Exception:
            pass  # Non-critical

    logger.info("Trading Assistant completato")


if __name__ == "__main__":
    main()
