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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

from modules.economic_calendar import fetch_calendar
from modules.hallucination_guard import (
    determine_regime,
    validate,
    validate_polymarket_consistency,
)
from modules.news_fetcher import fetch_news
from modules.polymarket import get_polymarket_context
from modules.price_data import analyze_assets, compute_correlation_matrix, filter_correlated_assets
from modules.report import generate_report, print_terminal_summary
from modules.sentiment import analyze_sentiment
from modules.trade_log import log_flat_day, log_trade, print_accuracy_report

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
        description="Trading Assistant — pre-market analysis for retail CFD traders"
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
    parser.add_argument(
        "--log-trade",
        action="store_true",
        help="Log today's analysis as a trade record in trade_log.csv",
    )
    parser.add_argument(
        "--review-trades",
        action="store_true",
        help="Print trade accuracy report and exit",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def load_config(path: str) -> dict:
    """Load and validate the YAML config file."""
    config_path = Path(path)
    if not config_path.exists():
        print(f"ERROR: Configuration file '{path}' not found.")
        print("Create the file config.yaml or specify a path with --config.")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        print(f"ERROR: File '{path}' is empty or invalid.")
        sys.exit(1)

    # Normalize: support both "seed_assets" (new) and "assets" (old)
    if "seed_assets" in config and "assets" not in config:
        config["assets"] = config.pop("seed_assets")

    # Validate required keys
    errors: list[str] = []
    if not config.get("assets"):
        errors.append("'assets' (or 'seed_assets') missing or empty")
    else:
        for i, asset in enumerate(config["assets"]):
            if not asset.get("symbol"):
                errors.append(f"assets[{i}]: 'symbol' missing")

    if not config.get("rss_feeds"):
        errors.append("'rss_feeds' missing or empty")
    else:
        for i, feed in enumerate(config["rss_feeds"]):
            if not feed.get("url"):
                errors.append(f"rss_feeds[{i}]: 'url' missing")

    hours = config.get("lookback_hours", 16)
    if not isinstance(hours, (int, float)) or hours <= 0 or hours > 168:
        errors.append(f"'lookback_hours' must be between 1 and 168 (found: {hours})")

    if errors:
        print("ERROR in configuration:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    return config


def main() -> None:
    args = parse_args()
    setup_logging()
    logger.info("Trading Assistant started")

    # Handle --review-trades (print and exit)
    if args.review_trades:
        print_accuracy_report()
        return

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
        print("ERROR: No assets configured. Check config.yaml.")
        sys.exit(1)

    # 2. Parallel I/O: fetch news, price data, Polymarket, and calendar
    print(
        "[1/5] Fetching data in parallel (news + technicals + Polymarket + calendar)..."
    )
    news: list = []
    asset_analyses: list = []
    poly_data: dict | None = None
    calendar_data = None

    def _fetch_news_task():
        return fetch_news(feeds, lookback_hours, assets=assets)

    def _fetch_technicals_task():
        return analyze_assets(assets)

    def _fetch_polymarket_task():
        if args.no_polymarket:
            return None
        return get_polymarket_context(assets, groq_model=groq_model)

    def _fetch_calendar_task():
        return fetch_calendar()

    tasks = {
        "news": _fetch_news_task,
        "technicals": _fetch_technicals_task,
        "polymarket": _fetch_polymarket_task,
        "calendar": _fetch_calendar_task,
    }

    progress = tqdm(total=len(tasks), desc="  Data", unit="src", leave=False)
    results: dict = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_map = {executor.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                logger.error("Error in task '%s': %s", name, exc)
                print(f"      WARNING: Error in {name}: {exc}")
                results[name] = [] if name != "polymarket" else None
            progress.update(1)
    progress.close()

    news = results.get("news", [])
    asset_analyses = results.get("technicals", [])
    poly_data = results.get("polymarket")
    calendar_data = results.get("calendar")

    ok_count = sum(1 for a in asset_analyses if not getattr(a, "error", True))
    print(
        f"      News: {len(news)} articles | Technicals: {ok_count}/{len(assets)} assets",
        end="",
    )
    if poly_data and poly_data.get("market_count", 0) > 0:
        print(
            f" | Polymarket: {poly_data['market_count']} markets ({poly_data.get('signal', 'N/A')})"
        )
    elif args.no_polymarket:
        print(" | Polymarket: SKIPPED", end="")
    else:
        print(" | Polymarket: N/A", end="")

    # Calendar summary
    if calendar_data and getattr(calendar_data, "high_impact_today", []):
        hi_count = len(calendar_data.high_impact_today)
        print(f" | Calendar: {hi_count} high-impact")
    else:
        print(" | Calendar: clear")

    # 3. Sentiment analysis
    if args.no_llm:
        print("[2/5] Sentiment analysis SKIPPED (--no-llm)")
        from modules.sentiment import SentimentResult

        sentiment = SentimentResult(
            sentiment_score=0.0,
            sentiment_label="N/A — LLM disabled",
            key_drivers=["LLM analysis disabled by user"],
            directional_bias="NEUTRAL",
            confidence=0.0,
            source="none",
        )
    else:
        print("[2/5] Sentiment analysis with LLM...")
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            print("      WARNING: GROQ_API_KEY not set. Using FinBERT fallback.")
        try:
            sentiment = analyze_sentiment(news, assets, groq_model, poly_data=poly_data)
            print(
                f"      Sentiment: {sentiment.sentiment_score:+.1f} — {sentiment.sentiment_label}"
            )
            print(f"      Source: {sentiment.source}")
        except Exception as exc:
            logger.error("Error in sentiment analysis: %s", exc)
            print(f"      ERROR: Sentiment analysis failed: {exc}")
            from modules.sentiment import SentimentResult

            sentiment = SentimentResult(
                sentiment_score=0.0,
                sentiment_label="Error",
                key_drivers=["Error in sentiment analysis"],
                directional_bias="NEUTRAL",
                confidence=0.0,
                error=str(exc),
            )

    # 4. Validation (including Polymarket consistency)
    print("[3/5] Signal validation...")
    validation = validate(sentiment, news, asset_analyses)
    validation_flags = list(validation.flags)

    # Add Polymarket consistency checks
    poly_flags = validate_polymarket_consistency(sentiment, poly_data, asset_analyses)
    validation_flags.extend(poly_flags)

    if validation_flags:
        for flag in validation_flags:
            print(f"      FLAG: {flag}")
    else:
        print("      No validation flags")

    # 4b. Determine daily regime
    regime, regime_reason = determine_regime(
        sentiment, asset_analyses, validation_flags
    )

    # 4c. Calendar regime override — force NEUTRAL if high-impact event imminent
    if calendar_data and getattr(calendar_data, "regime_override", False):
        if regime != "NEUTRAL":
            original_regime = regime
            regime = "NEUTRAL"
            regime_reason = (
                f"{calendar_data.override_reason} "
                f"(was {original_regime}: {regime_reason})"
            )
            print(f"      CALENDAR OVERRIDE: {original_regime} → NEUTRAL")

    print(f"      REGIME: {regime} — {regime_reason}")

    # 4d. Correlation filter
    corr_matrix = compute_correlation_matrix(asset_analyses)
    filtered_symbols = filter_correlated_assets(asset_analyses, corr_matrix)
    if filtered_symbols:
        print(f"      CORR-SKIP: {', '.join(filtered_symbols)} (correlated same-direction)")

    # 5. Generate report
    print("[4/5] Generating report...")
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
            calendar_data=calendar_data,
            corr_matrix=corr_matrix,
            filtered_symbols=filtered_symbols,
        )
        print(f"      Report saved: {report_path}")
    except Exception as exc:
        logger.error("Error in report generation: %s", exc)
        print(f"      ERROR: Report generation failed: {exc}")
        report_path = None

    # 5b. Trade log (if --log-trade)
    if args.log_trade:
        print("[5/5] Recording trade log...")
        try:
            tech_signal = "N/A"
            if asset_analyses:
                tech_signal = asset_analyses[0].composite_score
            poly_signal = poly_data.get("signal", "N/A") if poly_data else "N/A"
            direction = getattr(sentiment, "directional_bias", "NEUTRAL")

            if direction == "NEUTRAL":
                path = log_flat_day(
                    llm_score=sentiment.sentiment_score,
                    tech_signal=tech_signal,
                    poly_signal=poly_signal,
                    notes=regime_reason,
                )
            else:
                path = log_trade(
                    asset=assets[0]["symbol"] if assets else "N/A",
                    llm_score=sentiment.sentiment_score,
                    tech_signal=tech_signal,
                    poly_signal=poly_signal,
                    direction=direction,
                    notes=regime_reason,
                )
            print(f"      Trade log saved: {path}")
        except Exception as exc:
            logger.error("Error in trade log: %s", exc)
            print(f"      ERROR: Trade log failed: {exc}")
    else:
        print("[5/5] Trade log not requested (use --log-trade)")

    # 6. Terminal summary
    print_terminal_summary(
        sentiment,
        asset_analyses,
        len(news),
        poly_data=poly_data,
        regime=regime,
        regime_reason=regime_reason,
        validation_flags=validation_flags,
        calendar_data=calendar_data,
        corr_matrix=corr_matrix,
        filtered_symbols=filtered_symbols,
    )

    # 7. Open in browser
    if report_path and not args.no_browser:
        try:
            webbrowser.open(f"file://{report_path}")
        except Exception:
            pass  # Non-critical

    logger.info("Trading Assistant completed")


if __name__ == "__main__":
    main()
