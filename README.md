# Trading Copilot

Sistema di analisi e monitoraggio real-time per trader CFD retail. Due modalita' operative:

- **CLI** (`main.py`) — Report pre-market giornaliero con analisi tecnica, sentiment macro e notizie aggregate
- **Web Dashboard** (`run_webapp.py`) — Dashboard interattiva con monitoraggio real-time, signal detection, trade journal e analytics

Pensato per chi opera manualmente su **Fineco** e usa **TradingView** per i grafici.

---

## Prerequisiti

- Python 3.10 o superiore
- Una API key gratuita di [Groq](https://console.groq.com/) (opzionale ma consigliata)
- Docker e Docker Compose (opzionale, per deploy con PostgreSQL)

---

## Quick Start

### Opzione 1: Web Dashboard (consigliata)

```bash
git clone <url-del-repo>
cd trading-assistant

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Modifica .env con le tue API key

python run_webapp.py
# Apri http://localhost:8000
```

### Opzione 2: Docker (PostgreSQL + App)

```bash
cp .env.example .env
# Modifica .env con le tue API key

docker compose up -d
# Apri http://localhost:8000
```

### Opzione 3: CLI (report batch)

```bash
python main.py
```

---

## Configurazione

### Approccio

La configurazione segue le best practice per ambienti di produzione:

| Tipo | Dove | Esempio |
|------|------|---------|
| Secrets e API keys | `.env` (env vars) | `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN` |
| Dati runtime | Database | Asset, RSS feeds, Telegram settings |
| Seed iniziale | `config.yaml` (opzionale) | Asset e feed RSS per il primo avvio |
| App settings | `.env` o defaults | `GROQ_MODEL`, `LOOKBACK_HOURS` |

**`config.yaml` e' opzionale.** Senza di esso, l'app usa defaults ragionevoli (4 feed RSS, modello Groq standard). Gli asset si aggiungono dalla dashboard.

### Priorita' configurazione

```
env vars > .env file > config.yaml > defaults Pydantic
```

### Setup minimo

Copia `.env.example` in `.env` e imposta almeno `GROQ_API_KEY`:

```bash
cp .env.example .env
```

```env
# .env
GROQ_API_KEY=gsk_la_tua_chiave_qui

# Opzionale
TWELVE_DATA_API_KEY=la_tua_chiave_qui
TELEGRAM_BOT_TOKEN=il_tuo_bot_token
TELEGRAM_CHAT_ID=il_tuo_chat_id
```

> **Nota:** Se non imposti `GROQ_API_KEY`, il sistema usa automaticamente FinBERT come fallback (richiede il download del modello al primo avvio, circa 400MB).

### Variabili d'ambiente disponibili

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./trading.db` | URL database async |
| `GROQ_API_KEY` | *(vuoto)* | Groq LLM API key |
| `TWELVE_DATA_API_KEY` | *(vuoto)* | Twelve Data fallback per dati prezzo |
| `TELEGRAM_BOT_TOKEN` | *(vuoto)* | Telegram bot token (seed in DB al primo avvio) |
| `TELEGRAM_CHAT_ID` | *(vuoto)* | Telegram chat ID |
| `TELEGRAM_ENABLED` | `false` | Abilita notifiche Telegram |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Modello Groq da usare |
| `LOOKBACK_HOURS` | `16` | Ore di lookback per le notizie |
| `REPORT_LANGUAGE` | `italian` | Lingua del report CLI |
| `TRADING_COPILOT_API_KEY` | *(vuoto)* | API key per autenticazione (disabilitata se vuota) |
| `TRADING_COPILOT_DEV` | `false` | Abilita hot-reload in sviluppo |
| `TRADING_COPILOT_JSON_LOGS` | `false` | Abilita structured JSON logging |

---

## Web Dashboard

### Avvio

```bash
# Locale con SQLite (zero config, serve solo .env)
python run_webapp.py

# Oppure con Docker + PostgreSQL
docker compose up -d
```

Apri **http://localhost:8000** nel browser.

### Pagine

| Pagina | URL | Descrizione |
|--------|-----|-------------|
| Dashboard | `/` | Lista asset, stato monitor, avvio analisi |
| Dettaglio Asset | `/asset/{symbol}` | Grafico, indicatori, setup, segnali real-time |
| Trade Journal | `/trades` | Registra e gestisci i trade |
| Analytics | `/analytics` | Win rate, profit factor, equity curve, insights |
| Signal History | `/signals` | Storico segnali generati con outcome |
| Settings | `/settings` | Configurazione Telegram |

### API Endpoints

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/api/health` | Health check esteso (DB, monitor, cache, circuit breakers) |
| GET | `/api/assets` | Lista asset configurati |
| POST | `/api/assets` | Aggiunge asset (valida via yfinance) |
| DELETE | `/api/assets/{symbol}` | Rimuove asset |
| GET | `/api/chart/{symbol}` | Dati chart OHLC + EMA (caricamento veloce) |
| POST | `/api/analyze/{symbol}` | Lancia analisi completa |
| POST | `/api/analyze/{symbol}/telegram` | Analisi + invio Telegram |
| POST | `/api/monitor/start` | Avvia monitoraggio background |
| POST | `/api/monitor/stop` | Ferma monitoraggio |
| GET | `/api/monitor/status` | Stato monitor attivi |
| GET | `/api/trades` | Lista trade (con filtri) |
| POST | `/api/trades` | Registra nuovo trade |
| PUT | `/api/trades/{id}` | Chiudi/aggiorna trade |
| GET | `/api/trades/analytics` | Metriche performance |
| POST | `/api/trades/import-csv` | Importa da trade_log.csv |
| GET | `/api/signals` | Storico segnali |
| PUT | `/api/signals/{id}/outcome` | Aggiorna outcome segnale |
| GET | `/api/signals/analytics` | Analytics segnali |
| GET/PUT | `/api/settings/telegram` | Configurazione Telegram (salvata in DB) |
| POST | `/api/telegram/test` | Invia messaggio di test |
| GET | `/api/analytics/heatmap` | Matrice correlazione portfolio |
| WS | `/ws/signals` | WebSocket push real-time |

### Monitor Real-Time

Il sistema puo' monitorare gli asset in background e inviare notifiche quando le condizioni di entry si allineano:

1. Dalla dashboard, clicca "Monitor" su un asset
2. Il sistema controlla periodicamente (ogni 60s): prezzo, indicatori tecnici, regime
3. Quando tutte le 9 condizioni sono soddisfatte → **SIGNAL FIRED**
4. Notifica via WebSocket (browser) + Telegram (telefono)

**9 condizioni di entry:**
1. Regime direzionale (LONG o SHORT)
2. EMA trend allineato alla direzione
3. Prezzo sopra/sotto VWAP
4. RSI non in zona estrema
5. Quality Score >= 4
6. MTF Aligned
7. Sessione di qualita' (London/NYSE open)
8. Nessun evento calendario entro 2h
9. Setup tradeable

### Trade Journal

Registra i trade direttamente dalla dashboard:
- Entry/exit price, SL/TP, direzione, note
- P&L e R-multiple calcolati automaticamente
- Import da `trade_log.csv` per migrare i dati esistenti

### Performance Analytics

Metriche calcolate automaticamente:
- Win rate (totale e per asset/regime/QS/direzione)
- Profit factor, Average R-multiple, Max drawdown
- Equity curve, rolling win rate (20 trade)
- Insights automatici ("QS 5 ha 72% WR vs 48% con QS 4")

---

## CLI (Report Batch)

### Esecuzione standard

```bash
python main.py
```

Il sistema:

1. Recupera le notizie dai feed RSS configurati
2. Scarica i dati di prezzo e calcola gli indicatori tecnici
3. Analizza il sentiment macro con Groq LLM (o FinBERT)
4. Genera un report HTML e lo apre nel browser

### Opzioni da riga di comando

```bash
# Analizza solo alcuni asset
python main.py --assets ES=F GC=F

# Cambia il periodo di lookback delle notizie
python main.py --hours 24

# Salta l'analisi LLM (solo indicatori tecnici)
python main.py --no-llm

# Non aprire il browser automaticamente
python main.py --no-browser

# Usa un file di configurazione diverso
python main.py --config my_config.yaml
```

> **Nota:** Il CLI usa `config.yaml` per asset e feed RSS (non il database). Per la web dashboard, tutto e' nel database.

---

## Docker — Comandi Operativi

```bash
# Avvio completo (PostgreSQL + App)
docker compose up -d

# Logs in tempo reale
docker compose logs -f trading-app

# Stop
docker compose down

# Stop e cancella dati (reset completo)
docker compose down -v

# Rebuild dopo modifiche al codice
docker compose up -d --build

# Backup database PostgreSQL
docker compose exec postgres pg_dump -U trading trading > backup.sql

# Restore database
cat backup.sql | docker compose exec -T postgres psql -U trading trading
```

### Database

Il sistema supporta due backend:

- **SQLite** (default locale) — Zero setup, `python run_webapp.py` e funziona
- **PostgreSQL** (Docker) — Concurrent access, analytics query potenti

Configurazione via variabile d'ambiente in `.env`:

```env
# SQLite (default — non serve impostare nulla)
# DATABASE_URL=sqlite+aiosqlite:///./trading.db

# PostgreSQL (Docker)
DATABASE_URL=postgresql+asyncpg://trading:password@localhost:5432/trading
```

Le tabelle vengono create automaticamente al primo avvio. Asset e RSS feeds vengono importati da `config.yaml` (se presente) o da defaults nel primo avvio. Migrazioni gestite da Alembic.

---

## Resilienza & Sicurezza (v5.3.0+)

### Error Handling
Il sistema usa una gerarchia di eccezioni tipizzate (`TransientError` vs `PermanentError`) con retry automatico via `tenacity` per errori transitori (API timeout, rate limit). Circuit breaker pattern protegge da cascading failures: dopo 3 errori consecutivi su un'API, il circuito si apre per 5 minuti.

### Caching
Pipeline di analisi con cache in-memory TTL: prezzi 60s, news 300s, sentiment 600s, calendario 3600s. Riduce il tempo di analisi ripetuta da ~15s a <1s.

### Autenticazione
API key authentication opzionale via `TRADING_COPILOT_API_KEY`. Se impostata, tutti gli endpoint (tranne health e static) richiedono header `X-API-Key` o query param `api_key`.

### Rate Limiting
60 req/min sugli endpoint di analisi, 10 req/min su start/stop monitor. Protegge da abuse accidentale o intenzionale.

### Structured Logging
JSON logging opzionale (`TRADING_COPILOT_JSON_LOGS=true`) con correlation ID per tracciare richieste end-to-end. Log rotation automatica (10MB x 5 file).

### Drawdown Protection
Circuit breaker che monitora il P&L giornaliero/settimanale dai trade registrati. Pausa automatica dei segnali se il drawdown supera le soglie configurate.

---

## Backtesting (v5.5.0+)

Valida le regole di trading su dati storici prima di operare live.

```bash
# Backtest singolo asset
python -m modules.backtester --symbol NQ=F --period 6mo

# Output: win rate, profit factor, max drawdown, Sharpe ratio
```

### Funzionalita':
- **Walk-Forward Optimization**: rolling window per evitare overfitting
- **Monte Carlo Simulation**: 1000 permutazioni dell'equity curve con bande 5th/95th percentile
- **Kelly Position Sizing**: Half-Kelly capped per rischio ottimale (0.25%–2%)
- **ATR-Adaptive SL/TP**: stop loss dinamico basato sul percentile di volatilita'
- **Adaptive Indicator Weights**: pesi dinamici basati su regime di mercato (trending/ranging/volatile)

---

## Docker (Varianti)

### Full (default, ~3GB)
```bash
docker build -t trading-copilot .
```

### Lite (senza torch/transformers, ~500MB)
```bash
docker build --target lite -t trading-copilot-lite .
```
La variante lite non include FinBERT come fallback per il sentiment — richiede `GROQ_API_KEY`.

---

## Come Interpretare il Report

### Sentiment Macro (-3 a +3)

- **+2 / +3**: Mercato fortemente rialzista — cercare opportunita' LONG
- **+1**: Moderatamente positivo — bias LONG con cautela
- **0**: Neutro — nessuna direzione chiara
- **-1**: Moderatamente negativo — bias SHORT con cautela
- **-2 / -3**: Mercato fortemente ribassista — cercare opportunita' SHORT

### Tabella Assets (15 colonne)

- **RSI**: Sotto 30 = ipervenduto (potenziale rimbalzo), Sopra 70 = ipercomprato (potenziale correzione)
- **MACD**: Crossover rialzista/ribassista indica cambio di momentum
- **BB** (Bollinger Bands): Prezzo sopra banda superiore = overextended, sotto inferiore = oversold, squeeze = breakout imminente
- **Stoch** (Stochastic): %K sotto 20 = oversold, sopra 80 = overbought, crossover = cambio momentum
- **vs VWAP**: Prezzo sopra VWAP = forza, sotto = debolezza intraday
- **EMA Trend**: EMA20 > EMA50 = trend rialzista, viceversa ribassista
- **ADX**: Sopra 25 = trend forte, sotto 20 = mercato in range (mostra +DI/-DI per direzione)
- **Score Tecnico**: 6 indicatori direzionali — BULLISH/BEARISH/NEUTRAL con % di confidenza
- **MTF**: Multi-Timeframe Alignment — ALIGNED (Weekly+Daily+1H concordano), PARTIAL (2/3), CONFLICTING
- **QS**: Quality Score (0-5) — confluenza, ADX>25, key level, candle pattern, volume
- **Azione**: Suggerimento sintetico basato su tecnici + sentiment

### Suggerimento per il trading

1. Se Score Tecnico, LLM Bias e Polymarket concordano → **Triple Confluence**, segnale piu' affidabile
2. Se sono in conflitto → massima cautela, meglio attendere
3. Quality Score >= 4 → setup ad alta probabilita'. Sotto 4 → skip
4. Controlla la matrice correlazione: non aprire trade nella stessa direzione su NQ e ES simultaneamente
5. Usa sempre il report come **punto di partenza**, poi verifica su TradingView

---

## Aggiungere Nuovi Asset

**Via Web Dashboard:** Dalla dashboard, clicca "Add Asset", inserisci il simbolo Yahoo Finance. Il sistema valida il simbolo automaticamente via yfinance e lo salva nel database.

I simboli seguono la convenzione Yahoo Finance:

- Futures: `ES=F`, `NQ=F`, `GC=F`, `CL=F`
- Forex: `EURUSD=X`, `GBPUSD=X`
- Indici: `^GSPC`, `^IXIC`
- Azioni: `AAPL`, `MSFT`

---

## Integrazione Polymarket

Il sistema integra i dati dei **mercati predittivi di Polymarket** come terzo segnale di conferma. Le probabilita' riflettono l'opinione aggregata del mercato e forniscono un segnale complementare all'analisi tecnica e al sentiment LLM.

Il modulo (v3) utilizza l'endpoint `/events` dell'API Gamma con **tag_slug curati** per asset class (es. `fed`, `gdp`, `tariffs`, `gold`, `oil`).

```bash
# CLI senza Polymarket
python main.py --no-polymarket
```

> **Nota:** L'API Polymarket e' gratuita e pubblica, non serve nessuna API key.

---

## Struttura del Progetto

```
trading-assistant/
├── main.py                          # Entry point CLI
├── run_webapp.py                    # Entry point Web Dashboard
├── .env.example                     # Template variabili d'ambiente (UNICO file config richiesto)
├── config.yaml                      # Seed data opzionale (primo avvio)
├── Dockerfile                       # Container image multi-stage (full + lite)
├── docker-compose.yml               # App + PostgreSQL stack
├── alembic.ini                      # Configurazione migrazioni
├── requirements.txt                 # Dipendenze Python (range)
├── requirements.lock                # Dipendenze pinned (per build riproducibili)
├── requirements-base.txt            # Dipendenze core (senza ML)
├── requirements-ml.txt              # torch + transformers (opzionale)
│
├── app/                             # Web Dashboard (FastAPI)
│   ├── server.py                    # FastAPI app + lifespan (v6.0.0)
│   ├── config.py                    # Pydantic Settings (env vars + YAML fallback)
│   ├── api/
│   │   ├── health.py                # GET /api/health (esteso: DB, cache, breakers)
│   │   ├── assets.py                # CRUD asset (database)
│   │   ├── analysis.py              # Analisi singolo asset (rate limited)
│   │   ├── analytics_api.py         # Portfolio heatmap endpoint
│   │   ├── monitor.py               # Start/stop/status monitor (rate limited)
│   │   ├── trades.py                # Trade journal + analytics + signals
│   │   ├── settings.py              # Configurazione Telegram (database)
│   │   └── websocket.py             # WebSocket /ws/signals
│   ├── middleware/
│   │   ├── auth.py                  # API key authentication
│   │   ├── logging.py               # JSON structured logging + correlation ID
│   │   └── rate_limit.py            # Rate limiting (slowapi)
│   ├── services/
│   │   ├── analyzer.py              # Pipeline async con cache + trade thesis + news summary
│   │   ├── cache.py                 # In-memory TTL cache per pipeline stages
│   │   ├── signal_detector.py       # 9 condizioni entry + SL/TP adattivo
│   │   ├── monitor.py               # Background polling + graceful shutdown + drawdown check
│   │   └── notifier.py              # Telegram + WebSocket push
│   ├── models/
│   │   ├── database.py              # SQLAlchemy ORM (Asset, RssFeed, Signal, Trade, etc.)
│   │   └── engine.py                # Engine factory (SQLite / PostgreSQL)
│   ├── templates/                   # Jinja2 HTML (8 pagine incl. login)
│   └── static/                      # CSS dark theme + JS (HTMX, Alpine.js, WebSocket)
│
├── modules/                         # Engine Core
│   ├── exceptions.py                # Gerarchia eccezioni tipizzate
│   ├── retry.py                     # Retry decorators (tenacity)
│   ├── circuit_breaker.py           # Circuit breaker per API esterne
│   ├── circuit_breaker_drawdown.py  # Drawdown circuit breaker (daily/weekly P&L)
│   ├── backtester.py                # Backtesting engine + walk-forward + Monte Carlo
│   ├── news_fetcher.py              # Aggregatore notizie RSS + LLM summarizer
│   ├── price_data.py                # Dati prezzo + indicatori adattivi + intermarket + candle patterns
│   ├── sentiment.py                 # Analisi sentiment (Groq / FinBERT) con retry tipizzato
│   ├── report.py                    # Generatore report HTML
│   ├── hallucination_guard.py       # Validazione anti-allucinazione
│   ├── economic_calendar.py         # Calendario economico Forex Factory
│   ├── polymarket.py                # Segnale Polymarket (v3) con retry tipizzato
│   ├── keywords.py                  # Keyword bullish/bearish
│   └── trade_log.py                 # Registro trade CSV
│
├── alembic/                         # Migrazioni database
├── tradingview/
│   └── trading_copilot.pine         # Pine Script v6
│
├── reports/                         # Report HTML generati
└── tests/                           # Test suite (383 test)
```

---

## Risoluzione Problemi

| Problema | Soluzione |
|----------|-----------|
| `GROQ_API_KEY non impostata` | Crea `.env` da `.env.example` e imposta la chiave |
| `No data returned for symbol` | Verifica il simbolo su Yahoo Finance. Configura `TWELVE_DATA_API_KEY` come fallback |
| `Rate limit exceeded` | Aspetta qualche minuto, Groq free tier ha limiti. Il circuit breaker pausera' le chiamate automaticamente |
| `FinBERT download lento` | Normale al primo avvio, il modello viene cachato. Usa variante `lite` Docker se non serve |
| Porta 8000 gia' occupata | Cambia porta: `uvicorn app.server:app --port 8001` |
| Errore connessione PostgreSQL | Verifica che `docker compose up postgres` sia running |
| WebSocket non si connette | Controlla che il browser supporti WS e non ci siano proxy |
| Monitor non rileva segnali | Verifica: asset ha dati recenti su yfinance, drawdown breaker non e' scattato (`/api/health`) |
| `config.yaml` non trovato | Normale — il file e' opzionale. Usa `.env` per la configurazione |
| `401 Unauthorized` | `TRADING_COPILOT_API_KEY` e' impostata. Aggiungi header `X-API-Key` o usa la login page |
| `429 Too Many Requests` | Rate limit raggiunto. Aspetta 1 minuto per endpoint analisi, riprova |
| Circuit breaker aperto | Un'API esterna e' down. Il circuito si richiude dopo 5 minuti. Controlla `/api/health` |

---

## Disclaimer

Questo strumento e' solo a scopo informativo e didattico. **Non costituisce consiglio finanziario.** Il trading di CFD comporta un alto rischio di perdita. Opera sempre in modo responsabile e con capitali che puoi permetterti di perdere.
