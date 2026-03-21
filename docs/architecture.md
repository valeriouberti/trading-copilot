# Architecture

## Overview

ETF Swing Trader is a FastAPI web application with two operational modes:

- **Web Dashboard** (`run_webapp.py`) -- interactive UI with cron-scheduled monitoring
- **CLI** (`main.py`) -- batch report generation

Both share the same core engine in `modules/`.

## Component Diagram

```
Browser
  |
  +-- HTTP (REST API)
  +-- WebSocket (/ws/signals)
  |
FastAPI (app/server.py)
  |
  +-- API Layer (app/api/)
  |     +-- analysis.py    -> /analyze, /chart, /ohlc, /quote, /screening
  |     +-- assets.py      -> /assets CRUD
  |     +-- monitor.py     -> /monitor start/stop/schedule
  |     +-- portfolio.py   -> /portfolio CRUD (positions)
  |     +-- trades.py      -> /trades CRUD + analytics + signals
  |     +-- settings.py    -> /settings/telegram
  |     +-- websocket.py   -> /ws/signals
  |     +-- health.py      -> /health
  |
  +-- Services (app/services/)
  |     +-- analyzer.py       Orchestrates the full analysis pipeline
  |     +-- monitor.py        Cron scheduler (08:00/13:00/17:00 CET)
  |     +-- signal_detector.py  7-condition entry checker (LONG-only)
  |     +-- notifier.py       Telegram + WebSocket push
  |     +-- cache.py          In-memory TTL cache
  |
  +-- Middleware
  |     +-- rate_limit.py   slowapi rate limiting
  |     +-- logging.py      Structured JSON logging + correlation ID
  |
  +-- Models (SQLAlchemy ORM)
        +-- Asset, Signal, Trade, Position, NotificationLog, TelegramConfig, RssFeed
        +-- Engine factory (SQLite or PostgreSQL)

Core Engine (modules/)
  +-- llm_client.py           Unified LLM client (Groq primary + Ollama fallback)
  +-- groq_client.py          Groq API singleton
  +-- price_data.py           yfinance OHLCV fetch + technical indicators
  +-- strategy.py             Shared strategy logic (regime, labeling, QS, SL/TP, commission check)
  +-- sentiment.py            Two-pass chain-of-thought LLM sentiment analysis
  +-- polymarket.py           Prediction market signal from Gamma API
  +-- news_fetcher.py         RSS aggregation + LLM summarization
  +-- economic_calendar.py    Forex Factory calendar scraper
  +-- hallucination_guard.py  Cross-signal validation
  +-- exceptions.py           Typed exception hierarchy
  +-- circuit_breaker.py      Circuit breaker for external APIs
  +-- retry.py                Tenacity retry decorators
  +-- data/
        +-- universe.py       ETF universe definition (8 UCITS ETFs)
        +-- yfinance_provider.py  yfinance data provider
        +-- registry.py       Data provider registry
```

## Data Flow: Full Analysis

```
POST /api/analyze/{symbol}
  |
  +-- [parallel]
  |     +-- _run_technicals()
  |     |     +-- _fetch_daily()       yfinance (10mo, 1d)
  |     |     +-- _fetch_weekly()      yfinance (2y, 1wk)
  |     |     +-- Compute: RSI, MACD, EMA, BBands, Stoch, ADX, ATR
  |     |     +-- Build: OHLC chart data, EMA20/50 overlays, key levels
  |     |     +-- Score: composite direction, quality score (5 checks), MTF alignment
  |     |
  |     +-- _run_news()
  |     |     +-- Fetch RSS feeds + asset-specific Yahoo Finance feed
  |     |     +-- Filter and deduplicate
  |     |
  |     +-- _run_polymarket()
  |     |     +-- Fetch events from Gamma API (tag_slugs per ETF category)
  |     |     +-- LLM classification (or keyword fallback)
  |     |     +-- Signal: BULLISH/BEARISH/NEUTRAL, confidence, top markets
  |     |
  |     +-- _run_calendar()       (cached globally, not per-symbol)
  |           +-- Forex Factory high-impact events
  |           +-- Regime override if major event imminent
  |
  +-- _run_sentiment()  (needs news, runs after Phase 1)
  |     +-- Two-pass LLM analysis via llm_client (Groq -> Ollama)
  |     +-- Pass 1: Chain-of-thought reasoning
  |     +-- Pass 2: Structured JSON extraction
  |     +-- Score: -3 to +3, bias, confidence, key drivers
  |
  +-- Determine regime (sentiment + technicals + polymarket)
  +-- Compute setup (entry, SL/TP in EUR, R:R, commission viability)
  +-- Generate trade thesis (LONG regime only)
  +-- Validate with hallucination guard
  +-- Return complete analysis JSON
```

## Data Flow: Scheduler

```
APScheduler CronTrigger (Europe/Rome timezone)
  |
  +-- Morning Briefing (08:00 CET)
  |     +-- analyze_single_asset() for all 8 ETFs (parallel)
  |     +-- Classify: BUY / SELL_IF_HOLDING / HOLD
  |     +-- Rank by quality score + composite confidence
  |     +-- Check open positions count (max 2)
  |     +-- Send Telegram daily briefing
  |     +-- Broadcast via WebSocket
  |
  +-- Midday Check (13:00 CET)
  |     +-- Query open positions from DB
  |     +-- Fetch current prices via yfinance
  |     +-- Check SL/TP hit, max hold (10 days) exceeded
  |     +-- Send SELL alert if triggered
  |
  +-- Closing Check (17:00 CET)
        +-- Same as midday + end-of-day summary
```

## Data Flow: Startup Catch-up

```
App start
  |
  +-- Check: was morning briefing sent today?
  |     +-- Query NotificationLog for today's briefing
  |
  +-- If missed AND before 17:30 CET:
        +-- Run quick briefing (technicals only)
        +-- skip_llm=True, skip_polymarket=True, skip_calendar=True
        +-- ~12 seconds vs 2+ minutes for full pipeline
```

## LLM Architecture

```
modules/llm_client.py
  |
  +-- llm_call(system_msg, user_msg, max_tokens, temperature)
  |     +-- Try Groq first (Qwen 3 32B, cloud, ~0.5s per call)
  |     +-- If rate-limited/unavailable: fallback to Ollama (Qwen 2.5 14B, local)
  |     +-- _strip_think(): removes Qwen 3 <think>...</think> reasoning blocks
  |     +--   Handles truncated think blocks (max_tokens cut off before </think>)
  |
  +-- Used by:
        +-- sentiment.py      (2 LLM calls: reasoning + extraction)
        +-- news_fetcher.py   (1 LLM call: news summarization)
        +-- polymarket.py     (1 LLM call: event classification)
```

## Database Schema

| Table | Purpose |
|-------|---------|
| `assets` | Configured ETFs (symbol, display_name) |
| `positions` | Open/closed positions with entry/exit, SL/TP, P&L in EUR |
| `signals` | Generated signals with entry/SL/TP and outcome tracking |
| `trades` | Trade journal entries with P&L |
| `notification_log` | Rate-limited notification history |
| `telegram_config` | Bot token, chat ID, enabled flag |
| `rss_feeds` | RSS feed URLs for news aggregation |

Supports SQLite (default, zero config) and PostgreSQL (via Docker).

## Caching Strategy

| Data | TTL | Key | Reason |
|------|-----|-----|--------|
| Price data | 60s | per-symbol | Frequently changing |
| News | 300s | per-symbol | Updates every few minutes |
| Sentiment | 600s | per-symbol | Stable within analysis window |
| Polymarket | 600s | per-symbol | Prediction markets move slowly |
| Calendar | 3600s | `_global` | Same for all assets, doesn't change intraday |

## Resilience

- **Typed exceptions**: `TransientError` (retryable) vs `PermanentError` (fail fast)
- **Retry with backoff**: tenacity decorators on all external API calls
- **Circuit breakers**: 3 failures -> circuit open for 5 minutes per API
- **Graceful degradation**: each pipeline stage can fail independently
- **LLM fallback chain**: Groq -> Ollama -> neutral sentiment
- **Think block handling**: strips Qwen 3 reasoning blocks, handles truncation
