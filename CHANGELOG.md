# Trading Copilot — Changelog

Storico delle modifiche al progetto, dalla versione CLI alla web dashboard.

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

*Ultimo aggiornamento: 20 Marzo 2026 — v5.2.0*
