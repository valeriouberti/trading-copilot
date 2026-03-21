# ETF Swing Trader

UCITS ETF swing trading assistant for Italian retail investors on Fineco. Analyzes 8 ETFs daily and provides BUY/HOLD/SELL recommendations via web dashboard and Telegram.

| Symbol | Name | Category |
|--------|------|----------|
| `SWDA.MI` | iShares Core MSCI World | Equity - Global |
| `CSSPX.MI` | iShares Core S&P 500 | Equity - US |
| `EQQQ.MI` | Invesco NASDAQ-100 | Equity - US Tech |
| `MEUD.MI` | Amundi STOXX Europe 600 | Equity - Europe |
| `IEEM.MI` | iShares MSCI EM | Equity - EM |
| `SGLD.MI` | Invesco Physical Gold | Commodity |
| `SEGA.MI` | iShares Core EU Govt Bond | Bond - EUR |
| `AGGH.MI` | iShares Global Agg Bond | Bond - Global |

All available on Fineco at EUR 2.95/trade. LONG-only, 2-10 day holds, EUR 1-5k capital.

## What It Does

1. **Analyzes** each ETF using technical indicators, multi-timeframe alignment, quality scoring, news sentiment (Groq LLM with Qwen 3 32B), and Polymarket prediction markets
2. **Sends** a daily Telegram briefing at 08:00 CET with ranked BUY/SELL/HOLD recommendations
3. **Monitors** open positions during market hours and fires SELL alerts when SL/TP is hit or max hold (10 days) exceeded
4. **Tracks** your trades with automatic P&L in EUR and performance analytics

---

## Quick Start

```bash
git clone <repo-url>
cd trading-assistant

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt        # or: pip install .

cp .env.example .env
# Edit .env with your GROQ_API_KEY

python run_webapp.py
# Open http://localhost:8000
```

### Docker

```bash
cp .env.example .env
docker compose up -d
# Open http://localhost:8000
```

### CLI (batch report)

```bash
python main.py
```

---

## Configuration

Copy `.env.example` to `.env` and set at minimum:

```env
GROQ_API_KEY=gsk_your_key_here          # LLM sentiment (Dev Tier recommended)
```

Optional:

```env
TELEGRAM_BOT_TOKEN=your_bot_token        # Telegram alerts
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ENABLED=true
DATABASE_URL=postgresql+asyncpg://...     # Default: SQLite
```

`config.yaml` is optional seed data for the first startup. After that, everything lives in the database and is managed through the web UI.

Full configuration reference: [docs/configuration.md](docs/configuration.md)

---

## Pages

| Page | URL | Description |
|------|-----|-------------|
| **Dashboard** | `/` | 8-ETF overview with regime badges and verdict per asset |
| **Asset Detail** | `/asset/{symbol}` | Interactive chart, technicals, sentiment, Polymarket, Action Plan |
| **Portfolio** | `/portfolio` | Open positions, unrealized P&L, max 2 positions |
| **Trade Journal** | `/trades` | Record, close, and delete trades |
| **Analytics** | `/analytics` | Win rate, profit factor, equity curve, insights |
| **Signals** | `/signals` | Signal history with outcomes |
| **Settings** | `/settings` | Telegram config, scheduler settings |

---

## Dashboard

On page load, all 8 ETFs show cached data from the last analysis. Each card shows:

- Current price with change %
- Regime badge (LONG / NEUTRAL / BEARISH)
- Composite score, Quality Score, RSI, ADX, MTF, ATR
- **Verdict**: either "SKIP -- reason" or a tradeable setup with Entry / SL / TP / R:R

Buttons:
- **Analyze Now** -- trigger a full analysis of all 8 ETFs (same as the 08:00 morning briefing)
- **Start/Stop Scheduler** -- toggle the cron-based monitoring

---

## Asset Detail & Charts

### Timeframe Selector

The chart supports 2 timeframes, switchable with one click:

| Button | Interval | Data Range |
|--------|----------|------------|
| **1D** | Daily candles (default) | 10 months |
| 1W | Weekly candles | 2 years |

Both timeframes include EMA20 and EMA50 overlays.

### On-Demand Analysis

Clicking an ETF card triggers a full analysis pipeline for that asset, including LLM sentiment, Polymarket, and economic calendar data.

### Action Plan

After analysis, a plain-English **Action Plan** appears below the chart:

**When tradeable:**

1. Entry instruction with price, regime, and composite score
2. Stop loss placement with exact price, ATR multiplier, and distance in EUR
3. Take profit target with R:R ratio
4. Multi-timeframe context (weekly + daily trends)
5. Sentiment and Polymarket confirmation or conflict warnings
6. Execution rules (don't move SL, when to exit early)

Yellow warnings appear for imminent calendar events, borderline QS, or Polymarket conflicts.

**When not tradeable:**

Numbered steps explain exactly why: neutral regime, low quality score, partial MTF alignment, mixed indicators. Final instruction: "Stay flat. Do not force a trade."

---

## Analysis Pipeline

Each analysis runs this pipeline:

```
Price Data (yfinance)
    |
    +-- Technical Indicators (RSI, MACD, EMA, BBands, Stoch, ADX, ATR)
    +-- Multi-Timeframe Analysis (weekly + daily trends)
    +-- Key Levels (PDH/PDL/PDC, pivot points, R1/R2/S1/S2)
    +-- Quality Score (5 components: confluence, trend, key level, candle, volume)
    |
News Sentiment (Groq LLM — Qwen 3 32B, Ollama fallback)
Polymarket Prediction Markets (public API, no key needed)
Economic Calendar (Forex Factory)
    |
    +-- Regime Determination (LONG / NEUTRAL / BEARISH)
    +-- Composite Scoring (weighted directional consensus)
    +-- Setup Computation (entry, SL/TP in EUR, R:R, tradeable flag)
    +-- Commission Viability Check (expected gain > 2x round-trip cost)
    +-- Action Plan Generation
```

### LLM Architecture

All LLM calls route through a unified client (`modules/llm_client.py`):
- **Primary**: Groq cloud API with Qwen 3 32B (fast, Dev Tier recommended)
- **Fallback**: Local Ollama with Qwen 2.5 14B (used when Groq is rate-limited)
- Automatic `<think>` block stripping for Qwen 3 reasoning models

### Polymarket Integration

The Polymarket card shows:

- Aggregate signal (BULLISH / BEARISH / NEUTRAL) with confidence %
- Bull vs Bear probability breakdown
- Total volume across analyzed markets
- **Top 5 markets** with: question, YES/NO probability bar, impact direction, magnitude (1-5), volume, expiry date

Markets are fetched from the public Gamma API, classified by LLM (or keyword fallback), and scored with volume + temporal decay weighting. Tag slugs are mapped per ETF category (equity, bond, gold, emerging markets).

---

## Scheduler

The background scheduler uses APScheduler with 3 cron jobs (Rome timezone):

| Job | Time (CET) | What It Does |
|-----|------------|--------------|
| **Morning Briefing** | 08:00 | Full analysis of all 8 ETFs, ranked signals, Telegram briefing |
| **Midday Check** | 13:00 | Check open positions (price vs SL/TP, max hold days) |
| **Closing Check** | 17:00 | Check open positions, end-of-day summary |

**Startup catch-up**: if the app starts after 08:00 but before 17:30, it runs a quick technicals-only briefing (skips LLM/Polymarket/calendar for fast startup).

When entry conditions align, the scheduler fires a signal via:
- **WebSocket** (browser notification + chart flash)
- **Telegram** (formatted message with Entry/SL/TP/R:R in EUR)

---

## Portfolio

- Max 2 concurrent positions
- Position size: EUR 1,500 default
- Commission: EUR 2.95 per trade (EUR 5.90 round-trip)
- Record positions with entry price, shares, SL/TP
- Track unrealized P&L in EUR and %
- Automatic SELL alerts when SL/TP hit or max 10-day hold exceeded

---

## Trade Journal

- Record trades with entry/exit, SL/TP, direction, QS, regime, notes
- **Close** open trades with exit price
- **Delete** trades (with confirmation)
- Import from `trade_log.csv`
- Auto-computed P&L in EUR and R-multiple

### Performance Analytics

- Win rate (total + by asset, regime, QS, direction)
- Profit factor, average R-multiple, max drawdown
- Equity curve and rolling win rate (20-trade window)
- R-multiple distribution histogram
- Auto-generated insights

---

## Telegram Notifications

1. Create a bot via `@BotFather` on Telegram
2. Get your chat ID from `@userinfobot`
3. Enter both in Settings > Telegram
4. Click "Send Test" to verify

Notification types:
- **Daily briefing**: ranked ETF analysis with BUY/HOLD/SELL classifications
- **SELL alerts**: SL/TP hit, max hold exceeded
- **Signal alerts**: new entry conditions met

---

## Project Structure

```
trading-assistant/
+-- main.py                     # CLI entry point
+-- run_webapp.py                # Web dashboard entry point
+-- pyproject.toml               # Project metadata + dependencies
+-- config.yaml                  # Seed data (optional, first run only)
+-- .env.example                 # Environment variable template
+-- Dockerfile                   # Multi-stage (full + lite)
+-- docker-compose.yml           # App + PostgreSQL
|
+-- app/                         # Web Dashboard (FastAPI)
|   +-- server.py                # App + lifespan + page routes
|   +-- config.py                # Pydantic Settings
|   +-- api/
|   |   +-- analysis.py          # /analyze, /chart, /ohlc, /quote, /screening
|   |   +-- assets.py            # Asset CRUD
|   |   +-- monitor.py           # Scheduler control (start/stop/schedule)
|   |   +-- portfolio.py         # Position management
|   |   +-- trades.py            # Trade journal + signals + analytics
|   |   +-- settings.py          # Telegram configuration
|   |   +-- websocket.py         # Real-time push
|   |   +-- health.py            # Health check
|   |   +-- analytics_api.py     # Portfolio heatmap
|   +-- services/
|   |   +-- analyzer.py          # Analysis pipeline + setup computation
|   |   +-- monitor.py           # Cron scheduler (08:00/13:00/17:00 CET)
|   |   +-- notifier.py          # Telegram + WebSocket notifications
|   |   +-- signal_detector.py   # 7-condition entry check
|   |   +-- cache.py             # In-memory TTL cache
|   +-- middleware/               # Rate limiting, structured logging
|   +-- models/                   # SQLAlchemy ORM (Asset, Signal, Trade, Position)
|   +-- templates/                # Jinja2 HTML pages
|   +-- static/                   # CSS + JS (Alpine.js, HTMX, WebSocket)
|
+-- modules/                     # Core Engine
|   +-- llm_client.py            # Unified LLM client (Groq + Ollama fallback)
|   +-- groq_client.py           # Groq API singleton
|   +-- strategy.py              # Shared strategy (regime, labeling, QS, SL/TP, commission)
|   +-- price_data.py            # Price fetch + indicators + chart data
|   +-- polymarket.py            # Prediction market signal from Gamma API
|   +-- sentiment.py             # Two-pass LLM sentiment analysis
|   +-- news_fetcher.py          # RSS aggregation + LLM summarization
|   +-- economic_calendar.py     # Forex Factory calendar
|   +-- hallucination_guard.py   # Cross-signal validation
|   +-- exceptions.py            # Typed exception hierarchy
|   +-- circuit_breaker.py       # Circuit breaker for external APIs
|   +-- retry.py                 # Retry decorators (tenacity)
|   +-- vbt_backtester.py        # VectorBT backtester (LONG-only)
|   +-- data/
|   |   +-- universe.py          # ETF universe (8 UCITS ETFs)
|   |   +-- yfinance_provider.py # yfinance data provider
|   |   +-- registry.py          # Data provider registry
|
+-- docs/                        # Documentation wiki
+-- tests/                       # Test suite
+-- alembic/                     # Database migrations
```

---

## Wiki

Detailed documentation is in the [`docs/`](docs/) directory:

- [Architecture](docs/architecture.md) -- System design, data flow, component responsibilities
- [Trading Strategy](docs/strategy.md) -- Indicators, scoring, signals, quality checks
- [API Reference](docs/api.md) -- All endpoints with request/response examples
- [Deployment](docs/deployment.md) -- Docker, PostgreSQL, production settings
- [Configuration](docs/configuration.md) -- All environment variables and config options

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No data for symbol | Check the .MI symbol on Yahoo Finance |
| Telegram test fails "Chat not found" | Your chat ID is wrong. Get it from `@userinfobot` on Telegram |
| Groq rate limited | Upgrade to Dev Tier at https://console.groq.com/settings/billing |
| LLM analysis unavailable | Check `GROQ_API_KEY` is set in `.env`. Verify with `/api/health` |
| Port 8000 in use | `lsof -ti :8000 \| xargs kill` or use `--port 8001` |
| Scheduler not firing | Check: app is running, scheduler is started via dashboard toggle |
| WebSocket won't connect | Check browser console. Proxy/firewall may block WS connections |
| Circuit breaker open | An external API is down. Auto-recovers after 5 minutes. Check `/api/health` |
| Empty sentiment (score 0.0) | Qwen 3 `<think>` block may exceed max_tokens. Check server logs |

---

## Disclaimer

This tool is for informational and educational purposes only. **It is not financial advice.** ETF investing carries risk. Always invest responsibly and only with capital you can afford to lose.
