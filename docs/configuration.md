# Configuration

## Priority Chain

Settings are resolved in this order (first wins):

```
Environment variables  >  .env file  >  config.yaml  >  Pydantic defaults
```

- **Environment variables**: Always win. Use for secrets and deployment overrides.
- **`.env` file**: Loaded automatically by Pydantic Settings. Main configuration file.
- **`config.yaml`**: Optional. Only used for seed data (assets, RSS feeds) on first startup.
- **Pydantic defaults**: Sensible fallbacks so the app works out of the box.

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `GROQ_API_KEY` | Groq LLM API key for sentiment analysis | `gsk_abc123...` |

### Recommended

| Variable | Description | Example |
|----------|-------------|---------|
| `TWELVE_DATA_API_KEY` | Twelve Data API key for price polling fallback | `abc123def456` |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./trading.db` | Async SQLAlchemy URL |
| `POSTGRES_PASSWORD` | `trading_local` | PostgreSQL password (Docker Compose only) |

SQLite requires zero configuration. For PostgreSQL:

```env
DATABASE_URL=postgresql+asyncpg://trading:password@localhost:5432/trading
```

### Telegram

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | _(empty)_ | Your chat ID from @userinfobot |
| `TELEGRAM_ENABLED` | `false` | Enable/disable notifications |

These seed the database on first startup. After that, manage Telegram config via the Settings page in the web dashboard.

### App Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model for sentiment and classification |
| `LOOKBACK_HOURS` | `16` | Hours of news to fetch for sentiment (1-168) |
| `REPORT_LANGUAGE` | `italian` | Language for CLI reports |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_COPILOT_API_KEY` | _(empty)_ | API key for authentication. Empty = auth disabled |

When set, all API calls must include `X-API-Key` header or `api_key` query param. Dashboard pages and health check are exempt.

---

## .env File

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Minimal `.env` for development:

```env
GROQ_API_KEY=gsk_your_key_here
```

Full `.env` for production:

```env
# Database
DATABASE_URL=postgresql+asyncpg://trading:secure_pass@localhost:5432/trading
POSTGRES_PASSWORD=secure_pass

# API Keys
GROQ_API_KEY=gsk_your_key_here
TWELVE_DATA_API_KEY=your_key_here

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789
TELEGRAM_ENABLED=true

# Security
TRADING_COPILOT_API_KEY=your_secret_api_key

# App
GROQ_MODEL=llama-3.3-70b-versatile
LOOKBACK_HOURS=16
```

---

## config.yaml

**Optional.** Only used for seeding the database on first startup. After the first run, all data lives in the database and is managed through the web dashboard.

```yaml
# Seed RSS feeds (imported once, then managed in DB)
rss_feeds:
  - url: https://feeds.finance.yahoo.com/rss/2.0/headline?s=^IXIC&region=US&lang=en-US
    name: Yahoo Finance NASDAQ
  - url: https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114
    name: CNBC Top News
  - url: https://www.investing.com/rss/news_14.rss
    name: Investing.com
  - url: https://feeds.marketwatch.com/marketwatch/topstories/
    name: MarketWatch Top Stories

# Seed assets (imported once, then managed via dashboard)
seed_assets:
  - symbol: "^GSPC"
    display_name: S&P 500
  - symbol: GC=F
    display_name: Gold
  - symbol: EURUSD=X
    display_name: EUR/USD
```

Changes to `config.yaml` after the first startup have **no effect**. To modify assets or feeds, use the web dashboard.

---

## External API Keys

### Groq (required)

Free tier available. Used for:
- News sentiment analysis
- Polymarket event classification
- Trade thesis generation

Get a key at [console.groq.com](https://console.groq.com).

### Twelve Data (recommended)

Free tier: 800 credits/day. Used for:
- Price polling in the monitor's light job (1 credit per quote)
- Fallback data source when yfinance is unavailable

Get a key at [twelvedata.com](https://twelvedata.com).

The app works without it — yfinance is the primary data source. But the monitor's light poll requires Twelve Data for efficient single-price queries.

### Telegram (optional)

For push notifications when signals fire. Setup:
1. Message `@BotFather` on Telegram to create a bot
2. Message `@userinfobot` to get your chat ID
3. Set both in `.env` or in the Settings page

---

## Rate Limits

Built-in per-IP rate limits:

| Endpoint | Limit |
|----------|-------|
| `/api/analyze/*` | 60/minute |
| `/api/monitor/*` | 10/minute |
| All other `/api/*` | 120/minute |

Returns `429 Too Many Requests` when exceeded.
