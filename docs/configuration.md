# Configuration

## Priority Chain

Settings are resolved in this order (first wins):

```
Environment variables  >  .env file  >  config.yaml  >  Pydantic defaults
```

- **Environment variables**: Always win. Use for secrets and deployment overrides.
- **`.env` file**: Loaded automatically at startup. Main configuration file.
- **`config.yaml`**: Optional. Only used for seed data (assets, RSS feeds) on first startup.
- **Pydantic defaults**: Sensible fallbacks so the app works out of the box.

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `GROQ_API_KEY` | Groq LLM API key for sentiment analysis | `gsk_abc123...` |

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

### LLM Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_MODEL` | `qwen/qwen3-32b` | Groq model for sentiment and classification |
| `OLLAMA_API_URL` | `http://localhost:11434` | Ollama API URL (fallback LLM) |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Ollama model name |

The LLM client tries Groq first (cloud, fast). If Groq is rate-limited or unavailable, it falls back to a local Ollama instance. Ollama is optional -- the app works without it.

### App Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LOOKBACK_HOURS` | `16` | Hours of news to fetch for sentiment (1-168) |
| `REPORT_LANGUAGE` | `italian` | Language for CLI reports |
| `TIMEZONE` | `Europe/Rome` | Timezone for cron scheduling |
| `MAX_POSITIONS` | `2` | Maximum concurrent open positions |
| `POSITION_SIZE_EUR` | `1500` | Default position size in EUR |

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

# LLM
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=qwen/qwen3-32b

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789
TELEGRAM_ENABLED=true

# App
LOOKBACK_HOURS=16
TIMEZONE=Europe/Rome
MAX_POSITIONS=2
POSITION_SIZE_EUR=1500
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
  - url: https://feeds.marketwatch.com/marketwatch/topstories/
    name: MarketWatch Top Stories

# Seed assets (imported once, then managed via dashboard)
seed_assets:
  - symbol: SWDA.MI
    display_name: iShares Core MSCI World
  - symbol: CSSPX.MI
    display_name: iShares Core S&P 500
  - symbol: EQQQ.MI
    display_name: Invesco NASDAQ-100
  - symbol: MEUD.MI
    display_name: Amundi STOXX Europe 600
  - symbol: IEEM.MI
    display_name: iShares MSCI EM
  - symbol: SGLD.MI
    display_name: Invesco Physical Gold
  - symbol: SEGA.MI
    display_name: iShares Core EU Govt Bond
  - symbol: AGGH.MI
    display_name: iShares Global Agg Bond
```

Changes to `config.yaml` after the first startup have **no effect**. To modify assets or feeds, use the web dashboard.

---

## External API Keys

### Groq (required)

Dev Tier recommended for higher rate limits. Used for:
- News sentiment analysis (two-pass chain-of-thought)
- Polymarket event classification
- News summarization

Model: **Qwen 3 32B** (`qwen/qwen3-32b`) -- best available for financial analysis on Groq.

Get a key at [console.groq.com](https://console.groq.com). Upgrade to Dev Tier at [console.groq.com/settings/billing](https://console.groq.com/settings/billing).

### Ollama (optional, fallback)

Local LLM runtime used when Groq is rate-limited or unavailable. Setup:

```bash
brew install --cask ollama
ollama pull qwen2.5:14b
```

The app auto-detects Ollama availability. No configuration needed if running on default port.

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

### Groq Rate Limits

| Tier | Requests/day | Tokens/min |
|------|-------------|------------|
| Free | 14,400 | 12,000 |
| Dev | 500,000 | 300,000 |

Each ETF analysis uses ~4 LLM calls (2 sentiment + 1 news summary + 1 Polymarket classification). With 8 ETFs, a full screening uses ~32 calls.
