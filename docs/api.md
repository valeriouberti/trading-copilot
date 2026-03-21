# API Reference

Base URL: `http://localhost:8000/api`

All endpoints return JSON. Rate-limited endpoints return `429` when exceeded.

---

## Health

### GET /health

Extended health check covering database, monitor, cache, and circuit breakers.

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "monitor": "running",
    "cache": {"entries": 19, "active": 11, "expired": 8, "hits": 2, "misses": 19, "hit_rate": 9.5},
    "circuit_breakers": {"yfinance": "CLOSED", "groq": "CLOSED", "polymarket": "CLOSED"}
  }
}
```

---

## Assets

### GET /assets

```json
{
  "assets": [
    {"symbol": "SWDA.MI", "display_name": "iShares Core MSCI World"},
    {"symbol": "CSSPX.MI", "display_name": "iShares Core S&P 500"},
    {"symbol": "EQQQ.MI", "display_name": "Invesco NASDAQ-100"},
    {"symbol": "MEUD.MI", "display_name": "Amundi STOXX Europe 600"},
    {"symbol": "IEEM.MI", "display_name": "iShares MSCI EM"},
    {"symbol": "SGLD.MI", "display_name": "Invesco Physical Gold"},
    {"symbol": "SEGA.MI", "display_name": "iShares Core EU Govt Bond"},
    {"symbol": "AGGH.MI", "display_name": "iShares Global Agg Bond"}
  ],
  "count": 8
}
```

### POST /assets

Add a new asset. Validates the symbol via yfinance before saving.

```json
// Request
{"symbol": "IUSN.MI", "display_name": "iShares MSCI World Small Cap"}

// Response (201)
{"asset": {"symbol": "IUSN.MI", "display_name": "iShares MSCI World Small Cap"}, "message": "IUSN.MI added"}
```

### DELETE /assets/{symbol}

Remove an asset. Cannot remove the last asset.

---

## Analysis

### GET /quote/{symbol}

Lightweight current price (no analysis, free via yfinance).

```json
{"symbol": "SWDA.MI", "price": 108.74, "source": "yfinance"}
```

### GET /ohlc/{symbol}?tf=1d

OHLC + EMA data for a specific timeframe. Timeframes: `1d`, `1wk`.

```json
{
  "ohlc": [{"time": "2025-05-20", "open": 100.0, "high": 101.5, "low": 99.5, "close": 101.0}, ...],
  "ema20": [{"time": "2025-06-15", "value": 105.50}, ...],
  "ema50": [{"time": "2025-07-25", "value": 103.30}, ...],
  "price": 108.74,
  "change_pct": -1.01,
  "tf": "1d",
  "bars": 211
}
```

### GET /chart/{symbol}

Chart data from the analysis pipeline (OHLC + EMA from daily data).

```json
{
  "chart": {"ohlc": [...], "ema20": [...], "ema50": [...]},
  "price": {"current": 108.74, "change_pct": -1.01, "data_source": "yfinance"}
}
```

### POST /analyze/{symbol}

Full analysis pipeline. Query params: `skip_llm` (bool), `skip_polymarket` (bool).

Response includes: `analysis` (technicals, chart, price), `sentiment`, `polymarket`, `calendar`, `regime`, `setup` (entry/SL/TP/tradeable), `trade_thesis`, `news_summary`, `validation_flags`.

```json
{
  "symbol": "EQQQ.MI",
  "display_name": "Invesco NASDAQ-100",
  "timestamp": "2026-03-21T16:00:00Z",
  "analysis": {"technicals": {...}, "price": {"current": 509.16, "change_pct": -0.5}},
  "sentiment": {"score": 1.5, "label": "Bullish", "bias": "BULLISH", "source": "groq-2pass"},
  "polymarket": {"signal": "BULLISH", "confidence": 65, "market_count": 12},
  "calendar": {"events_today": [...]},
  "regime": "LONG",
  "setup": {
    "direction": "LONG",
    "entry_price": 509.16,
    "stop_loss": 500.32,
    "take_profit": 526.84,
    "risk_reward": 2.0,
    "quality_score": 4,
    "commission_viable": true,
    "tradeable": true
  },
  "news_summary": ["Fed holds rates steady...", "Tech sector shows resilience..."]
}
```

### POST /analyze/{symbol}/telegram

Run analysis and send the signal to Telegram. Returns 422 if no tradeable signal.

### GET /screening

Run analysis on all 8 ETFs and return ranked BUY/HOLD/SELL classification.

```json
{
  "screening": [
    {"symbol": "EQQQ.MI", "classification": "BUY", "regime": "LONG", "quality_score": 4, ...},
    {"symbol": "SWDA.MI", "classification": "HOLD", "regime": "NEUTRAL", ...},
    {"symbol": "IEEM.MI", "classification": "SELL_IF_HOLDING", "regime": "BEARISH", ...}
  ]
}
```

---

## Monitor

### POST /monitor/start

Start the cron scheduler.

```json
{"message": "Scheduler started", "jobs": ["morning_briefing", "midday_check", "closing_check"]}
```

### POST /monitor/stop

Stop the scheduler.

### GET /monitor/status

```json
{
  "status": "running",
  "jobs": [
    {"name": "morning_briefing", "next_run": "2026-03-22T07:00:00+01:00"},
    {"name": "midday_check", "next_run": "2026-03-21T12:00:00+01:00"},
    {"name": "closing_check", "next_run": "2026-03-21T16:00:00+01:00"}
  ]
}
```

---

## Portfolio

### GET /portfolio

List open positions with current prices.

```json
{
  "positions": [
    {
      "id": 1,
      "symbol": "EQQQ.MI",
      "entry_date": "2026-03-18",
      "entry_price": 505.00,
      "shares": 3,
      "stop_loss": 496.00,
      "take_profit": 523.00,
      "status": "OPEN",
      "unrealized_pnl_eur": 12.48,
      "days_held": 3
    }
  ],
  "open_count": 1,
  "max_positions": 2
}
```

### POST /portfolio

Record a new position.

```json
{"symbol": "EQQQ.MI", "entry_price": 505.00, "shares": 3, "stop_loss": 496.00, "take_profit": 523.00}
```

### PUT /portfolio/{id}/close

Close a position with exit price.

```json
{"exit_price": 520.30}
```

### DELETE /portfolio/{id}

Remove a position.

---

## Trades

### GET /trades

List trades with optional filters: `symbol`, `direction`, `quality_score`, `limit`, `offset`.

### POST /trades

Record a new trade. If `exit_price` is provided, P&L and R-multiple are auto-computed.

### PUT /trades/{id}

Update a trade (typically to close it with `exit_price`).

### DELETE /trades/{id}

Delete a trade permanently.

### GET /trades/analytics

Performance metrics across all closed trades: win rate, profit factor, max drawdown, equity curve, insights.

### POST /trades/import-csv

Import trades from `trade_log.csv` in the project root.

---

## Signals

### GET /signals

List generated signals with filters: `symbol`, `direction`, `outcome`, `limit`, `offset`.

### PUT /signals/{id}/outcome

Update signal outcome: `TP_HIT`, `SL_HIT`, or `MANUAL`.

### GET /signals/analytics

Signal accuracy metrics: total, resolved, pending, TP hits, SL hits, theoretical win rate.

---

## Settings

### GET /settings/telegram

Returns current config with masked token.

### PUT /settings/telegram

Update config. Empty `bot_token` preserves the existing token.

### POST /telegram/test

Send a test message. Returns 400 with clear error if token or chat ID is wrong.

---

## Analytics

### GET /analytics/heatmap

Portfolio correlation matrix across monitored assets.

---

## WebSocket

### WS /ws/signals

Real-time push connection. Message types:

| Type | Fields | When |
|------|--------|------|
| `price_update` | symbol, price, change_pct, regime, timestamp | Scheduled position checks |
| `signal` | symbol, direction, entry, sl, tp, quality_score, mtf | Entry conditions met |
| `regime_change` | old_regime, new_regime, reason | Regime transitions |

Client-side events are dispatched as `ws:price_update`, `ws:signal`, etc.
