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
        return "Weekend — Markets Closed"
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
        return "Look for LONG"
    elif composite == "BEARISH" and bias in ("BEARISH", ""):
        return "Look for SHORT"
    elif composite == "BULLISH" and bias == "BEARISH":
        return "Conflict — Caution"
    elif composite == "BEARISH" and bias == "BULLISH":
        return "Conflict — Caution"
    else:
        return "Wait"


def _format_volume(volume: float) -> str:
    """Format volume in readable format ($XXXk or $X.Xm)."""
    if volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}m"
    elif volume >= 1_000:
        return f"${volume / 1_000:.0f}k"
    return f"${volume:,.0f}"


def _poly_signal_color(signal: str) -> str:
    """CSS color for the Polymarket signal."""
    if signal == "BULLISH":
        return "#00c851"
    elif signal == "BEARISH":
        return "#ff4444"
    return "#888888"


def _category_badge(category: str) -> str:
    """Colored HTML badge for the market category."""
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
    """CSS color for YES probability."""
    if prob > 60:
        return "#ef4444"
    elif prob < 40:
        return "#22c55e"
    return "#9ca3af"


def _build_polymarket_section(
    poly_data: dict[str, Any] | None,
    validation_flags: list[str] | None = None,
) -> str:
    """Build the HTML section for the Polymarket signal."""
    if not poly_data or poly_data.get("market_count", 0) == 0:
        return """
        <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;text-align:center;">
            <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Polymarket Signal</h2>
            <p style="color:#64748b;">No Polymarket data available</p>
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
    <div style="color:#94a3b8;font-size:0.85em;">{confidence:.0f}% confidence</div>"""

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
                    <th style="padding:8px 10px;text-align:left;color:#94a3b8;">Question</th>
                    <th style="padding:8px 10px;text-align:center;color:#94a3b8;">Category</th>
                    <th style="padding:8px 10px;text-align:center;color:#94a3b8;">Prob. YES</th>
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
            <span style="color:#86efac;">&#9989; TRIPLE CONFLUENCE: LLM + Technicals + Polymarket agree &rarr; {signal}</span>
        </div>"""
    elif conflict:
        flag_msg = conflict[0]
        confluence_html = f"""
        <div style="background:#3d2f0f;border:1px solid #f59e0b;border-radius:8px;padding:12px;margin-top:16px;">
            <span style="color:#fcd34d;">&#9888;&#65039; CONFLICT: {flag_msg}</span>
        </div>"""
    else:
        confluence_html = """
        <div style="background:#1f2937;border:1px solid #4b5563;border-radius:8px;padding:12px;margin-top:16px;">
            <span style="color:#9ca3af;">&#10134; Neutral or partial signal &mdash; use as context</span>
        </div>"""

    return f"""
    <!-- POLYMARKET SIGNAL -->
    <div style="background:linear-gradient(135deg,#1e293b,#0f172a);border:2px solid {sig_color};border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;text-align:center;">Polymarket Signal</h2>
        <div style="text-align:center;">
            <div style="font-size:2.5em;font-weight:bold;color:{sig_color};margin:8px 0;">{signal}</div>
            {conf_bar}
            <div style="color:#64748b;font-size:0.85em;margin-top:4px;">
                Based on {market_count} prediction markets &middot; Total volume: ${total_volume:,.0f}
            </div>
        </div>

        <div style="display:flex;justify-content:center;gap:40px;margin-top:16px;">
            <div style="text-align:center;">
                <span style="color:#22c55e;font-size:1.1em;">&#128200; BULLISH event prob.: {bullish_prob:.1f}%</span>
            </div>
            <div style="text-align:center;">
                <span style="color:#ef4444;font-size:1.1em;">&#128201; BEARISH event prob.: {bearish_prob:.1f}%</span>
            </div>
        </div>

        {markets_table}
        {confluence_html}
    </div>"""


def _build_regime_section(regime: str, regime_reason: str) -> str:
    """Build the HTML section for the daily operational regime."""
    colors = {
        "LONG": ("#22c55e", "#1e3a2f", "Look ONLY for LONG setups"),
        "SHORT": ("#ef4444", "#3d1f1f", "Look ONLY for SHORT setups"),
        "NEUTRAL": ("#eab308", "#3d2f0f", "No directional trades"),
    }
    color, bg, action = colors.get(regime, colors["NEUTRAL"])
    return f"""
    <!-- OPERATIONAL REGIME -->
    <div style="background:{bg};border:2px solid {color};border-radius:12px;padding:20px;margin-bottom:24px;text-align:center;">
        <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Operational Regime</h2>
        <div style="font-size:2.5em;font-weight:bold;color:{color};margin:8px 0;">{regime}</div>
        <div style="color:#cbd5e1;font-size:1em;margin-bottom:4px;">{action}</div>
        <div style="color:#64748b;font-size:0.85em;">{regime_reason}</div>
    </div>"""


def _build_calendar_section(calendar_data: Any | None) -> str:
    """Build the HTML section for the economic calendar."""
    if not calendar_data:
        return ""

    events_today = getattr(calendar_data, "events_today", [])
    high_impact = getattr(calendar_data, "high_impact_today", [])
    override = getattr(calendar_data, "regime_override", False)
    override_reason = getattr(calendar_data, "override_reason", "")
    next_hi = getattr(calendar_data, "next_high_impact", None)
    hours_to = getattr(calendar_data, "hours_to_next", None)

    if not events_today:
        return """
        <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;">
            <h2 style="margin:0 0 12px;color:#f1f5f9;">Economic Calendar</h2>
            <p style="color:#86efac;">No economic events scheduled today.</p>
        </div>"""

    # Override warning
    override_html = ""
    if override:
        override_html = f"""
        <div style="background:#7f1d1d;border:1px solid #dc2626;border-radius:8px;padding:12px;margin-bottom:16px;">
            <span style="color:#fca5a5;font-weight:bold;">&#9888; REGIME OVERRIDE: {override_reason}</span>
        </div>"""

    # Next high-impact countdown
    countdown_html = ""
    if next_hi and hours_to is not None:
        if hours_to < 1:
            time_str = f"{int(hours_to * 60)} min"
        else:
            time_str = f"{hours_to:.1f}h"
        urgency_color = "#ef4444" if hours_to <= 2 else "#f59e0b" if hours_to <= 4 else "#22c55e"
        countdown_html = f"""
        <div style="text-align:center;margin-bottom:16px;">
            <span style="color:{urgency_color};font-size:1.3em;font-weight:bold;">
                Next: {next_hi.title} ({next_hi.country}) in {time_str}
            </span>
        </div>"""

    # Event rows
    event_rows = ""
    for e in events_today:
        impact_colors = {"High": "#ef4444", "Medium": "#f59e0b", "Low": "#6b7280"}
        impact_color = impact_colors.get(e.impact, "#6b7280")
        hours = e.hours_away
        if hours < 0:
            time_cell = '<span style="color:#6b7280;">Passed</span>'
        elif hours < 1:
            time_cell = f'<span style="color:#ef4444;font-weight:bold;">{int(hours * 60)}m</span>'
        else:
            time_cell = f'<span style="color:#cbd5e1;">{hours:.1f}h</span>'

        event_rows += f"""
            <tr>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;color:#d1d5db;">{e.title}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;">{e.country}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;">
                    <span style="color:{impact_color};font-weight:bold;">{e.impact}</span></td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;text-align:center;">{time_cell}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;color:#9ca3af;">{e.forecast}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #374151;color:#9ca3af;">{e.previous}</td>
            </tr>"""

    border_color = "#dc2626" if high_impact else "#374151"
    return f"""
    <!-- ECONOMIC CALENDAR -->
    <div style="background:#1e293b;border:2px solid {border_color};border-radius:12px;padding:20px;margin-bottom:24px;">
        <h2 style="margin:0 0 12px;color:#f1f5f9;">Economic Calendar ({len(events_today)} events, {len(high_impact)} high-impact)</h2>
        {override_html}
        {countdown_html}
        <table style="width:100%;border-collapse:collapse;color:#e2e8f0;font-size:0.9em;">
            <thead>
                <tr style="border-bottom:2px solid #374151;">
                    <th style="padding:8px 10px;text-align:left;color:#94a3b8;">Event</th>
                    <th style="padding:8px 10px;text-align:left;color:#94a3b8;">Country</th>
                    <th style="padding:8px 10px;text-align:left;color:#94a3b8;">Impact</th>
                    <th style="padding:8px 10px;text-align:center;color:#94a3b8;">In</th>
                    <th style="padding:8px 10px;text-align:left;color:#94a3b8;">Forecast</th>
                    <th style="padding:8px 10px;text-align:left;color:#94a3b8;">Previous</th>
                </tr>
            </thead>
            <tbody>
                {event_rows}
            </tbody>
        </table>
    </div>"""


def _build_key_levels_section(asset_analyses: list[Any]) -> str:
    """Build the HTML section for key S/R levels."""
    has_levels = any(
        getattr(a, "key_levels", None) is not None
        and getattr(a, "error", None) is None
        for a in asset_analyses
    )
    if not has_levels:
        return ""

    cards = ""
    for a in asset_analyses:
        kl = getattr(a, "key_levels", None)
        if not kl or getattr(a, "error", None):
            continue

        price = getattr(a, "price", None)
        if not price:
            continue

        # Build level rows, sorted by value
        all_levels = kl.all_levels()
        all_levels.sort(key=lambda nv: nv[1], reverse=True)

        level_rows = ""
        for name, val in all_levels:
            dist_pct = ((price - val) / price) * 100
            if abs(dist_pct) < 0.3:
                row_bg = "background:#374151;"
                dist_color = "#f59e0b"
                dist_label = "AT LEVEL"
            elif dist_pct > 0:
                row_bg = ""
                dist_color = "#22c55e"
                dist_label = f"{dist_pct:+.2f}%"
            else:
                row_bg = ""
                dist_color = "#ef4444"
                dist_label = f"{dist_pct:+.2f}%"

            # Highlight nearest level
            is_nearest = (kl.nearest_level is not None and abs(val - kl.nearest_level) < 0.001)
            name_style = "font-weight:bold;color:#f1f5f9;" if is_nearest else "color:#94a3b8;"

            level_rows += f"""
                <tr style="{row_bg}">
                    <td style="padding:4px 8px;border-bottom:1px solid #1f2937;">
                        <span style="{name_style}">{name}</span></td>
                    <td style="padding:4px 8px;border-bottom:1px solid #1f2937;text-align:right;color:#cbd5e1;">
                        {val:,.2f}</td>
                    <td style="padding:4px 8px;border-bottom:1px solid #1f2937;text-align:right;">
                        <span style="color:{dist_color};">{dist_label}</span></td>
                </tr>"""

        # Price position indicator
        nearest_info = ""
        if kl.nearest_level_name and kl.nearest_level_dist_pct is not None:
            dist = abs(kl.nearest_level_dist_pct)
            if dist < 0.3:
                warn_color = "#ef4444"
                warn_text = f"AT {kl.nearest_level_name} ({kl.nearest_level:,.2f})"
            elif dist < 0.7:
                warn_color = "#f59e0b"
                warn_text = f"Near {kl.nearest_level_name} ({dist:.2f}% away)"
            else:
                warn_color = "#22c55e"
                warn_text = f"Clear of levels (nearest: {kl.nearest_level_name} at {dist:.2f}%)"
            nearest_info = f'<div style="color:{warn_color};font-size:0.85em;margin-top:8px;">{warn_text}</div>'

        cards += f"""
            <div style="background:#0f172a;border:1px solid #374151;border-radius:8px;padding:16px;min-width:250px;flex:1;">
                <h3 style="margin:0 0 8px;color:#f1f5f9;font-size:1em;">{a.display_name}
                    <span style="color:#9ca3af;font-size:0.85em;"> @ {price:,.2f}</span></h3>
                <table style="width:100%;border-collapse:collapse;font-size:0.85em;">
                    <thead>
                        <tr>
                            <th style="padding:4px 8px;text-align:left;color:#64748b;">Level</th>
                            <th style="padding:4px 8px;text-align:right;color:#64748b;">Price</th>
                            <th style="padding:4px 8px;text-align:right;color:#64748b;">Dist.</th>
                        </tr>
                    </thead>
                    <tbody>{level_rows}</tbody>
                </table>
                {nearest_info}
            </div>"""

    return f"""
    <!-- KEY LEVELS -->
    <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;">
        <h2 style="margin:0 0 16px;color:#f1f5f9;">Key Levels (S/R)</h2>
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
            {cards}
        </div>
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
    calendar_data: Any | None = None,
) -> str:
    """Generate the HTML report and return the file path.

    Args:
        sentiment: SentimentResult object.
        asset_analyses: List of AssetAnalysis objects.
        news: List of news article dicts.
        output_dir: Directory to save the report.
        poly_data: Optional Polymarket data from get_polymarket_context().
        validation_flags: Validation flags including Polymarket ones.
        calendar_data: Optional CalendarData from economic calendar.

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
                <td colspan="13" style="padding:10px;border-bottom:1px solid #374151;color:#f87171;">
                    Error: {a.error}
                </td>
            </tr>"""
            continue

        signals_map = {s.name: s for s in a.signals}
        rsi = signals_map.get("RSI")
        macd = signals_map.get("MACD")
        bb = signals_map.get("BBANDS")
        stoch = signals_map.get("STOCH")
        vwap = signals_map.get("VWAP")
        ema = signals_map.get("EMA_TREND")
        adx = signals_map.get("ADX")

        rsi_cell = f'<span style="color:{_signal_color(rsi.label)}">{rsi.value:.1f} ({rsi.label})</span>' if rsi and rsi.value else "N/A"
        macd_cell = f'<span style="color:{_signal_color(macd.label)}">{macd.label}</span>' if macd else "N/A"
        bb_cell = f'<span style="color:{_signal_color(bb.label)}">{bb.label}<br><span style="font-size:0.8em;color:#9ca3af;">{bb.detail}</span></span>' if bb else "N/A"
        stoch_cell = f'<span style="color:{_signal_color(stoch.label)}">{stoch.value:.0f} ({stoch.label})</span>' if stoch and stoch.value is not None else "N/A"
        vwap_cell = f'<span style="color:{_signal_color(vwap.label)}">{vwap.detail}</span>' if vwap else "N/A"
        ema_cell = f'<span style="color:{_signal_color(ema.label)}">{ema.label}</span>' if ema else "N/A"
        adx_cell = f'<span style="color:#9ca3af;">{adx.detail}</span>' if adx else "N/A"

        score_color = _signal_color(a.composite_score)
        # v2: per-asset LLM bias (falls back to global bias)
        asset_biases = getattr(sentiment, "asset_biases", {})
        bias = asset_biases.get(a.symbol, getattr(sentiment, "directional_bias", "FLAT"))
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

        # Data source badge (only shown for non-yfinance)
        source_badge = ""
        data_src = getattr(a, "data_source", "yfinance")
        if data_src != "yfinance":
            source_badge = f' <span style="color:#6366f1;font-size:0.7em;">via {data_src}</span>'

        asset_rows += f"""
            <tr>
                <td style="padding:10px;border-bottom:1px solid #374151;font-weight:bold;">{a.display_name}<br>
                    <span style="color:#9ca3af;font-size:0.85em;">{a.symbol}</span>{source_badge}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{price_str}
                    <span style="color:{change_color};font-size:0.85em;"> {change_str}</span></td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{rsi_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{macd_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{bb_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{stoch_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{vwap_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{ema_cell}</td>
                <td style="padding:10px;border-bottom:1px solid #374151;">{adx_cell}</td>
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
            <p style="color:#86efac;margin:0;">No particular risk events reported.</p>
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
    score_label = getattr(sentiment, "sentiment_label", "Neutral")
    source = getattr(sentiment, "source", "N/A")
    confidence = getattr(sentiment, "confidence", 0)

    # FinBERT ensemble info
    finbert_score = getattr(sentiment, "finbert_score", None)
    finbert_agreement = getattr(sentiment, "finbert_agreement", "")
    finbert_html = ""
    if finbert_score is not None and finbert_agreement:
        agree_color = {"AGREE": "#22c55e", "PARTIAL": "#eab308", "DISAGREE": "#ef4444"}.get(finbert_agreement, "#9ca3af")
        finbert_html = (
            f'<div style="color:#64748b;font-size:0.85em;margin-top:4px;">'
            f'FinBERT: {finbert_score:+.1f} — '
            f'<span style="color:{agree_color};">{finbert_agreement}</span>'
            f'</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
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
                {now_it.strftime('%d %B %Y — %H:%M')} (Italian time) &middot; {now.strftime('%H:%M')} UTC
            </p>
        </div>
        <div style="text-align:right;">
            <span style="background:#334155;color:#cbd5e1;padding:6px 16px;border-radius:20px;font-size:0.9em;">
                {session}
            </span>
        </div>
    </div>

    <!-- MACRO SENTIMENT -->
    <div style="background:linear-gradient(135deg,#1e293b,#0f172a);border:2px solid {score_color};border-radius:12px;padding:24px;margin-bottom:24px;text-align:center;">
        <h2 style="margin:0 0 8px;color:#94a3b8;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Macro Sentiment</h2>
        <div style="font-size:4em;font-weight:bold;color:{score_color};margin:8px 0;">
            {score:+.1f}
        </div>
        <div style="font-size:1.2em;color:{score_color};margin-bottom:8px;">{score_label}</div>
        <div style="color:#64748b;font-size:0.85em;">
            Source: {source.upper()} | Confidence: {confidence:.0f}%
        </div>
        {finbert_html}
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

    {_build_calendar_section(calendar_data)}

    <!-- ASSETS TABLE -->
    <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;overflow-x:auto;">
        <h2 style="margin:0 0 16px;color:#f1f5f9;">Asset Analysis</h2>
        <table style="width:100%;border-collapse:collapse;color:#e2e8f0;font-size:0.9em;">
            <thead>
                <tr style="border-bottom:2px solid #374151;">
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Asset</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Price</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">RSI</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">MACD</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">BB</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Stoch</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">vs VWAP</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">EMA Trend</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">ADX</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Score</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">LLM Bias</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Poly</th>
                    <th style="padding:10px;text-align:left;color:#94a3b8;">Action</th>
                </tr>
            </thead>
            <tbody>
                {asset_rows}
            </tbody>
        </table>
    </div>

    {_build_key_levels_section(asset_analyses)}

    <!-- RAW NEWS -->
    <div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;">
        <details>
            <summary style="cursor:pointer;color:#f1f5f9;font-size:1.1em;font-weight:bold;margin-bottom:12px;">
                Raw News ({len(news)} articles)
            </summary>
            <table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:0.85em;">
                <thead>
                    <tr style="border-bottom:1px solid #374151;">
                        <th style="padding:6px 10px;text-align:left;color:#94a3b8;">Title</th>
                        <th style="padding:6px 10px;text-align:left;color:#94a3b8;">Source</th>
                        <th style="padding:6px 10px;text-align:left;color:#94a3b8;">Time</th>
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
        <p>For informational use only. Not financial advice.</p>
        <p>Generated by Trading Assistant</p>
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
    calendar_data: Any | None = None,
) -> None:
    """Print a compact ASCII summary to the terminal."""
    session = get_market_session()
    now = datetime.now(timezone.utc)
    now_it = now.astimezone(ZoneInfo("Europe/Rome"))

    print()
    print("=" * 70)
    print(f"  TRADING ASSISTANT — {now_it.strftime('%d/%m/%Y %H:%M')} IT ({now.strftime('%H:%M')} UTC)")
    print(f"  Session: {session}")
    print("=" * 70)

    score = getattr(sentiment, "sentiment_score", 0)
    label = getattr(sentiment, "sentiment_label", "N/A")
    bias = getattr(sentiment, "directional_bias", "FLAT")
    source = getattr(sentiment, "source", "N/A")

    finbert_score = getattr(sentiment, "finbert_score", None)
    finbert_agreement = getattr(sentiment, "finbert_agreement", "")
    finbert_str = f" | FinBERT: {finbert_score:+.1f} [{finbert_agreement}]" if finbert_score is not None else ""
    print(f"\n  SENTIMENT MACRO: {score:+.1f} — {label} (bias: {bias}, source: {source}){finbert_str}")
    print(f"  OPERATIONAL REGIME: {regime} — {regime_reason}")

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
        print("\n  VALIDATION:")
        for flag in flags:
            if "TRIPLE_CONFLUENCE" in flag:
                print(f"    ✓ {flag}")
            elif "CONFLICT" in flag or "MISMATCH" in flag:
                print(f"    ✗ {flag}")
            else:
                print(f"    • {flag}")
    else:
        print("\n  VALIDATION: OK — no flags")

    print(f"\n  {'Asset':<25} {'Price':>12} {'Score':<10} {'Action':<20}")
    print("  " + "-" * 67)

    asset_biases = getattr(sentiment, "asset_biases", {})
    for a in asset_analyses:
        if a.error:
            print(f"  {a.display_name:<25} {'ERROR':>12} {'':10} {a.error[:20]}")
            continue
        price_str = f"{a.price:,.2f}" if a.price else "N/A"
        a_bias = asset_biases.get(a.symbol, bias)
        hint = _action_hint(a.composite_score, a_bias)

        # Key level proximity note
        kl = getattr(a, "key_levels", None)
        level_note = ""
        if kl and kl.nearest_level_name and kl.nearest_level_dist_pct is not None:
            dist = abs(kl.nearest_level_dist_pct)
            if dist < 0.5:
                level_note = f" [!{kl.nearest_level_name} {dist:.1f}%]"

        print(f"  {a.display_name:<25} {price_str:>12} {a.composite_score:<10} {hint:<20}{level_note}")

    print(f"\n  News analyzed: {news_count}")

    if poly_data and poly_data.get("market_count", 0) > 0:
        p_sig = poly_data.get("signal", "NEUTRAL")
        p_conf = poly_data.get("confidence", 50)
        p_count = poly_data.get("market_count", 0)
        print(f"  POLYMARKET: {p_sig} ({p_conf:.0f}%) — {p_count} markets analyzed")

    # Calendar summary
    if calendar_data:
        hi_events = getattr(calendar_data, "high_impact_today", [])
        override = getattr(calendar_data, "regime_override", False)
        next_hi = getattr(calendar_data, "next_high_impact", None)
        if hi_events:
            print(f"\n  CALENDAR: {len(hi_events)} high-impact events today")
            if next_hi:
                hours = next_hi.hours_away
                time_str = f"{int(hours * 60)}m" if hours < 1 else f"{hours:.1f}h"
                print(f"    Next: {next_hi.title} ({next_hi.country}) in {time_str}")
            if override:
                print(f"    !! REGIME OVERRIDE — event imminent")
        else:
            print(f"\n  CALENDAR: No high-impact events today")

    print("=" * 70)
    print("  For informational use only. Not financial advice.")
    print("=" * 70)
    print()
