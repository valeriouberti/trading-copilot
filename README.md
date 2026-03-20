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

export GROQ_API_KEY="gsk_la_tua_chiave_qui"

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

## Setup Dettagliato

### 1. Clona il repository e crea un ambiente virtuale

```bash
git clone <url-del-repo>
cd trading-assistant

python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# oppure: venv\Scripts\activate  # Windows
```

### 2. Installa le dipendenze

```bash
pip install -r requirements.txt
```

### 3. Configura le API key

**Groq (consigliata):** Registrati su [console.groq.com](https://console.groq.com/) e crea una API key gratuita.

```bash
export GROQ_API_KEY="gsk_la_tua_chiave_qui"  # Linux/macOS
# oppure: set GROQ_API_KEY=gsk_la_tua_chiave_qui  # Windows CMD
```

> **Nota:** Se non imposti la chiave Groq, il sistema usa automaticamente FinBERT come fallback (richiede il download del modello al primo avvio, circa 400MB).

**Twelve Data (opzionale):** Fallback per i dati di prezzo quando yfinance non e' disponibile. Registrati su [twelvedata.com](https://twelvedata.com/) per una API key gratuita (800 richieste/giorno).

```bash
export TWELVE_DATA_API_KEY="la_tua_chiave_qui"
```

**Telegram (opzionale):** Per ricevere notifiche dei segnali sul telefono. Crea un bot con [@BotFather](https://t.me/BotFather).

```bash
export TELEGRAM_BOT_TOKEN="il_tuo_bot_token"
export TELEGRAM_CHAT_ID="il_tuo_chat_id"
```

> Il Telegram bot puo' essere configurato anche dalla pagina Settings della web dashboard.

Per rendere le chiavi permanenti, aggiungile al tuo `.bashrc`, `.zshrc` o profilo di sistema.

---

## Web Dashboard

### Avvio

```bash
# Locale con SQLite (zero config)
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
| GET | `/api/health` | Health check |
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
| GET/PUT | `/api/settings/telegram` | Configurazione Telegram |
| POST | `/api/telegram/test` | Invia messaggio di test |
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

---

## Docker

### Comandi Operativi

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
- **PostgreSQL** (Docker) — Concurrent access, analytics query potenti, JSONB

Configurazione in `config.yaml`:

```yaml
database:
  # SQLite (default)
  url: "sqlite+aiosqlite:///./trading.db"

  # PostgreSQL (Docker)
  # url: "postgresql+asyncpg://trading:trading@localhost:5432/trading"
```

Le tabelle vengono create automaticamente al primo avvio. Gli asset vengono importati da `config.yaml` nel DB al primo avvio (seed). Migrazioni gestite da Alembic.

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

> **Nota:** Gli asset sono gestiti nel database (tabella `assets`). Al primo avvio, gli asset vengono importati da `config.yaml` nel DB. Dopo il seed iniziale, tutte le operazioni CRUD avvengono via database.

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
├── config.yaml                      # Configurazione (feed RSS, database, telegram, seed asset)
├── Dockerfile                       # Container image multi-stage
├── docker-compose.yml               # App + PostgreSQL stack
├── .env.example                     # Template variabili d'ambiente
├── alembic.ini                      # Configurazione migrazioni
├── requirements.txt                 # Dipendenze Python
│
├── app/                             # Web Dashboard (FastAPI)
│   ├── server.py                    # FastAPI app + lifespan
│   ├── config.py                    # Gestione configurazione
│   ├── api/
│   │   ├── health.py                # GET /api/health
│   │   ├── assets.py                # CRUD asset
│   │   ├── analysis.py              # Analisi singolo asset
│   │   ├── monitor.py               # Start/stop/status monitor
│   │   ├── trades.py                # Trade journal + analytics + signals
│   │   ├── settings.py              # Configurazione Telegram
│   │   └── websocket.py             # WebSocket /ws/signals
│   ├── services/
│   │   ├── analyzer.py              # Wrapper async dei moduli esistenti
│   │   ├── signal_detector.py       # 9 condizioni entry + calcolo SL/TP
│   │   ├── monitor.py               # Background polling (APScheduler)
│   │   └── notifier.py              # Telegram + WebSocket push
│   ├── models/
│   │   ├── database.py              # SQLAlchemy ORM (Asset, Signal, Trade, etc.)
│   │   └── engine.py                # Engine factory (SQLite / PostgreSQL)
│   ├── templates/                   # Jinja2 HTML (7 pagine)
│   │   ├── base.html                # Layout base (nav, footer, dark theme)
│   │   ├── dashboard.html           # Lista asset + monitor
│   │   ├── asset_detail.html        # Grafico + analisi + setup
│   │   ├── trades.html              # Trade journal
│   │   ├── analytics.html           # Performance analytics
│   │   ├── signals.html             # Storico segnali
│   │   └── settings.html            # Configurazione Telegram
│   └── static/
│       ├── css/style.css            # Dark theme CSS
│       └── js/
│           ├── app.js               # HTMX + Alpine.js init
│           └── websocket.js         # Client WebSocket auto-reconnect
│
├── modules/                         # Engine CLI (invariato)
│   ├── news_fetcher.py              # Aggregatore notizie RSS
│   ├── price_data.py                # Dati prezzo + indicatori + key levels + MTF + QS
│   ├── sentiment.py                 # Analisi sentiment (Groq / FinBERT)
│   ├── report.py                    # Generatore report HTML
│   ├── hallucination_guard.py       # Validazione anti-allucinazione
│   ├── economic_calendar.py         # Calendario economico Forex Factory
│   ├── polymarket.py                # Segnale Polymarket (v3)
│   ├── keywords.py                  # Keyword bullish/bearish
│   └── trade_log.py                 # Registro trade CSV
│
├── alembic/                         # Migrazioni database
│   ├── env.py                       # Async migration env
│   └── versions/                    # Migration scripts
│
├── tradingview/
│   └── trading_copilot.pine         # Pine Script v6
│
├── reports/                         # Report HTML generati
└── tests/                           # Test suite (250+ test)
```

---

## Risoluzione Problemi

| Problema | Soluzione |
|----------|-----------|
| `GROQ_API_KEY non impostata` | Esporta la variabile d'ambiente (vedi Setup punto 3) |
| `No data returned for symbol` | Verifica il simbolo su Yahoo Finance. Configura `TWELVE_DATA_API_KEY` come fallback |
| `Rate limit exceeded` | Aspetta qualche minuto, Groq free tier ha limiti |
| `FinBERT download lento` | Normale al primo avvio, il modello viene cachato |
| Porta 8000 gia' occupata | Cambia porta: `uvicorn app.server:app --port 8001` |
| Errore connessione PostgreSQL | Verifica che `docker compose up postgres` sia running |
| WebSocket non si connette | Controlla che il browser supporti WS e non ci siano proxy |
| Monitor non rileva segnali | Verifica che l'asset abbia dati recenti su yfinance |

---

## Disclaimer

Questo strumento e' solo a scopo informativo e didattico. **Non costituisce consiglio finanziario.** Il trading di CFD comporta un alto rischio di perdita. Opera sempre in modo responsabile e con capitali che puoi permetterti di perdere.
