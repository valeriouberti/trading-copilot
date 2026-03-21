# Trading Copilot

Real-time CFD analysis and monitoring dashboard for retail traders. Focused on three core assets:

| Asset | Symbol | Type |
|-------|--------|------|
| S&P 500 | `^GSPC` | Cash index |
| Gold | `GC=F` | Futures |
| EUR/USD | `EURUSD=X` | Spot forex |

Built for manual execution on platforms like Fineco, with TradingView for charting.

## What It Does

1. **Analyzes** each asset using 5 directional indicators, multi-timeframe alignment, quality scoring, news sentiment (Groq LLM), and Polymarket prediction markets
2. **Generates** a plain-English **Action Plan** telling you exactly what to do (or why to sit out)
3. **Monitors** prices in the background and fires alerts via WebSocket + Telegram when entry conditions align
4. **Tracks** your trades with automatic P&L, R-multiple, and performance analytics

---

## Quick Start

```bash
git clone <repo-url>
cd trading-assistant

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt        # or: pip install .

cp .env.example .env
# Edit .env with your API keys

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
GROQ_API_KEY=gsk_your_key_here          # LLM sentiment (free tier)
TWELVE_DATA_API_KEY=your_key_here        # Price polling fallback (free: 800 credits/day)
```

Optional:

```env
TELEGRAM_BOT_TOKEN=your_bot_token        # Telegram alerts
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ENABLED=true
TRADING_COPILOT_API_KEY=your_secret      # API authentication (disabled if empty)
DATABASE_URL=postgresql+asyncpg://...     # Default: SQLite
```

`config.yaml` is optional seed data for the first startup. After that, everything lives in the database and is managed through the web UI.

Full configuration reference: [docs/configuration.md](docs/configuration.md)

---

## Pages

| Page | URL | Description |
|------|-----|-------------|
| **Dashboard** | `/` | 3-asset overview with auto-analysis, regime badges, verdict per asset |
| **Asset Detail** | `/asset/{symbol}` | Interactive chart with timeframe selector, technicals, Action Plan |
| **Trade Journal** | `/trades` | Record, close, and delete trades |
| **Analytics** | `/analytics` | Win rate, profit factor, equity curve, insights |
| **Signals** | `/signals` | Signal history with outcomes |
| **Settings** | `/settings` | Telegram config, monitor settings, credit budget |

---

## Dashboard

On page load, all 3 assets are analyzed automatically. Each card shows:

- Current price with change %
- Regime badge (LONG / SHORT / NEUTRAL)
- Composite score, Quality Score, RSI, ADX, MTF, ATR
- **Verdict**: either "SKIP -- reason" or a tradeable setup with Entry / SL / TP / R:R

Buttons:
- **Analyze All** -- re-run analysis for all 3 assets
- **Start Monitor** / **Stop Monitor** -- toggle background monitoring for all assets

A credit budget bar shows Twelve Data usage (800/day free tier).

---

## Asset Detail & Charts

### Timeframe Selector

The chart supports 6 timeframes, switchable with one click:

| Button | Interval | Data Range |
|--------|----------|------------|
| 5m | 5-minute candles | 5 days |
| 15m | 15-minute candles | 30 days |
| 1H | Hourly candles | 60 days |
| 4H | 4-hour (resampled from 1H) | 60 days |
| **1D** | Daily candles (default) | 10 months |
| 1W | Weekly candles | 2 years |

All timeframes include EMA20 and EMA50 overlays. Intraday charts show time on the x-axis.

### Live Price Updates

The chart updates in real-time:

- **Every 30 seconds**: polls `/api/quote/{symbol}` (yfinance, free, no credits)
- **Every 2 minutes**: WebSocket push from the monitor's light poll (when monitor is active)
- A blinking **LIVE** badge appears on the chart when updates are active

The last candle's close, high, and low update with each price tick.

### Action Plan

After analysis, a plain-English **Action Plan** appears below the chart:

**When tradeable:**

1. Entry instruction with price, regime, and composite score
2. Stop loss placement with exact price, ATR multiplier, and distance
3. Take profit target with R:R ratio
4. Multi-timeframe context (weekly/daily/hourly trends)
5. Sentiment and Polymarket confirmation or conflict warnings
6. Execution rules (don't move SL, when to exit early)

Yellow warnings appear for imminent calendar events, borderline QS, or Polymarket conflicts.

**When not tradeable:**

Numbered steps explain exactly why: neutral regime, low quality score, partial MTF alignment, mixed indicators. Final instruction: "Stay flat. Do not force a trade."

---

## Analysis Pipeline

Each analysis runs this pipeline:

```
Price Data (yfinance / Twelve Data)
    |
    +-- Technical Indicators (RSI, MACD, EMA, BBands, Stoch, ADX, ATR)
    +-- Multi-Timeframe Analysis (weekly + daily + hourly trends)
    +-- Key Levels (PDH/PDL/PDC, pivot points, R1/R2/S1/S2)
    +-- Quality Score (5 components: confluence, trend, key level, candle, volume)
    |
News Sentiment (Groq LLM or FinBERT fallback)
Polymarket Prediction Markets (public API, no key needed)
Economic Calendar (Forex Factory)
    |
    +-- Regime Determination (LONG / SHORT / NEUTRAL)
    +-- Composite Scoring (weighted directional consensus)
    +-- Setup Computation (entry, SL/TP, R:R, tradeable flag)
    +-- Action Plan Generation
```

### Polymarket Integration

The Polymarket card shows:

- Aggregate signal (BULLISH / BEARISH / NEUTRAL) with confidence %
- Bull vs Bear probability breakdown
- Total volume across analyzed markets
- **Top 5 markets** with: question, YES/NO probability bar, impact direction, magnitude (1-5), volume, expiry date

Markets are fetched from the public Gamma API, classified by LLM (or keyword fallback), and scored with volume + temporal decay weighting.

---

## Monitor

The background monitor uses a split architecture to stay within Twelve Data's free tier (800 credits/day):

| Job | Interval | What It Does | Cost |
|-----|----------|-------------|------|
| **Heavy** | Every 30 min | Full analysis pipeline (indicators, scoring, QS, SL/TP) | ~1 credit |
| **Light** | Every 2 min | Price quote + signal re-check against cached analysis | 1 credit |

Max 3 assets monitored simultaneously. The Settings page shows credit usage in real-time.

When all 9 entry conditions align, the monitor fires a signal via:
- **WebSocket** (browser notification + chart flash)
- **Telegram** (formatted message with Entry/SL/TP/R:R)

---

## Trade Journal

- Record trades with entry/exit, SL/TP, direction, QS, regime, notes
- **Close** open trades with exit price
- **Delete** trades (with confirmation)
- Import from `trade_log.csv`
- Auto-computed P&L and R-multiple

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

Notification types: trade signals, regime changes, calendar alerts, monitor status.

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
|   |   +-- analysis.py          # /analyze, /chart, /ohlc, /quote endpoints
|   |   +-- assets.py            # Asset CRUD
|   |   +-- monitor.py           # Background monitor control
|   |   +-- trades.py            # Trade journal + signals + analytics
|   |   +-- settings.py          # Telegram configuration
|   |   +-- websocket.py         # Real-time push
|   |   +-- health.py            # Health check
|   |   +-- analytics_api.py     # Portfolio heatmap
|   +-- services/
|   |   +-- analyzer.py          # Analysis pipeline + setup + Action Plan data
|   |   +-- monitor.py           # Heavy/light split polling
|   |   +-- notifier.py          # Telegram + WebSocket notifications
|   |   +-- signal_detector.py   # 9-condition entry check
|   |   +-- cache.py             # In-memory TTL cache
|   +-- middleware/               # Auth, rate limiting, structured logging
|   +-- models/                   # SQLAlchemy ORM + engine
|   +-- templates/                # Jinja2 HTML pages
|   +-- static/                   # CSS + JS (Alpine.js, HTMX, WebSocket)
|
+-- modules/                     # Core Engine
|   +-- strategy.py              # Shared strategy (regime, labeling, QS, SL/TP)
|   +-- price_data.py            # Price fetch + indicators + chart data
|   +-- polymarket.py            # Prediction market signal
|   +-- sentiment.py             # LLM / FinBERT sentiment
|   +-- news_fetcher.py          # RSS aggregation + summarization
|   +-- economic_calendar.py     # Forex Factory calendar
|   +-- hallucination_guard.py   # Cross-validation of signals
|   +-- exceptions.py            # Typed exception hierarchy
|   +-- circuit_breaker.py       # Circuit breaker for external APIs
|   +-- retry.py                 # Retry decorators (tenacity)
|   +-- vbt_backtester.py        # VectorBT backtester
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
| No data for symbol | Check the symbol on Yahoo Finance. Set `TWELVE_DATA_API_KEY` as fallback |
| Telegram test fails "Chat not found" | Your chat ID is wrong. Get it from `@userinfobot` on Telegram |
| Rate limit exceeded | Wait 1 minute. Groq and analysis endpoints have per-minute limits |
| Port 8000 in use | `lsof -ti :8000 \| xargs kill` or use `--port 8001` |
| Monitor not firing signals | Check: asset has recent data, QS >= 4, MTF aligned, regime not NEUTRAL |
| WebSocket won't connect | Check browser console. Proxy/firewall may block WS connections |
| Circuit breaker open | An external API is down. Auto-recovers after 5 minutes. Check `/api/health` |

---

## Disclaimer

This tool is for informational and educational purposes only. **It is not financial advice.** CFD trading carries a high risk of loss. Always trade responsibly and only with capital you can afford to lose.
