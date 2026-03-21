# Trading Copilot — Changelog

All notable changes to this project are documented here.

---

## v6.4.0 — 21 March 2026

### Codebase Cleanup & Documentation Update

Senior architect review: dead code removal, test reorganization, dependency management, docs accuracy fixes.

#### Dead Code Removal
- **Deleted `modules/backtester.py`** (938 lines) — deprecated legacy backtester replaced by `modules/vbt_backtester.py`
- **Deleted `tests/test_backtester.py`** (718 lines) — tests for deleted backtester
- **Deleted `app/templates/login.html`** (72 lines) — orphaned template with no route serving it
- **Deleted `app/static/js/app.js`** (6 lines) — unused, not referenced by any template
- Removed `/login` from `_PUBLIC_PATHS` in `app/middleware/auth.py`

#### Test Suite Reorganization
- **Split `tests/test_sprint456.py`** into domain-specific files:
  - `tests/test_analyzer.py` — ATR-adaptive SL/TP tests (`_compute_setup`)
  - `tests/test_auth.py` — API key authentication middleware tests
  - `tests/test_analytics_api.py` — Portfolio heatmap endpoint tests
- Removed 7 duplicate candle pattern tests (already in `tests/test_price_data.py`)
- Fixed hardcoded absolute paths in `TestRequirementsFiles` — now uses `Path(__file__).resolve().parent.parent`
- **405 tests pass, 0 failures** (down from 412 — 7 duplicates removed)

#### Dependency Management
- **Added `pyproject.toml`** — project metadata, dependencies with optional `[ml]` and `[dev]` groups, pytest config
- Existing requirements files kept for backward compatibility

#### Documentation Fixes
- Fixed SL/TP table in `docs/strategy.md` to match actual code values (forex 1.2x/3.0x, commodity 1.5x/3.5x, index 2.0x/4.0x, stock 1.8x/3.0x)
- Removed deleted `backtester.py` from project structure in README
- Added `pyproject.toml` to project structure and install instructions
- Updated `docs/deployment.md` with `pyproject.toml` install alternative
- Added deletion annotations to CHANGELOG entries that reference removed files

---

## v6.3.0 — 21 March 2026

### Strategy Audit & Production Fixes

Full audit of the trading system from a senior trader and software engineer perspective. Six bugs fixed that affected signal reliability for live trading.

#### Signal Detector Fixes
- **Missing RSI no longer passes**: `rsi_ok` default changed from `True` to `False`. Signals now require valid RSI data — missing RSI blocks the signal instead of silently passing.
- **Missing MTF no longer counts as ALIGNED**: Both `signal_detector.py` and `analyzer.py` now require explicit `"ALIGNED"` MTF. `None` (missing data) no longer passes the check or marks a setup as tradeable.
- **Files**: `app/services/signal_detector.py`, `app/services/analyzer.py`

#### Strategy Module Fixes
- **RSI label text corrected**: In ranging mode, RSI 35 now reads "approaching oversold" (was incorrectly "bearish momentum"). RSI 65 reads "approaching overbought" (was "bullish momentum"). Logic was correct; only display text was inverted.
- **ADX filter threshold lowered**: Composite scoring now only blocks signals at ADX < 15 (was ≤ 20). The 20-25 transition zone no longer suppresses valid setups.
- **Adaptive SL/TP aligned between live and backtest**: `compute_sl_tp_series()` (backtester) now uses the same formula as `compute_sl_tp()` (live) — 20-bar ATR window, ratio-based percentile, linear interpolation. Previously used a different 50-bar rank-based formula, causing live/backtest SL/TP divergence. Verified: 0.0% difference on identical data.
- **Files**: `modules/strategy.py`

#### Hallucination Guard Fix
- **Keyword sentiment denominator**: `_keyword_sentiment()` now divides by matched article count (`total`) instead of all articles (`len(news)`). Fixes deflated keyword baseline that made the guard too lenient against LLM overconfidence.
- **Files**: `modules/hallucination_guard.py`

#### Test Updates
- Updated ADX filter test to match new threshold (ADX < 15)
- Added new test `test_adx_filter_allows_transition_zone` (ADX 18 should pass)
- **454 tests pass, 0 failures**
- **Files**: `tests/test_strategy.py`

---

## v6.2.0 — 21 March 2026

### Dashboard Overhaul, ^GSPC Migration & Documentation

Major dashboard enhancements and complete documentation rewrite.

#### ^GSPC Migration (Cash Index)
- Switched S&P 500 from futures (`ES=F`) to cash index (`^GSPC`) — CFDs track the spot price, not the futures contract
- Added `"GSPC": "SPX"` mapping in Twelve Data provider for ^GSPC support
- Added `GSPC`, `SPX`, `IXIC` to `_INDEX_SYMS` set in analyzer for correct asset class detection
- Symbol normalization strips `^` prefix for Twelve Data and asset class matching
- **Files**: `config.yaml`, `modules/data/twelvedata_provider.py`, `app/services/analyzer.py`

#### Timeframe Selector
- 6 timeframes switchable with one click: 5m, 15m, 1H, 4H, 1D (default), 1W
- New `GET /api/ohlc/{symbol}?tf=` endpoint with per-timeframe data range config
- 4H timeframe created by resampling 1H data via pandas `.resample("4h")`
- EMA20/50 overlays on all timeframes
- Intraday charts use unix timestamps, daily/weekly use date strings
- **Files**: `app/api/analysis.py`, `app/templates/asset_detail.html`

#### Live Chart Updates
- 30-second polling via `GET /api/quote/{symbol}` (yfinance `fast_info`, free, zero credits)
- WebSocket push from monitor's light poll (every 2 min, when active)
- Last candle's close/high/low update with each tick via `candleSeries.update()`
- Blinking LIVE badge on chart when updates are active
- New `GET /api/quote/{symbol}` endpoint
- **Files**: `app/api/analysis.py`, `app/templates/asset_detail.html`

#### EMA50 Data Fix
- Increased daily data fetch from 60 days to 10 months (`period="10mo"`)
- Twelve Data fallback increased from 60 to 200 bars
- Result: 211 candles, 162 EMA50 data points (was only 1)
- **Files**: `modules/price_data.py`

#### Action Plan
- Plain-English step-by-step trading instructions below the chart
- **Tradeable**: entry instruction, SL placement, TP target, MTF context, sentiment/Polymarket confirmation, execution rules
- **Non-tradeable**: numbered reasons why, what needs to change, "Stay flat" instruction
- Yellow warnings for imminent calendar events, borderline QS, Polymarket conflicts
- **Files**: `app/templates/asset_detail.html`

#### Enhanced Polymarket Card
- Signal badge (BULLISH/BEARISH/NEUTRAL) with confidence
- Summary stats: market count, total volume, bull/bear probability breakdown
- Top 5 markets with: question, YES/NO probability bar, impact direction, magnitude (1-5), volume, expiry
- Pass-through of `net_score`, `bullish_prob`, `bearish_prob`, `total_volume` from pipeline
- **Files**: `app/templates/asset_detail.html`, `app/services/analyzer.py`

#### Delete Trade
- New `DELETE /api/trades/{trade_id}` endpoint with 404 handling
- Delete button on each trade row with confirmation dialog
- **Files**: `app/api/trades.py`, `app/templates/trades.html`

#### Telegram Test Fix
- `POST /api/telegram/test` returned 500 when chat ID was wrong — `NotificationPermanent` was uncaught
- Now returns 400 with clear error message ("Chat not found")
- **Files**: `app/api/settings.py`

#### Documentation Rewrite
- Deleted `ROADMAP.md`, `ROADMAP-ENGINEERING.md`, `ROADMAP-TRADING.md`
- Complete README rewrite: English, reflects current 3-asset system, all features, project structure, wiki links
- New `docs/architecture.md`: system design, component diagram, data flows, DB schema, caching, resilience
- New `docs/strategy.md`: indicators, composite scoring, QS, MTF, SL/TP, 9 entry conditions, backtest gaps
- New `docs/api.md`: complete API reference with request/response JSON examples
- New `docs/deployment.md`: local dev, Docker (full vs lite), PostgreSQL, backups, production setup
- New `docs/configuration.md`: all env vars, .env setup, config.yaml, priority chain, external API keys
- **Files**: `README.md`, `docs/architecture.md`, `docs/strategy.md`, `docs/api.md`, `docs/deployment.md`, `docs/configuration.md`

---

## v6.1.0 — 21 March 2026

### Unified Strategy Module & VBT Backtester

Single source of truth for trading strategy shared between live system and backtester.

#### Unified Strategy Module
- New `modules/strategy.py` — regime classification, indicator labeling, composite scoring, quality score, SL/TP computation
- Regime-aware indicator labeling: RSI, MACD, EMA, BBands, Stochastic adapt thresholds based on ADX (TRENDING/RANGING/NEUTRAL)
- Weighted composite scoring: momentum indicators 1.5x in trending, mean-reversion 1.5x in ranging, 60% threshold
- Quality Score from OHLCV: confluence, strong trend, near key level, candle pattern, volume above average
- Candle pattern detection: engulfing, pin bar, inside bar
- Key levels: pivot points (PP, R1, R2, S1, S2), PDH/PDL/PDC, psychological levels
- Per-class SL/TP defaults: forex (1.2x/3.0x ATR), commodity (1.5x/3.5x), index (2.0x/4.0x), stock (1.8x/3.0x)
- Adaptive SL/TP: ATR percentile adjustment based on 20-bar rolling mean
- **Files**: `modules/strategy.py`

#### VectorBT Backtester
- New `modules/vbt_backtester.py` — production backtester using shared strategy module
- Realistic trade simulation: spread, slippage, commission modeling
- Walk-forward bar-by-bar SL/TP exit simulation
- Per-class cost models and point values from `ASSET_UNIVERSE`
- Signal deduplication (suppress consecutive same-direction signals)
- USD-denominated P&L and equity curve
- Risk metrics: Sharpe, Sortino, Calmar, max drawdown, Kelly fraction
- **Files**: `modules/vbt_backtester.py`

#### Data Providers
- Twelve Data provider with symbol mapping and quote fetching
- yfinance provider with retry logic and data validation
- **Files**: `modules/data/twelvedata_provider.py`, `modules/data/yfinance_provider.py`

#### Live System Refactored
- `modules/price_data.py` uses `strategy.label_*()` for indicator labeling
- `modules/price_data.py` uses `strategy.compute_composite()` for scoring
- `app/services/analyzer.py` uses `strategy.compute_sl_tp()` for SL/TP
- Old backtester (`modules/backtester.py`) marked as deprecated _(deleted in v6.4.0)_

---

## v6.0.0 — 20 March 2026

### Advanced Trading System

Sprint 6 del piano unificato: funzionalita' di trading avanzate per migliorare l'edge.

#### Intermarket Analysis (T5.3)
- `compute_intermarket_signals()` in `modules/price_data.py`
- Analisi divergenza DXY/Gold, Yields/Equities
- Warning automatico quando correlazioni attese divergono
- **Files**: `modules/price_data.py`

#### Advanced Candle Patterns (T1.3)
- `_detect_candle_pattern()` rileva: ENGULFING, PIN_BAR, INSIDE_BAR
- Pattern label incluso nell'output di analisi
- **Files**: `modules/price_data.py`

#### Kelly Criterion Position Sizing (T2.2)
- `kelly_position_size()` nel backtester
- Half-Kelly capped (floor 0.25%, ceiling 2%)
- Integrato nell'output del backtesting
- **Files**: `modules/backtester.py` _(deleted in v6.4.0)_

#### Monte Carlo Simulation (T4.3)
- 1000 permutazioni dell'equity curve
- Output: median + 5th/95th percentile bands
- Distribuzione statistica del max drawdown
- **Files**: `modules/backtester.py` _(deleted in v6.4.0)_

#### Portfolio Heat Map (T6.1)
- Endpoint `GET /api/analytics/heatmap`
- Matrice correlazione rolling 30 giorni per tutti gli asset
- **Files**: `app/api/analytics_api.py`

---

## v5.7.0 — 20 Marzo 2026

### Secure & Tested

Sprint 5 del piano unificato: sicurezza e testing.

#### API Key Authentication (E4.1)
- `APIKeyMiddleware` in `app/middleware/auth.py`
- Header `X-API-Key` o query param `api_key`
- Abilitato solo con env var `TRADING_COPILOT_API_KEY`
- Endpoint health e static esclusi
- Login page in `app/templates/login.html` _(deleted in v6.4.0)_
- **Files**: `app/middleware/auth.py`, `app/templates/login.html` _(deleted in v6.4.0)_, `app/server.py`

#### Walk-Forward Optimization (T4.2)
- Metodo `walk_forward()` nel `BacktestEngine`
- Rolling window: train su N giorni, test su M
- Confronto in-sample vs out-of-sample performance
- **Files**: `modules/backtester.py` _(deleted in v6.4.0)_

#### Separate ML Dependencies (E7.2)
- `requirements-base.txt` — dipendenze core (senza torch/transformers)
- `requirements-ml.txt` — torch + transformers
- Dockerfile target `lite`: immagine < 500MB vs 3GB+ full
- **Files**: `requirements-base.txt`, `requirements-ml.txt`, `Dockerfile`

---

## v5.6.0 — 20 Marzo 2026

### Smart Signals + Async

Sprint 4 del piano unificato: segnali migliori, esecuzione piu' veloce.

#### Adaptive Indicator Weights (T1.1)
- Pesi dinamici basati su ADX (trending vs ranging vs volatile)
- TRENDING: EMA x2, ADX x2, RSI x0.5
- RANGING: RSI x2, BB x2, Stoch x2, EMA x0.5
- Composite score pesato: `sum(signal * weight) / sum(weights)`
- **Files**: `modules/price_data.py`

#### ATR-Adaptive SL/TP (T2.1)
- ATR percentile vs ultimi 50 giorni
- HIGH VOL (>80th): SL = ATR x 1.0 (stretto)
- LOW VOL (<20th): SL = ATR x 2.0 (largo)
- NORMAL: SL = ATR x 1.5
- **Files**: `app/services/analyzer.py`, `modules/price_data.py`

#### Async HTTP Client (E2.2)
- `httpx` per chiamate HTTP async dirette
- Migrazione a `AsyncGroq` per sentiment
- **Files**: `modules/sentiment.py`, `modules/polymarket.py`, `requirements.txt`

#### Query Optimization (E3.1)
- `get_asset_by_symbol()` — query diretta con WHERE
- Indici DB aggiunti per trade analytics e notification rate limiting
- **Files**: `app/models/database.py`

---

## v5.5.0 — 20 Marzo 2026

### Backtesting MVP

Sprint 3 del piano unificato: validazione regole di trading su dati storici.

#### Backtester Core (T4.1)
- `BacktestEngine` in `modules/backtester.py` _(deleted in v6.4.0)_
- `compute_indicators()`, `generate_signals()`, `simulate_trades()`, `compute_statistics()`
- Metriche: win rate, profit factor, max drawdown, Sharpe ratio, avg R-multiple
- CLI: `python -m modules.backtester --symbol NQ=F --period 6mo`
- 36 test dedicati in `tests/test_backtester.py`
- **Files**: `modules/backtester.py` _(deleted in v6.4.0)_, `tests/test_backtester.py` _(deleted in v6.4.0)_

#### Rate Limiting (E4.2)
- `slowapi` rate limiter middleware
- 60 req/min per endpoint analisi, 10 req/min per monitor start/stop
- Unlimited per health, static, WebSocket
- **Files**: `app/middleware/rate_limit.py`, `app/api/analysis.py`, `app/api/monitor.py`, `app/server.py`

#### Transaction Boundaries (E3.2)
- Signal persistito in DB PRIMA dei side-effects (Telegram, WebSocket)
- Ogni side-effect in try/except individuale
- **Files**: `app/services/monitor.py`

#### LLM News Summarizer (T3.2)
- `summarize_news_with_llm()` in `modules/news_fetcher.py`
- Distilla articoli in N bullet points concisi
- Fallback a titoli se LLM non disponibile
- **Files**: `modules/news_fetcher.py`, `app/services/analyzer.py`

---

## v5.4.0 — 20 Marzo 2026

### Resilient & Fast

Sprint 2 del piano unificato: resilienza e caching.

#### Circuit Breaker (E1.2)
- `CircuitBreaker` in `modules/circuit_breaker.py` (closed/open/half-open)
- Pre-configurati: `yfinance_breaker`, `groq_breaker`, `polymarket_breaker`, `rss_breaker`
- 3 fallimenti → circuito aperto → retry dopo 5 minuti
- 11 test in `tests/test_circuit_breaker.py`
- **Files**: `modules/circuit_breaker.py`, `tests/test_circuit_breaker.py`

#### Response Caching (E2.1)
- `AnalysisCache` in `app/services/cache.py` — in-memory con TTL
- TTL: price 60s, news 300s, sentiment 600s, calendar 3600s, polymarket 600s
- Cache hit/miss stats nel health check
- 11 test in `tests/test_cache.py`
- **Files**: `app/services/cache.py`, `app/services/analyzer.py`, `tests/test_cache.py`

#### Extended Health Check (E6.2)
- Verifica: DB connectivity, monitor heartbeat, cache stats, circuit breaker states, drawdown breaker
- Ritorna 503 se degradato
- **Files**: `app/api/health.py`

#### Structured Logging (E6.3)
- `JSONFormatter` + `CorrelationIDMiddleware` in `app/middleware/logging.py`
- RotatingFileHandler (10MB x 5 file)
- Attivabile via `TRADING_COPILOT_JSON_LOGS=true`
- **Files**: `app/middleware/logging.py`, `app/server.py`

#### LLM Trade Thesis (T3.1)
- `_build_trade_thesis()` in `app/services/analyzer.py`
- Ragionamento strutturato: direction, conviction, thesis, risks, catalysts, invalidation
- Campo `trade_thesis` nell'output analisi
- **Files**: `app/services/analyzer.py`

---

## v5.3.0 — 20 Marzo 2026

### Production-Stable Foundation

Sprint 1 del piano unificato: stabilita' produzione, error handling, resilienza base.

#### Fix Reload in Production (E6.1)
- `reload=True` condizionato a env var `TRADING_COPILOT_DEV=true`
- **Files**: `run_webapp.py`

#### Pin Dependencies (E7.1)
- `requirements.lock` con versioni esatte
- Dockerfile usa `requirements.lock`
- **Files**: `requirements.lock`, `Dockerfile`

#### Custom Exception Hierarchy (E1.1)
- `TradingCopilotError` base → `TransientError`, `PermanentError`
- Sotto-gerarchie: Data, API, LLM, Notification, Config, Analysis
- Rimpiazzati 59+ bare `except Exception`
- 17 test in `tests/test_exceptions.py`
- **Files**: `modules/exceptions.py`, `modules/price_data.py`, `modules/sentiment.py`, `modules/polymarket.py`

#### Retry with Exponential Backoff (E1.3)
- Decoratori `tenacity`: `retry_transient()`, `retry_data_fetch()`, `retry_llm()`, `retry_external_api()`
- Rimossi 3 loop di retry manuali (price_data, sentiment, polymarket)
- **Files**: `modules/retry.py`, `modules/price_data.py`, `modules/sentiment.py`, `modules/polymarket.py`

#### Graceful Shutdown (E6.4)
- `wait=True` con timeout 30s nel monitor shutdown
- SIGTERM/SIGINT handler per completare il polling cycle corrente
- **Files**: `app/services/monitor.py`, `app/server.py`

#### Drawdown Circuit Breaker (T2.3)
- `DrawdownCircuitBreaker` in `modules/circuit_breaker_drawdown.py`
- Query Trade table per daily/weekly P&L
- Default: -100 pips/day, -250 pips/week
- Monitor controlla breaker prima di generare segnali
- 7 test in `tests/test_drawdown_breaker.py`
- **Files**: `modules/circuit_breaker_drawdown.py`, `app/services/monitor.py`, `tests/test_drawdown_breaker.py`

---

## v5.2.0 — 20 Marzo 2026

### Production-Ready Configuration

Refactoring completo della gestione configurazione per ambienti di produzione.

#### 12.1 Pydantic Settings
- `app/config.py` riscritto con `pydantic-settings` (BaseSettings)
- Configurazione tipizzata e validata con Pydantic v2
- Priorita': env vars > `.env` file > `config.yaml` > defaults Pydantic
- `config.yaml` e' ora **opzionale** — l'app funziona senza con defaults ragionevoli
- Aggiunta dipendenza `pydantic-settings>=2.0.0`
- **Files**: `app/config.py`, `requirements.txt`

#### 12.2 Secrets in Environment Variables
- Rimossi secrets da `config.yaml` (Telegram bot token, chat ID)
- Tutti i secrets esclusivamente da env vars: `GROQ_API_KEY`, `TWELVE_DATA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`
- App settings sovrascrivibili via env: `GROQ_MODEL`, `LOOKBACK_HOURS`, `REPORT_LANGUAGE`
- `.env.example` aggiornato come unico riferimento configurazione
- **Files**: `config.yaml`, `.env.example`

#### 12.3 Telegram Settings in Database
- Nuova tabella `TelegramConfig` in SQLAlchemy ORM (singleton, id=1)
- Settings page salva/legge da database (non piu' scrittura su `config.yaml`)
- Seed automatico da env vars al primo avvio (se DB vuoto)
- `get_notifier_from_db()` per il monitor (legge config aggiornata dal DB)
- Rimosso `save_config()` e `reload_config()` — nessuna scrittura su YAML
- **Files**: `app/models/database.py`, `app/api/settings.py`, `app/services/notifier.py`, `app/services/monitor.py`

#### 12.4 RSS Feeds in Database
- Nuova tabella `RssFeed` in SQLAlchemy ORM
- Seed da `config.yaml` (se presente) o da `DEFAULT_RSS_FEEDS` hardcoded
- RSS feeds caricati dal DB in `app.state.config` al startup
- `config.yaml` rinominato key `assets` → `seed_assets` (backward compat mantenuta)
- **Files**: `app/models/database.py`, `app/server.py`, `app/config.py`

#### 12.5 Documentazione
- README riscritto: sezione configurazione, tabella env vars, config.yaml opzionale
- CHANGELOG aggiornato con v5.2.0
- ROADMAP aggiornato con Phase 12

---

## v5.1.0 — 20 Marzo 2026

### Asset in Database + News/Polymarket per Asset + Chart Fix

#### 11.1 Asset in Database
- Nuova tabella `Asset` in SQLAlchemy ORM (`app/models/database.py`)
- Seed automatico da `config.yaml` al primo avvio (tabella vuota → import)
- CRUD asset via database (non piu' scrittura su `config.yaml`)
- Dashboard, asset detail, trades caricano asset dal DB
- **Files**: `app/models/database.py`, `app/api/assets.py`, `app/server.py`, `app/config.py`

#### 11.2 News per Asset
- Nuovo `fetch_news_for_asset()` in `modules/news_fetcher.py`
- Aggiunge RSS Yahoo Finance specifico per simbolo (es. `headline?s=AAPL`)
- Filtra articoli per rilevanza (solo quelli che menzionano l'asset)
- Fallback a lista completa se meno di 3 risultati rilevanti
- Prima: 60+ articoli generici. Dopo: ~5 articoli specifici per asset
- **Files**: `modules/news_fetcher.py`, `app/services/analyzer.py`

#### 11.3 TradingView Chart Fix
- Chart candlestick ora funzionante con dati OHLC reali (era vuoto)
- Overlay EMA20 (blu) e EMA50 (viola) sul grafico
- Linee orizzontali per key levels (PDH, PDL, PDC, PP, R1, S1)
- Caricamento automatico chart all'apertura pagina (senza cliccare Analyze)
- Nuovo endpoint `GET /api/chart/{symbol}` per caricamento veloce
- Fix bug `nearest_level` JS (struttura API piatta, non annidata)
- Fix duplicazione serie su ri-analisi (ricreazione chart)
- **Files**: `app/templates/asset_detail.html`, `app/api/analysis.py`, `app/services/analyzer.py`, `modules/price_data.py`

#### 11.4 Pulizia
- Rimosso `ROADMAP-WEBAPP.md` (completato, storico in CHANGELOG)
- Rimosso `docs/Main.md` (duplicato di README)
- Aggiornati README, CHANGELOG, ROADMAP

---

## v5.0.0 — 20 Marzo 2026

### Web Dashboard Completa

Trasformazione da CLI tool a web dashboard real-time per trading CFD.
Tutti i moduli CLI (`modules/`) restano invariati — il web app e' un layer sopra.

---

### Phase 10 — Docker & PostgreSQL

#### 10.4 Comandi Operativi (20 Marzo 2026)
- Documentazione comandi Docker (up, down, logs, backup, restore)
- Profilo `lite` per avvio solo con SQLite

#### 10.3 Alembic Migrations (20 Marzo 2026)
- `alembic.ini` configurato per async engine
- `alembic/env.py` con supporto SQLite e PostgreSQL
- Migration iniziale `e1b5a34759a7_initial_schema.py` (tutte le tabelle)
- Auto-create tabelle al startup FastAPI

#### 10.2 Docker Compose (20 Marzo 2026)
- `docker-compose.yml` con `trading-app` + `postgres:16-alpine`
- Volume `pgdata` per persistenza dati PostgreSQL
- Volume mount `config.yaml` (read-only) e `reports/`
- Environment variables per secrets (da `.env`)
- Healthcheck su entrambi i servizi
- `.env.example` template per configurazione

#### 10.1 Dockerfile (20 Marzo 2026)
- `Dockerfile` multi-stage (builder + runtime) con `python:3.12-slim`
- Utente non-root `trader` per sicurezza
- Healthcheck integrato su `/api/health`
- `.dockerignore` per escludere `.venv/`, `__pycache__/`, `.git/`, `.env`

---

### Phase 9 — Trade Journal & Analytics

#### 9.3 Signal History (20 Marzo 2026)
- Pagina `/signals` con tabella storica di tutti i segnali generati
- Filtro per outcome (PENDING, TP_HIT, SL_HIT, MANUAL)
- Modal per aggiornare outcome di un segnale con prezzo di uscita
- Endpoint `GET /api/signals`, `PUT /api/signals/{id}/outcome`
- Endpoint `GET /api/signals/analytics` (win rate teorico)
- **Files**: `app/templates/signals.html`, `app/api/trades.py` (esteso)

#### 9.2 Performance Analytics (20 Marzo 2026)
- Pagina `/analytics` con metriche di performance complete
- 6 KPI cards: Win Rate, Profit Factor, Avg R-Multiple, Max Drawdown, Total Trades, Best Trade
- Equity curve con TradingView Lightweight Charts
- Rolling win rate (finestra 20 trade)
- Distribuzione R-multiple (istogramma)
- Breakdown per regime, Quality Score, direzione, simbolo
- Insights automatici generati dal sistema
- **Files**: `app/templates/analytics.html`, `app/api/trades.py` (esteso)

#### 9.1 Trade Journal UI (20 Marzo 2026)
- Pagina `/trades` con tabella trade filtrabili (per asset, direzione)
- Modal "New Trade" per registrare un trade manualmente
- Bottone "Close" su trade aperti per registrare exit price
- Import CSV da `trade_log.csv` (migrazione dati esistenti)
- Auto-calcolo P&L (pips) e R-multiple da entry/exit/SL
- Endpoint `GET/POST/PUT /api/trades`, `POST /api/trades/import-csv`
- **Files**: `app/templates/trades.html`, `app/api/trades.py`

---

### Phase 8 — Real-Time Monitor

#### 8.3 WebSocket Real-Time Push (20 Marzo 2026)
- Endpoint WebSocket `/ws/signals` con `ConnectionManager` singleton
- Broadcast a tutti i client connessi (price_update, signal, regime_change, calendar_alert)
- Client JS (`app/static/js/websocket.js`) con auto-reconnect (3s)
- Custom DOM events (`ws:price_update`, `ws:signal`, etc.)
- Browser notifications su segnale rilevato
- Badge nel titolo tab, status dot nella navbar
- **Files**: `app/api/websocket.py`, `app/static/js/websocket.js`

#### 8.2 Signal Detection Engine (20 Marzo 2026)
- 9 condizioni di entry: regime direzionale, EMA trend, VWAP position, RSI non estremo, QS >= 4, MTF aligned, session quality, no calendario entro 2h, setup tradeable
- `DetectionResult` dataclass con fired/direction/entry/sl/tp/conditions
- Calcolo Entry/SL/TP: SL = ATR x 1.5, TP = R:R 1:2
- Signal fired solo quando TUTTE le 9 condizioni sono vere
- **Files**: `app/services/signal_detector.py`

#### 8.1 Background Price Monitor (20 Marzo 2026)
- `AssetMonitor` con APScheduler `AsyncIOScheduler`
- `start(symbol, interval)`, `stop(symbol)`, `get_status()`
- Ciclo polling: analyze → detect → broadcast WebSocket → save DB → Telegram
- Stato persistito in tabella `MonitorSession` (sopravvive a restart)
- `restore_from_db()` al startup per ripristinare monitor attivi
- Endpoint `POST /api/monitor/start`, `POST /api/monitor/stop`, `GET /api/monitor/status`
- **Files**: `app/services/monitor.py`, `app/api/monitor.py`

---

### Phase 7 — Telegram Notifications

#### 7.2 Notification Triggers (20 Marzo 2026)
- Notifica su analisi manuale (bottone "Send to Telegram")
- Notifica automatica su segnale rilevato dal monitor
- Notifica su cambio regime e evento calendario imminente
- Rate limiting: max 1 notifica per asset ogni 15 minuti (tabella `NotificationLog`)
- Endpoint `POST /api/analyze/{symbol}/telegram`
- **Files**: `app/services/notifier.py` (esteso), `app/api/analysis.py` (esteso)

#### 7.1 Telegram Bot Setup (20 Marzo 2026)
- `TelegramNotifier` con metodi: `send_signal()`, `send_regime_change()`, `send_calendar_alert()`, `send_monitor_status()`, `send_test()`
- Formato messaggio strutturato con entry/SL/TP/QS/MTF/regime
- Configurazione in `config.yaml` (sezione `telegram:`)
- Endpoint `GET/PUT /api/settings/telegram`, `POST /api/telegram/test`
- Pagina `/settings` per configurare bot token e chat ID
- **Files**: `app/services/notifier.py`, `app/api/settings.py`, `app/templates/settings.html`

---

### Phase 6 — Single-Asset Analysis Page

#### 6.3 Entry/SL/TP Calculator (20 Marzo 2026)
- Calcolo automatico: Entry = prezzo corrente, SL = entry -/+ ATR x 1.5, TP = R:R 1:2
- Integrazione nel signal detector per segnali automatici
- **Files**: `app/services/signal_detector.py`

#### 6.2 Asset Detail Page + Chart (20 Marzo 2026)
- Pagina `/asset/{symbol}` con analisi completa singolo asset
- Grafico TradingView Lightweight Charts (candlestick + EMA20/50 + key levels)
- Cards: Sentiment, Tecnici, Key Levels, MTF, Quality Score, Polymarket, Calendario
- Box Setup in evidenza (direzione, entry, SL, TP, QS, R:R)
- Box Regime (LONG/SHORT/NEUTRAL con ragione)
- Bottone "Monitor This Asset" per avvio background monitoring
- Bottone "Send to Telegram"
- Live price updates via WebSocket con signal flash animation
- **Files**: `app/templates/asset_detail.html`

#### 6.1 Analysis Service Layer (20 Marzo 2026)
- `analyze_single_asset(symbol)` — wrapper async dei moduli esistenti
- Orchestrazione: price_data → news → sentiment → polymarket → calendar → validation → regime
- `asyncio.to_thread()` per bridge sync → async
- Risposta JSON completa (price, sentiment, technicals, polymarket, calendar, regime, setup)
- Endpoint `POST /api/analyze/{symbol}`
- **Files**: `app/services/analyzer.py`, `app/api/analysis.py`

---

### Phase 5 — Foundation: Web App Skeleton

#### 5.3 Config Management UI (20 Marzo 2026)
- Modal nella dashboard per aggiungere/rimuovere asset
- Validazione simbolo via yfinance prima di salvare
- Auto-fill display_name dal ticker info
- `save_config()` e `reload_config()` per persistenza dinamica
- Endpoint `POST /api/assets`, `DELETE /api/assets/{symbol}`
- **Files**: `app/api/assets.py` (esteso), `app/config.py` (esteso)

#### 5.2 Dashboard HTML (20 Marzo 2026)
- Layout base `base.html` con navbar, footer, dark theme
- Dashboard con lista asset configurati, badge stato, bottone "Analyze"
- CSS custom dark theme ottimizzato per trading (no framework)
- HTMX + Alpine.js per interattivita' senza build step
- Nav links: Dashboard, Trades, Analytics, Settings
- **Files**: `app/templates/base.html`, `app/templates/dashboard.html`, `app/static/css/style.css`

#### 5.1 Struttura Progetto (20 Marzo 2026)
- Directory `app/` con struttura completa (api/, services/, models/, templates/, static/)
- `app/server.py` — FastAPI app con async lifespan (startup/shutdown)
- `app/models/database.py` — SQLAlchemy 2.0 ORM (Signal, Trade, MonitorSession, NotificationLog, AnalysisCache)
- `app/models/engine.py` — Engine factory async (SQLite + PostgreSQL)
- `app/api/health.py` — Endpoint `GET /api/health`
- `app/api/assets.py` — Endpoint `GET /api/assets`
- `app/config.py` — Gestione configurazione con `lru_cache`
- `run_webapp.py` — Entry point Uvicorn
- `requirements.txt` — Aggiornato con nuove dipendenze (FastAPI, SQLAlchemy, APScheduler, etc.)
- Alembic configurato per migrazioni async

---

## v4.1.0 — Marzo 2026

### CLI Tool — Tutte le Fasi Complete

#### Phase 4 — Selezione
- **4.2 Correlation Filter**: Matrice correlazione 30 giorni, filtro >0.7 same-direction, auto-select best QS
- **4.1 Quality Score**: Score 1-5 (confluenza, ADX>25, key level, candle pattern, volume), filtro QS >= 4

#### Phase 3 — Precisione
- **3.2 Session Filter**: Pine Script session filter (London/NYSE), dead zone blocking, countdown
- **3.1 Multi-Timeframe**: Weekly/Daily/1H EMA trend, alignment (ALIGNED/PARTIAL/CONFLICTING)

#### Phase 2 — Attacco
- **2.1 Trailing Stop**: 3 exit modes (Fixed TP, Trailing, Partial+Trail), BE at +1R, trail at +2R

#### Phase 1 — Difesa
- **1.2 Calendario Economico**: Forex Factory API, regime override entro 2h, sezione report
- **1.1 Key Levels**: PDH/PDL/PDC, PWH/PWL, Pivots, livelli psicologici, distanza %

---

*Last updated: 21 March 2026 — v6.4.0*
