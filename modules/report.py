"""HTML report generator module.

Generates a dark-themed, self-contained HTML report with market analysis,
sentiment data, and technical indicators. Also prints a terminal summary.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def get_market_session() -> str:
    """Determine current US market session based on UTC time."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()

    if weekday >= 5:  # Saturday/Sunday
        return "Weekend — Mercati Chiusi"
    if 13 <= hour < 14:
        return "Pre-Market (08:00-09:30 ET)"
    elif 14 <= hour < 15 and now.minute < 30:
        return "Pre-Market (08:00-09:30 ET)"
    elif (14 <= hour and now.minute >= 30) or (15 <= hour < 21):
        return "Regular Session (09:30-16:00 ET)"
    elif 21 <= hour < 24 or 0 <= hour < 4:
        return "After-Hours"
    else:
        return "Pre-Market / Overnight"


def _sentiment_color(score: float) -> str:
    """Map sentiment score (-3 to +3) to a CSS color."""
    if score >= 2:
        return "#22c55e"  # Bright green
    elif score >= 1:
        return "#4ade80"  # Light green
    elif score >= 0.3:
        return "#86efac"  # Pale green
    elif score <= -2:
        return "#ef4444"  # Bright red
    elif score <= -1:
        return "#f87171"  # Light red
    elif score <= -0.3:
        return "#fca5a5"  # Pale red
    else:
        return "#9ca3af"  # Grey


def _signal_color(label: str) -> str:
    """Map a signal label to a CSS color."""
    if label == "BULLISH":
        return "#22c55e"
    elif label == "BEARISH":
        return "#ef4444"
    return "#eab308"  # Yellow/neutral


def _action_hint(composite: str, bias: str) -> str:
    """Generate action hint from technical score and LLM bias."""
    if composite == "BULLISH" and bias in ("BULLISH", ""):
        return "Cercare LONG"
    elif composite == "BEARISH" and bias in ("BEARISH", ""):
        return "Cercare SHORT"
    elif composite == "BULLISH" and bias == "BEARISH":
        return "Conflitto — Cautela"
    elif composite == "BEARISH" and bias == "BULLISH":
        return "Conflitto — Cautela"
    else:
        return "Attendere"


def _format_volume(volume: float) -> str:
    """Formatta il volume in formato leggibile ($XXXk o $X.Xm)."""
    if volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}m"
    elif volume >= 1_000:
        return f"${volume / 1_000:.0f}k"
    return f"${volume:,.0f}"


def _poly_signal_color(signal: str) -> str:
    """Colore CSS per il segnale Polymarket."""
    if signal == "BULLISH":
        return "#00c851"
    elif signal == "BEARISH":
        return "#ff4444"
    return "#888888"


def _category_badge(category: str) -> str:
    """Badge HTML colorato per la categoria del mercato."""
    colors = {
        "FED": "#3b82f6",
        "MACRO": "#f59e0b",
        "GEOPOLITICAL": "#ef4444",
        "CRYPTO": "#a855f7",
        "OTHER": "#6b7280",
    }
    color = colors.get(category, "#6b7280")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:0.8em;">{category}</span>'
    )


def _prob_color(prob: float) -> str:
    """Colore CSS per la probabilità SÌ."""
    if prob > 60:
        return "#ef4444"
    elif prob < 40:
        return "#22c55e"
    return "#9ca3af"


def _build_polymarket_section(
    poly_data: dict[str, Any] | None,
    validation_flags: list[str] | None = None,
) -> str:
    """Costruisce la sezione HTML del segnale Polymarket."""
    if not poly_data or poly_data.get("market_count", 0) == 0:
        return """
        <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;text-align:center;">
            <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Polymarket Signal</h2>
            <p style="color:#64748b;">Nessun dato Polymarket disponibile</p>
        </div>"""

    signal = poly_data.get("signal", "NEUTRAL")
    confidence = poly_data.get("confidence", 50)
    market_count = poly_data.get("market_count", 0)
    total_volume = poly_data.get("total_volume", 0)
    bullish_prob = poly_data.get("bullish_prob", 0)
    bearish_prob = poly_data.get("bearish_prob", 0)
    top_markets = poly_data.get("top_markets", [])
    sig_color = _poly_signal_color(signal)

    # Confidence bar
    conf_bar = f"""
    <div style="background:#374151;border-radius:6px;height:12px;width:200px;margin:8px auto;overflow:hidden;">
        <div style="background:{sig_color};height:100%;width:{confidence:.0f}%;border-radius:6px;"></div>
    </div>
    <div style="color:#94a3b8;font-size:0.85em;">{confidence:.0f}% confidenza</div>"""

    # Top markets table rows
    market_rows = ""
    for m in top_markets[:5]:
        question = m.get("question", "")
        truncated = (question[:57] + "...") if len(question) > 60 else question
        url = m.get("url", "")
        category = m.get("category", "OTHER")
        prob = m.get("prob_yes", 50)
        volume = m.get("volume_usd", 0)

        link = f'<a href="{url}" style="color:#93c5fd;text-decoration:none;" target="_blank">{truncated}</a>' if url else truncated
        prob_c = _prob_color(prob)
        vol_str = _format_volume(volume)

        market_rows += f"""
            <tr>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;color:#d1d5db;">{link}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;text-align:center;">{_category_badge(category)}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;text-align:center;color:{prob_c};font-weight:bold;">{prob:.1f}%</td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;text-align:right;color:#9ca3af;">{vol_str}</td>
            </tr>"""

    markets_table = ""
    if market_rows:
        markets_table = f"""
        <table style="width:100%;border-collapse:collapse;color:#e2e8f0;font-size:0.9em;margin-top:16px;">
            <thead>
                <tr style="border-bottom:2px solid #374151;">
                    <th style="padding:8px 10px;text-align:left;color:#94a3b8;">Domanda</th>
                    <th style="padding:8px 10px;text-align:center;color:#94a3b8;">Categoria</th>
                    <th style="padding:8px 10px;text-align:center;color:#94a3b8;">Prob. S&Igrave;</th>
                    <th style="padding:8px 10px;text-align:right;color:#94a3b8;">Volume</th>
                </tr>
            </thead>
            <tbody>
                {market_rows}
            </tbody>
        </table>"""

    # Confluence box
    confluence_html = ""
    flags = validation_flags or []
    triple = [f for f in flags if "TRIPLE_CONFLUENCE" in f]
    conflict = [f for f in flags if "POLYMARKET_CONFLICT" in f]

    if triple:
        confluence_html = f"""
        <div style="background:#1e3a2f;border:1px solid #22c55e;border-radius:8px;padding:12px;margin-top:16px;">
            <span style="color:#86efac;">&#9989; CONFLUENZA TRIPLA: LLM + Tecnici + Polymarket concordano &rarr; {signal}</span>
        </div>"""
    elif conflict:
        flag_msg = conflict[0]
        confluence_html = f"""
        <div style="background:#3d2f0f;border:1px solid #f59e0b;border-radius:8px;padding:12px;margin-top:16px;">
            <span style="color:#fcd34d;">&#9888;&#65039; CONFLITTO: {flag_msg}</span>
        </div>"""
    else:
        confluence_html = """
        <div style="background:#1f2937;border:1px solid #4b5563;border-radius:8px;padding:12px;margin-top:16px;">
            <span style="color:#9ca3af;">&#10134; Segnale neutro o parziale &mdash; usa come contesto</span>
        </div>"""

    return f"""
    <!-- POLYMARKET SIGNAL -->
    <div style="background:linear-gradient(135deg,#1e293b,#0f172a);border:2px solid {sig_color};border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;text-align:center;">Polymarket Signal</h2>
        <div style="text-align:center;">
            <div style="font-size:2.5em;font-weight:bold;color:{sig_color};margin:8px 0;">{signal}</div>
            {conf_bar}
            <div style="color:#64748b;font-size:0.85em;margin-top:4px;">
                Basato su {market_count} mercati predittivi &middot; Volume totale: ${total_volume:,.0f}
            </div>
        </div>

        <div style="display:flex;justify-content:center;gap:40px;margin-top:16px;">
            <div style="text-align:center;">
                <span style="color:#22c55e;font-size:1.1em;">&#128200; Prob. eventi BULLISH: {bullish_prob:.1f}%</span>
            </div>
            <div style="text-align:center;">
                <span style="color:#ef4444;font-size:1.1em;">&#128201; Prob. eventi BEARISH: {bearish_prob:.1f}%</span>
            </div>
        </div>

        {markets_table}
        {confluence_html}
    </div>"""


def _build_regime_section(regime: str, regime_reason: str) -> str:
    """Build the HTML section for the daily operational regime."""
    colors = {
        "LONG": ("#22c55e", "#1e3a2f", "Cercare SOLO setup LONG"),
        "SHORT": ("#ef4444", "#3d1f1f", "Cercare SOLO setup SHORT"),
        "NEUTRAL": ("#eab308", "#3d2f0f", "Nessun trade direzionale"),
    }
    color, bg, action = colors.get(regime, colors["NEUTRAL"])
    return f"""
    <!-- REGIME OPERATIVO -->
    <div style="background:{bg};border:2px solid {color};border-radius:12px;padding:20px;margin-bottom:24px;text-align:center;">
        <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Regime Operativo</h2>
        <div style="font-size:2.5em;font-weight:bold;color:{color};margin:8px 0;">{regime}</div>
        <div style="color:#cbd5e1;font-size:1em;margin-bottom:4px;">{action}</div>
        <div style="color:#64748b;font-size:0.85em;">{regime_reason}</div>
    </div>"""


def generate_report(
    sentiment: Any,
    asset_analyses: list[Any],
    news: list[dict[str, Any]],
    output_dir: str = "reports",
    poly_data: dict[str, Any] | None = None,
    validation_flags: list[str] | None = None,
    regime: str = "NEUTRAL",
    regime_reason: str = "",
) -> str:
    """Genera il report HTML e restituisce il percorso del file.

    Args:
        sentiment: SentimentResult object.
        asset_analyses: List of AssetAnalysis objects.
        news: List of news article dicts.
        output_dir: Directory to save the report.
        poly_data: Dati Polymarket opzionali da get_polymarket_context().
        validation_flags: Flag di validazione incluse quelle Polymarket.

    Returns:
        Absolute path to the generated HTML file.
    """
    now = datetime.now(timezone.utc)
    now_it = now.astimezone(ZoneInfo("Europe/Rome"))
    timestamp = now.strftime("%Y%m%d_%H%M")
    session = get_market_session()

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Build asset rows
    asset_rows = ""
    for a in asset_analyses:
        if a.error:
            asset_rows += f"""
            <tr>
                <td style="padding:10px;border-bottom:1px solid #374151;font-weight:bold;">{a.display_name}</td>
                <td colspan="9" style="padding:10px;border-bottom:1px solid #374151;color:#f87171;">
                    Errore: {a.error}
                </td>
            </tr>"""
            continue

        signals_map = {s.name: s for s in a.signals}
        rsi = signals_map.get("RSI")
        macd = signals_map.get("MACD")
        vwap = signals_map.get("VWAP")
        ema = signals_map.get("EMA_TREND")

        rsi_cell = f'<span style="color:{_signal_color(rsi.label)}">{rsi.value:.1f} ({rsi.label})</span>' if rsi and rsi.value else "N/A"
        macd_cell = f'<span style="color:{_signal_color(macd.label)}">{macd.label}</span>' if macd else "N/A"
        vwap_cell = f'<span style="color:{_signal_color(vwap.label)}">{vwap.detail}</span>' if vwap else "N/A"
        ema_cell = f'<span style="color:{_signal_color(ema.label)}">{ema.label}</span>' if ema else "N/A"

        score_color = _signal_color(a.composite_score)
        bias = getattr(sentiment, "directional_bias", "FLAT")
        hint = _action_hint(a.composite_score, bias)
        hint_color = "#22c55e" if "LONG" in hint else "#ef4444" if "SHORT" in hint else "#eab308"

        price_str = f"{a.price:,.2f}" if a.price else "N/A"
        change_str = f"{a.change_pct:+.2f}%" if a.change_pct is not None else ""
        change_color = "#22c55e" if (a.change_pct or 0) >= 0 else "#ef4444"

        # Poly signal cell
        if poly_data and poly_data.get("market_count", 0) > 0:
            p_sig = poly_data.get("signal", "NEUTRAL")
            p_conf = poly_data.get("confidence", 50)
            p_emoji = "\U0001f7e2" if p_sig == "BULLISH" else "\U0001f534" if p_sig == "BEARISH" else "\u26aa"
            p_label = "BULL" if p_sig == "BULLISH" else "BEAR" if p_sig == "BEARISH" else "NEU"
            poly_cell = f'<span style="color:{_poly_signal_color(p_sig)}">{p_emoji} {p_label} {p_conf:.0f}%</span>'
        else:
            poly_cell = '<span style="color:#64748b;">N/A</span>'

        asset_rows += f"""
            <tr>
                <td style="padding:10px;border-bottom:1px solid #374151;font-weight:bold;">{a.display_name}<br>
                    <span style="color:#9ca3af;font-size:0.85em;">{a.symbol}</span></td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{price_str}
                    <span style="color:{change_color};font-size:0.85em;"> {change_str}</span></td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{rsi_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{macd_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{vwap_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{ema_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">
                    <span style="color:{score_color};font-weight:bold;">{a.composite_score}</span>
                    <span style="color:#9ca3af;font-size:0.85em;"> ({a.confidence_pct}%)</span></td>
                <td style="padding:10px;border-bottom:1px solid #374151;">
                    <span style="color:{_signal_color(bias)}">{bias}</span></td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{poly_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">
                    <span style="font-weight:bold;color:{hint_color};">{hint}</span></td>
            </tr>"""

    # Build key drivers list
    drivers_html = ""
    for driver in getattr(sentiment, "key_drivers", []):
        drivers_html += f'<li style="margin-bottom:8px;">{driver}</li>\n'

    # Build risk events
    risk_events = getattr(sentiment, "risk_events", [])
    risk_html = ""
    if risk_events:
        risk_items = "".join(f"<li>{e}</li>" for e in risk_events)
        risk_html = f"""
        <div style="background:#7f1d1d;border:1px solid #dc2626;border-radius:8px;padding:16px;margin-bottom:24px;">
            <h2 style="color:#fca5a5;margin-top:0;">⚠ RISK EVENTS</h2>
            <ul style="color:#fecaca;margin:0;padding-left:20px;">{risk_items}</ul>
        </div>"""
    else:
        risk_html = """
        <div style="background:#1e3a2f;border:1px solid #22c55e;border-radius:8px;padding:16px;margin-bottom:24px;">
            <p style="color:#86efac;margin:0;">Nessun evento di rischio particolare segnalato.</p>
        </div>"""

    # Build news section
    news_rows = ""
    for article in news[:30]:
        pub = article["published_at"]
        if hasattr(pub, "strftime"):
            pub_str = pub.strftime("%H:%M %d/%m")
        else:
            pub_str = str(pub)
        news_rows += f"""
            <tr>
                <td style="padding:6px 10px;border-bottom:1px solid #1f2937;color:#d1d5db;">{article['title']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #1f2937;color:#9ca3af;">{article['source']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #1f2937;color:#9ca3af;white-space:nowrap;">{pub_str}</td>
            </tr>"""

    score = getattr(sentiment, "sentiment_score", 0)
    score_color = _sentiment_color(score)
    score_label = getattr(sentiment, "sentiment_label", "Neutro")
    source = getattr(sentiment, "source", "N/A")
    confidence = getattr(sentiment, "confidence", 0)

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Assistant Report — {now_it.strftime('%d/%m/%Y %H:%M')} IT</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;">
<div style="max-width:1200px;margin:0 auto;padding:24px;">

    <!-- HEADER -->
    <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;">
        <div>
            <h1 style="margin:0;font-size:1.5em;color:#f1f5f9;">Trading Assistant Report</h1>
            <p style="margin:4px 0 0;color:#94a3b8;">
                {now_it.strftime('%d %B %Y — %H:%M')} (ora italiana) &middot; {now.strftime('%H:%M')} UTC
            </p>
        </div>
        <div style="text-align:right;">
            <span style="background:#334155;color:#cbd5e1;padding:6px 16px;border-radius:20px;font-size:0.9em;">
                {session}
            </span>
        </div>
    </div>

    <!-- SENTIMENT MACRO -->
    <div style="background:linear-gradient(135deg,#1e293b,#0f172a);border:2px solid {score_color};border-radius:12px;padding:24px;margin-bottom:24px;text-align:center;">
        <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Sentiment Macro</h2>
        <div style="font-size:4em;font-weight:bold;color:{score_color};margin:8px 0;">
            {score:+.1f}
        </div>
        <div style="font-size:1.2em;color:{score_color};margin-bottom:8px;">{score_label}</div>
        <div style="color:#64748b;font-size:0.85em;">
            Fonte: {source.upper()} | Confidenza: {confidence:.0f}%
        </div>
    </div>

    {_build_polymarket_section(poly_data, validation_flags)}

    {_build_regime_section(regime, regime_reason)}

    <!-- KEY DRIVERS -->
    <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;">
        <h2 style="margin:0 0 12px;color:#f1f5f9;">Key Drivers</h2>
        <ul style="margin:0;padding-left:20px;color:#cbd5e1;">
            {drivers_html}
        </ul>
    </div>

    <!-- RISK EVENTS -->
    {risk_html}

    <!-- ASSETS TABLE -->
    <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;overflow-x:auto;">
        <h2 style="margin:0 0 16px;color:#f1f5f9;">Analisi Assets</h2>
        <table style="width:100%;border-collapse:collapse;color:#e2e8f0;font-size:0.9em;">
            <thead>
                <tr style="border-bottom:2px solid #374151;">
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Asset</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Prezzo</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">RSI</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">MACD</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">vs VWAP</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">EMA Trend</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Score Tecnico</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">LLM Bias</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Poly Signal</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Azione</th>
                </tr>
            </thead>
            <tbody>
                {asset_rows}
            </tbody>
        </table>
    </div>

    <!-- RAW NEWS -->
    <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;">
        <details>
            <summary style="cursor:pointer;color:#f1f5f9;font-size:1.1em;font-weight:bold;margin-bottom:12px;">
                Notizie Raw ({len(news)} articoli)
            </summary>
            <table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:0.85em;">
                <thead>
                    <tr style="border-bottom:1px solid #374151;">
                        <th style="padding:6px 10px;text-align:left;color:#94a3b8;">Titolo</th>
                        <th style="padding:6px 10px;text-align:left;color:#94a3b8;">Fonte</th>
                        <th style="padding:6px 10px;text-align:left;color:#94a3b8;">Ora</th>
                    </tr>
                </thead>
                <tbody>
                    {news_rows}
                </tbody>
            </table>
        </details>
    </div>

    <!-- FOOTER -->
    <div style="text-align:center;padding:16px;color:#64748b;font-size:0.8em;border-top:1px solid #1e293b;">
        <p>Solo uso informativo. Nessun consiglio finanziario.</p>
        <p>Generato da Trading Assistant</p>
    </div>

</div>
</body>
</html>"""

    filepath = os.path.join(output_dir, f"report_{timestamp}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    abs_path = str(Path(filepath).resolve())
    logger.info("Report saved to %s", abs_path)
    return abs_path


def print_terminal_summary(
    sentiment: Any,
    asset_analyses: list[Any],
    news_count: int,
    poly_data: dict[str, Any] | None = None,
    regime: str = "NEUTRAL",
    regime_reason: str = "",
    validation_flags: list[str] | None = None,
) -> None:
    """Stampa un riepilogo ASCII compatto nel terminale."""
    session = get_market_session()
    now = datetime.now(timezone.utc)
    now_it = now.astimezone(ZoneInfo("Europe/Rome"))

    print()
    print("=" * 70)
    print(f"  TRADING ASSISTANT — {now_it.strftime('%d/%m/%Y %H:%M')} IT ({now.strftime('%H:%M')} UTC)")
    print(f"  Sessione: {session}")
    print("=" * 70)

    score = getattr(sentiment, "sentiment_score", 0)
    label = getattr(sentiment, "sentiment_label", "N/A")
    bias = getattr(sentiment, "directional_bias", "FLAT")
    source = getattr(sentiment, "source", "N/A")

    print(f"\n  SENTIMENT MACRO: {score:+.1f} — {label} (bias: {bias}, fonte: {source})")
    print(f"  REGIME OPERATIVO: {regime} — {regime_reason}")

    drivers = getattr(sentiment, "key_drivers", [])
    if drivers:
        print("\n  KEY DRIVERS:")
        for d in drivers:
            print(f"    - {d}")

    risk_events = getattr(sentiment, "risk_events", [])
    if risk_events:
        print("\n  RISK EVENTS:")
        for e in risk_events:
            print(f"    ! {e}")

    # Validation flags and confluence status
    flags = validation_flags or []
    if flags:
        print("\n  VALIDAZIONE:")
        for flag in flags:
            if "TRIPLE_CONFLUENCE" in flag:
                print(f"    ✓ {flag}")
            elif "CONFLICT" in flag or "MISMATCH" in flag:
                print(f"    ✗ {flag}")
            else:
                print(f"    • {flag}")
    else:
        print("\n  VALIDAZIONE: OK — nessun flag")

    print(f"\n  {'Asset':<25} {'Prezzo':>12} {'Score':<10} {'Azione':<20}")
    print("  " + "-" * 67)

    for a in asset_analyses:
        if a.error:
            print(f"  {a.display_name:<25} {'ERROR':>12} {'':10} {a.error[:20]}")
            continue
        price_str = f"{a.price:,.2f}" if a.price else "N/A"
        hint = _action_hint(a.composite_score, bias)
        print(f"  {a.display_name:<25} {price_str:>12} {a.composite_score:<10} {hint:<20}")

    print(f"\n  Notizie analizzate: {news_count}")

    if poly_data and poly_data.get("market_count", 0) > 0:
        p_sig = poly_data.get("signal", "NEUTRAL")
        p_conf = poly_data.get("confidence", 50)
        p_count = poly_data.get("market_count", 0)
        print(f"  POLYMARKET: {p_sig} ({p_conf:.0f}%) — {p_count} markets analyzed")

    print("=" * 70)
    print("  Solo uso informativo. Nessun consiglio finanziario.")
    print("=" * 70)
    print()
