# API Reference

Base URL: `http://localhost:8000/api`

All endpoints return JSON. Rate-limited endpoints return `429` when exceeded.

---

## Health

### GET /health

Extended health check covering database, monitor, cache, and circuit breakers.

```json
{
  "status": "healthy",
  "database": "ok",
  "monitor": {"active": 2},
  "cache": {"entries": 5, "hit_rate": 0.73},
  "circuit_breakers": {"groq": "closed", "polymarket": "closed"}
}
```

---

## Assets

### GET /assets

```json
{
  "assets": [
    {"symbol": "^GSPC", "display_name": "S&P 500"},
    {"symbol": "GC=F", "display_name": "Gold Futures"},
    {"symbol": "EURUSD=X", "display_name": "EUR/USD"}
  ],
  "count": 3
}
```

### POST /assets

Add a new asset. Validates the symbol via yfinance before saving.

```json
// Request
{"symbol": "AAPL", "display_name": "Apple"}

// Response (201)
{"asset": {"symbol": "AAPL", "display_name": "Apple Inc."}, "message": "AAPL added"}
```

### DELETE /assets/{symbol}

Remove an asset. Cannot remove the last asset.

```json
{"message": "AAPL removed"}
```

---

## Analysis

### GET /quote/{symbol}

Lightweight current price (no analysis, no credits).

```json
{"symbol": "^GSPC", "price": 6506.48, "source": "yfinance"}
```

### GET /ohlc/{symbol}?tf=1d

OHLC + EMA data for a specific timeframe. Timeframes: `5m`, `15m`, `1h`, `4h`, `1d`, `1wk`.

```json
{
  "ohlc": [{"time": "2025-05-20", "open": 5800.0, "high": 5850.0, "low": 5780.0, "close": 5830.0}, ...],
  "ema20": [{"time": "2025-06-15", "value": 5900.50}, ...],
  "ema50": [{"time": "2025-07-25", "value": 5850.30}, ...],
  "price": 6506.48,
  "change_pct": -0.15,
  "tf": "1d",
  "bars": 211
}
```

Intraday timeframes use unix timestamps for `time`. Daily/weekly use `"YYYY-MM-DD"` strings.

### GET /chart/{symbol}

Chart data from the analysis pipeline (OHLC + EMA from daily data).

```json
{
  "chart": {"ohlc": [...], "ema20": [...], "ema50": [...]},
  "price": {"current": 6506.48, "change_pct": -0.15, "data_source": "yfinance"}
}
```

### POST /analyze/{symbol}

Full analysis pipeline. Query params: `skip_llm` (bool), `skip_polymarket` (bool).

Response includes: `analysis` (technicals, chart, price), `sentiment`, `polymarket`, `calendar`, `regime`, `setup` (entry/SL/TP/tradeable), `trade_thesis`, `news_summary`, `validation_flags`.

### POST /analyze/{symbol}/telegram

Run analysis and send the signal to Telegram. Returns 422 if no tradeable signal.

---

## Monitor

### POST /monitor/start

```json
// Request
{"symbol": "^GSPC"}

// Response
{"message": "Monitor started for ^GSPC", "interval_seconds": 120}
```

### POST /monitor/stop

```json
{"symbol": "^GSPC"}
```

### GET /monitor/status

```json
{
  "monitors": [
    {
      "symbol": "^GSPC",
      "status": "ACTIVE",
      "interval_seconds": 120,
      "started_at": "2026-03-21T08:00:00Z",
      "last_check": "2026-03-21T10:30:00Z",
      "last_price": 6506.48
    }
  ],
  "ws_connections": 2
}
```

### GET /monitor/budget

Twelve Data credit usage for the current day.

```json
{
  "used": 145,
  "remaining": 605,
  "limit": 750,
  "pct_used": 19.3
}
```

---

## Trades

### GET /trades

List trades with optional filters: `symbol`, `direction`, `quality_score`, `limit`, `offset`.

```json
{
  "trades": [
    {
      "id": 1,
      "timestamp": "2026-03-21T09:30:00",
      "symbol": "^GSPC",
      "direction": "LONG",
      "entry_price": 6500.00,
      "exit_price": 6550.00,
      "stop_loss": 6470.00,
      "take_profit": 6560.00,
      "quality_score": 4,
      "regime": "LONG",
      "outcome_pips": 50.0,
      "r_multiple": 1.67,
      "notes": "Strong trend day"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

### POST /trades

Record a new trade. If `exit_price` is provided, P&L and R-multiple are auto-computed.

### PUT /trades/{id}

Update a trade (typically to close it with `exit_price`).

### DELETE /trades/{id}

Delete a trade permanently. Returns 404 if not found.

```json
{"message": "Trade deleted", "id": 1}
```

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

```json
{
  "bot_token_masked": "...W61QedYg",
  "chat_id": "123456789",
  "enabled": true
}
```

### PUT /settings/telegram

Update config. Empty `bot_token` preserves the existing token.

```json
{"bot_token": "", "chat_id": "123456789", "enabled": true}
```

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
| `price_update` | symbol, price, change_pct, regime, timestamp | Every light poll (2 min) |
| `signal` | symbol, direction, entry, sl, tp, quality_score, mtf | Entry conditions met |
| `regime_change` | old_regime, new_regime, reason | Regime transitions |

Client-side events are dispatched as `ws:price_update`, `ws:signal`, etc.
