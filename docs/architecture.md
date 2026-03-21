# Architecture

## Overview

Trading Copilot is a FastAPI web application with two operational modes:

- **Web Dashboard** (`run_webapp.py`) -- interactive UI with real-time monitoring
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
  |     +-- analysis.py    -> /analyze, /chart, /ohlc, /quote
  |     +-- assets.py      -> /assets CRUD
  |     +-- monitor.py     -> /monitor start/stop/status/budget
  |     +-- trades.py      -> /trades CRUD + analytics + signals
  |     +-- settings.py    -> /settings/telegram
  |     +-- websocket.py   -> /ws/signals
  |     +-- health.py      -> /health
  |
  +-- Services (app/services/)
  |     +-- analyzer.py       Orchestrates the full analysis pipeline
  |     +-- monitor.py        Background heavy/light polling loop
  |     +-- signal_detector.py  9-condition entry checker
  |     +-- notifier.py       Telegram + WebSocket push
  |     +-- cache.py          In-memory TTL cache
  |
  +-- Middleware
  |     +-- auth.py         API key authentication
  |     +-- rate_limit.py   slowapi rate limiting
  |     +-- logging.py      Structured JSON logging + correlation ID
  |
  +-- Models (SQLAlchemy ORM)
        +-- Asset, Signal, Trade, NotificationLog, TelegramConfig, RssFeed
        +-- Engine factory (SQLite or PostgreSQL)

Core Engine (modules/)
  +-- price_data.py          Multi-source OHLCV fetch + technical indicators
  +-- strategy.py            Shared strategy logic (regime, labeling, QS, SL/TP)
  +-- sentiment.py           Groq LLM / FinBERT sentiment analysis
  +-- polymarket.py          Prediction market signal from Gamma API
  +-- news_fetcher.py        RSS aggregation + LLM summarization
  +-- economic_calendar.py   Forex Factory calendar scraper
  +-- hallucination_guard.py Cross-signal validation
  +-- exceptions.py          Typed exception hierarchy
  +-- circuit_breaker.py     Circuit breaker for external APIs
  +-- retry.py               Tenacity retry decorators
```

## Data Flow: Full Analysis

```
POST /api/analyze/{symbol}
  |
  +-- [parallel]
  |     +-- _run_technicals()
  |     |     +-- _fetch_daily()       yfinance (10mo, 1d) -> Twelve Data fallback
  |     |     +-- _fetch_intraday()    yfinance (5d, 5m)
  |     |     +-- _fetch_weekly()      yfinance (2y, 1wk)
  |     |     +-- _fetch_hourly()      yfinance (30d, 1h)
  |     |     +-- Compute: RSI, MACD, EMA, BBands, Stoch, ADX, ATR, VWAP
  |     |     +-- Build: OHLC chart data, EMA20/50 overlays, key levels
  |     |     +-- Score: composite direction, quality score (5 checks), MTF alignment
  |     |
  |     +-- _run_sentiment()
  |     |     +-- Fetch RSS news
  |     |     +-- Groq LLM analysis (or FinBERT fallback)
  |     |     +-- Score: -3 to +3, bias, confidence, key drivers
  |     |
  |     +-- _run_polymarket()
  |     |     +-- Fetch events from Gamma API (tag_slug per asset class)
  |     |     +-- LLM classification (or keyword fallback)
  |     |     +-- Signal: BULLISH/BEARISH/NEUTRAL, confidence, top markets
  |     |
  |     +-- _run_calendar()
  |           +-- Forex Factory high-impact events
  |           +-- Regime override if major event within 2h
  |
  +-- Determine regime (sentiment + technicals + polymarket)
  +-- Compute setup (entry, SL/TP, R:R, tradeable)
  +-- Generate trade thesis
  +-- Validate with hallucination guard
  +-- Return complete analysis JSON
```

## Data Flow: Monitor

```
POST /api/monitor/start {symbol}
  |
  +-- Schedule heavy job (every 30 min)
  |     +-- Full analyze_single_asset()
  |     +-- Cache result (TTL 1800s)
  |     +-- Broadcast via WebSocket
  |
  +-- Schedule light job (every 2 min)
        +-- fetch_quote() via Twelve Data /price (1 credit)
        +-- Merge fresh price into cached analysis
        +-- Recompute entry/SL/TP from cached distances
        +-- Run signal detection (9 conditions)
        +-- If signal fires: Telegram + WebSocket notification
        +-- Broadcast price_update via WebSocket
```

## Data Flow: Real-Time Chart

```
Page load -> renderChart() with analysis OHLC data
  |
  +-- setInterval(30s) -> GET /api/quote/{symbol}
  |     +-- yfinance fast_info (free, no credits)
  |     +-- Update last candle (close, high, low)
  |
  +-- WebSocket ws:price_update (every 2 min, when monitor active)
        +-- Update last candle
        +-- Update price display
        +-- Flash LIVE badge
```

## Database Schema

| Table | Purpose |
|-------|---------|
| `assets` | Configured trading assets (symbol, display_name) |
| `signals` | Generated signals with entry/SL/TP and outcome tracking |
| `trades` | Trade journal entries with P&L |
| `notification_log` | Rate-limited notification history |
| `telegram_config` | Bot token, chat ID, enabled flag |
| `rss_feeds` | RSS feed URLs for news aggregation |

Supports SQLite (default, zero config) and PostgreSQL (via Docker).

## Caching Strategy

| Data | TTL | Reason |
|------|-----|--------|
| Price data | 60s | Frequently changing |
| News | 300s | Updates every few minutes |
| Sentiment | 600s | Stable within analysis window |
| Polymarket | 600s | Prediction markets move slowly |
| Calendar | 3600s | Events don't change intraday |
| Heavy analysis | 1800s | Full pipeline is expensive |

## Resilience

- **Typed exceptions**: `TransientError` (retryable) vs `PermanentError` (fail fast)
- **Retry with backoff**: tenacity decorators on all external API calls
- **Circuit breakers**: 3 failures -> circuit open for 5 minutes per API
- **Graceful degradation**: each pipeline stage can fail independently
- **Drawdown breaker**: pauses signals if daily/weekly P&L exceeds threshold
