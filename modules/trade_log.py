"""Trade log module — records trades and computes accuracy metrics.

Writes to trade_log.csv and provides accuracy analysis after 30+ trades.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRADE_LOG_FILE = "trade_log.csv"

COLUMNS = [
    "date", "asset", "llm_score", "tech_signal", "poly_signal",
    "direction", "entry_price", "exit_price", "outcome_pips",
    "llm_correct", "notes",
]


def _ensure_csv(path: str) -> None:
    """Create the CSV file with headers if it doesn't exist."""
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
        logger.info("Created trade log: %s", path)


def log_trade(
    asset: str,
    llm_score: float,
    tech_signal: str,
    poly_signal: str,
    direction: str,
    entry_price: float = 0.0,
    exit_price: float = 0.0,
    outcome_pips: float = 0.0,
    llm_correct: str = "N/A",
    notes: str = "",
    log_path: str = TRADE_LOG_FILE,
) -> str:
    """Append a trade record to the CSV log.

    Returns:
        Path to the log file.
    """
    _ensure_csv(log_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    row = [
        today, asset, f"{llm_score:+.1f}", tech_signal, poly_signal,
        direction, f"{entry_price:.2f}", f"{exit_price:.2f}",
        f"{outcome_pips:.1f}", llm_correct, notes,
    ]

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)

    logger.info("Trade logged: %s %s %s", today, asset, direction)
    return str(Path(log_path).resolve())


def log_flat_day(
    llm_score: float,
    tech_signal: str,
    poly_signal: str,
    notes: str = "",
    log_path: str = TRADE_LOG_FILE,
) -> str:
    """Log a FLAT day (no trade taken)."""
    return log_trade(
        asset="ALL",
        llm_score=llm_score,
        tech_signal=tech_signal,
        poly_signal=poly_signal,
        direction="FLAT",
        notes=notes,
        log_path=log_path,
    )


def compute_accuracy(log_path: str = TRADE_LOG_FILE) -> dict[str, Any] | None:
    """Compute accuracy metrics from the trade log.

    Returns None if fewer than 30 directional trades recorded.
    """
    if not os.path.exists(log_path):
        return None

    trades: list[dict[str, str]] = []
    with open(log_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)

    if not trades:
        return None

    total = len(trades)
    directional = [t for t in trades if t.get("direction") not in ("FLAT", "")]
    flat_days = total - len(directional)

    if len(directional) < 30:
        return {
            "total_trades": total,
            "directional_trades": len(directional),
            "flat_days": flat_days,
            "sufficient_data": False,
            "message": f"Servono almeno 30 trade direzionali per le statistiche "
                       f"({len(directional)}/30)",
        }

    correct = sum(1 for t in directional if t.get("llm_correct") == "TRUE")
    accuracy = (correct / len(directional)) * 100

    total_pips = sum(float(t.get("outcome_pips", 0) or 0) for t in directional)
    wins = sum(1 for t in directional if float(t.get("outcome_pips", 0) or 0) > 0)
    win_rate = (wins / len(directional)) * 100

    if accuracy < 50:
        rating = "Scarso — considera di disabilitare LLM (--no-llm)"
    elif accuracy < 55:
        rating = "Marginale — ottimizza prompt e parametri"
    elif accuracy < 60:
        rating = "Accettabile — il sistema funziona come filtro"
    else:
        rating = "Buono — il sistema aggiunge valore"

    return {
        "total_trades": total,
        "directional_trades": len(directional),
        "flat_days": flat_days,
        "sufficient_data": True,
        "llm_accuracy": round(accuracy, 1),
        "win_rate": round(win_rate, 1),
        "total_pips": round(total_pips, 1),
        "rating": rating,
    }


def print_accuracy_report(log_path: str = TRADE_LOG_FILE) -> None:
    """Print a formatted accuracy report to the terminal."""
    stats = compute_accuracy(log_path)
    if stats is None:
        print("  Nessun trade log trovato.")
        return

    print()
    print("=" * 60)
    print("  TRADE LOG — Statistiche Performance")
    print("=" * 60)
    print(f"  Trade totali:       {stats['total_trades']}")
    print(f"  Trade direzionali:  {stats['directional_trades']}")
    print(f"  Giorni flat:        {stats['flat_days']}")

    if not stats["sufficient_data"]:
        print(f"\n  {stats['message']}")
    else:
        print(f"\n  LLM Accuracy:       {stats['llm_accuracy']:.1f}%")
        print(f"  Win Rate:           {stats['win_rate']:.1f}%")
        print(f"  P&L totale (pips):  {stats['total_pips']:+.1f}")
        print(f"\n  Valutazione: {stats['rating']}")

    print("=" * 60)
    print()
