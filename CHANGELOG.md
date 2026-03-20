# Trading Copilot — Changelog

Storico delle modifiche al progetto, dalla versione CLI alla web dashboard.

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

*Ultimo aggiornamento: 20 Marzo 2026*
