# Trading Copilot — Web App Roadmap v5.0

Da CLI tool a web dashboard per trading CFD in tempo reale.

> **Principio guida**: i moduli esistenti (`modules/`) restano invariati.
> Il web app e' un layer sopra, non una riscrittura. Il CLI `main.py` continua a funzionare.

---

## Architettura Target

```

Browser (Dashboard)
     │
     ├── GET  /                        → Dashboard con lista asset
     ├── GET  /asset/{symbol}          → Pagina dettaglio singolo asset
     ├── POST /api/analyze/{symbol}    → Lancia analisi completa
     ├── POST /api/monitor/start       → Avvia monitoraggio background
     ├── POST /api/monitor/stop        → Ferma monitoraggio
     ├── GET  /api/signals/history     → Storico segnali
     ├── GET  /api/trades              → Trade journal
     ├── WS   /ws/signals              → Push real-time segnali
     │
┌─────────────────────────────────────────────────────┐
│              Docker Compose (opzionale)               │
│  ┌──────────────────────┐  ┌───────────────────────┐ │
│  │  trading-app          │  │  postgres:16-alpine   │ │
│  │  (FastAPI + modules)  │←→│  (oppure SQLite)      │ │
│  │  Port 8000            │  │  Port 5432            │ │
│  └──────────────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────┘

FastAPI Backend
     │
     ├── app/
     │   ├── server.py                 → FastAPI app + startup/shutdown
     │   ├── api/
     │   │   ├── assets.py             → CRUD asset, lista, config
     │   │   ├── analysis.py           → Endpoint analisi singolo asset
     │   │   ├── monitor.py            → Start/stop/status monitor
     │   │   └── trades.py             → Trade journal endpoints
     │   ├── services/
     │   │   ├── analyzer.py           → Wrappa modules/ esistenti
     │   │   ├── signal_detector.py    → Rileva condizioni entry
     │   │   ├── monitor.py            → Background worker polling
     │   │   └── notifier.py           → Telegram + WebSocket push
     │   ├── models/
     │   │   ├── database.py           → SQLAlchemy models (SQLite o PostgreSQL)
     │   │   └── engine.py             → Engine factory (sceglie backend da config)
     │   ├── templates/                → Jinja2 HTML
     │   └── static/                   → CSS, JS, immagini
     │
     ├── modules/                      → INVARIATI (engine esistente)
     │   ├── price_data.py
     │   ├── sentiment.py
     │   ├── news_fetcher.py
     │   ├── polymarket.py
     │   ├── economic_calendar.py
     │   ├── hallucination_guard.py
     │   ├── trade_log.py
     │   └── keywords.py
     │
     ├── main.py                       → CLI (invariato, continua a funzionare)
     ├── Dockerfile                    → Container image
     └── docker-compose.yml            → App + PostgreSQL stack

```

---

## Stack Tecnologico

| Componente | Scelta | Motivazione |
|------------|--------|-------------|
| Backend | **FastAPI** | Async nativo, WebSocket built-in, Python (riusa modules/) |
| Templates | **Jinja2** | Built-in FastAPI, niente build step Node |
| Frontend JS | **HTMX + Alpine.js** | Interattivita' senza framework pesanti |
| Grafici | **TradingView Lightweight Charts** | Open source, real-time, professionale |
| Real-time | **WebSocket** (FastAPI native) | Push segnali al browser istantaneamente |
| Notifiche | **python-telegram-bot** | Standard per trader, funziona da telefono |
| Background | **APScheduler** | Job periodici (polling prezzo, news refresh) |
| ORM | **SQLAlchemy 2.0 + alembic** | Astrae il database — stesse query per SQLite e PostgreSQL |
| DB (dev) | **SQLite** | Zero setup, `python run_webapp.py` e funziona |
| DB (docker) | **PostgreSQL 16** | Concurrent access, analytics query potenti, JSONB |
| Container | **Docker + Compose** | Un comando per tutto lo stack: `docker compose up` |
| Server ASGI | **Uvicorn** | Produzione-ready, async |

### Perche' SQLAlchemy (Dual Database)

Il principio e' semplice: **stessa codebase, due backend**.

```
# config.yaml
database:
  # Opzione 1: SQLite (default, zero setup)
  url: "sqlite+aiosqlite:///./trading.db"

  # Opzione 2: PostgreSQL (Docker)
  # url: "postgresql+asyncpg://trading:trading@localhost:5432/trading"
```

- **Sviluppo locale**: `python run_webapp.py` → usa SQLite, niente da installare.
- **Docker**: `docker compose up` → FastAPI + PostgreSQL, tutto automatico.
- **Le query sono identiche** grazie a SQLAlchemy. Scrivi una volta, gira ovunque.
- **Migrazioni**: Alembic gestisce lo schema per entrambi i backend.

**Quando serve PostgreSQL:**
- Background monitor + web server scrivono in contemporanea (SQLite ha un solo writer)
- Query analytics complesse (window functions, `GROUP BY ROLLUP`, JSONB per signal metadata)
- Vuoi fare girare il sistema su un VPS/server remoto
- Vuoi dati persistenti che sopravvivono a rebuild del container

### Nuove Dipendenze

```
# Web
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
jinja2>=3.1.0
aiofiles>=23.0.0
python-multipart>=0.0.7

# ORM + Database
sqlalchemy[asyncio]>=2.0.0
alembic>=1.13.0
aiosqlite>=0.19.0              # SQLite async driver
asyncpg>=0.29.0                # PostgreSQL async driver (solo con Docker)

# Background tasks
apscheduler>=3.10.0

# Notifications
python-telegram-bot>=21.0

# Already present (no changes)
# requests, pyyaml, pandas-ta, yfinance, groq, etc.
```

---

## Phase 5 — Foundation: Web App Skeleton

> Obiettivo: FastAPI che serve una dashboard base con lista asset.
> Il sistema si avvia, mostra gli asset configurati, e puo' lanciare un'analisi.

### 5.1 Struttura Progetto

**Cosa implementare:**
- [ ] Directory `app/` con struttura completa (api/, services/, models/, templates/, static/)
- [ ] `app/server.py` — FastAPI app con startup/shutdown lifecycle
- [ ] `app/api/assets.py` — endpoint GET `/api/assets` (legge config.yaml)
- [ ] `app/models/engine.py` — Engine factory (legge `database.url` da config, crea engine async)
- [ ] `app/models/database.py` — SQLAlchemy ORM models (Signal, Trade, MonitorSession, etc.)
- [ ] `alembic/` — directory migrazioni con env.py configurato per async
- [ ] Entry point `run_webapp.py` — avvia uvicorn
- [ ] `config.yaml` — aggiunta sezione `database:` e `telegram:`

**Files coinvolti:**
- `app/server.py` — NUOVO
- `app/api/assets.py` — NUOVO
- `app/models/engine.py` — NUOVO
- `app/models/database.py` — NUOVO
- `alembic.ini` — NUOVO
- `alembic/env.py` — NUOVO
- `run_webapp.py` — NUOVO
- `requirements.txt` — aggiornare con nuove dipendenze

### 5.2 Dashboard HTML

**Cosa implementare:**
- [ ] `app/templates/base.html` — layout base (header, nav, footer)
- [ ] `app/templates/dashboard.html` — pagina principale
- [ ] `app/static/css/style.css` — stile dark theme (trading-friendly)
- [ ] Lista asset con: simbolo, nome, ultimo prezzo (se cached), badge stato
- [ ] Bottone "Analyze" per ogni asset → lancia analisi
- [ ] Sezione "Calendario Economico" sidebar (eventi del giorno)
- [ ] Sezione "Regime Corrente" in alto (LONG/SHORT/NEUTRAL)

**Design:**
- Dark theme (sfondo scuro, testo chiaro — standard per piattaforme trading)
- Responsive ma ottimizzato per desktop (dove si trada)
- No framework CSS pesanti — CSS custom minimale

**Files coinvolti:**
- `app/templates/base.html` — NUOVO
- `app/templates/dashboard.html` — NUOVO
- `app/static/css/style.css` — NUOVO
- `app/static/js/app.js` — NUOVO (HTMX + Alpine.js init)

### 5.3 Config Management via UI

**Cosa implementare:**
- [ ] Endpoint POST `/api/assets` — aggiungere un asset
- [ ] Endpoint DELETE `/api/assets/{symbol}` — rimuovere un asset
- [ ] Modal nella dashboard per aggiungere asset (symbol + display_name)
- [ ] Validazione: verifica che il simbolo esista su yfinance prima di salvare
- [ ] Persistenza: aggiorna config.yaml

**Files coinvolti:**
- `app/api/assets.py` — estendere
- `app/templates/dashboard.html` — modal aggiunta asset
- `config.yaml` — modificato dinamicamente

---

## Phase 6 — Single-Asset Analysis Page

> Obiettivo: pagina dedicata per asset con analisi completa e grafico interattivo.
> Equivalente del report HTML ma live, interattivo, e focalizzato su un solo asset.

### 6.1 Analysis Service Layer

**Cosa implementare:**
- [ ] `app/services/analyzer.py` — wrapper async dei moduli esistenti
- [ ] Funzione `analyze_single_asset(symbol)` che orchestra:
  - `price_data.analyze_assets([asset])` — tecnici + key levels + MTF + QS
  - `news_fetcher.fetch_news(feeds, hours, assets=[asset])` — news filtrate
  - `sentiment.analyze_sentiment(news, [asset], model)` — sentiment per-asset
  - `polymarket.get_polymarket_context([asset])` — segnale predittivo
  - `economic_calendar.fetch_calendar()` — eventi del giorno
  - `hallucination_guard.validate()` — validazione
  - `hallucination_guard.determine_regime()` — regime
- [ ] Esecuzione parallela con `asyncio.to_thread()` per le parti sync
- [ ] Caching risultati in SQLite (TTL: 5 minuti per prezzi, 30 min per news/sentiment)
- [ ] Endpoint POST `/api/analyze/{symbol}` — ritorna JSON completo

**Struttura risposta JSON:**
```json
{
  "symbol": "NQ=F",
  "display_name": "NASDAQ 100 Futures",
  "timestamp": "2026-03-20T08:15:00+01:00",
  "price": {
    "current": 19875.50,
    "change_pct": -0.35,
    "data_source": "yfinance"
  },
  "sentiment": {
    "score": 1.8,
    "label": "Moderatamente rialzista",
    "bias": "BULLISH",
    "confidence": 72,
    "key_drivers": ["...", "...", "..."],
    "risk_events": []
  },
  "technicals": {
    "composite_score": "BULLISH",
    "confidence_pct": 83,
    "signals": { "rsi": {...}, "macd": {...}, ... },
    "key_levels": { "pdh": 19920, "pdl": 19780, ... },
    "mtf": { "weekly": "BULLISH", "daily": "BULLISH", "hourly": "BULLISH", "alignment": "ALIGNED" },
    "quality_score": { "total": 4, "confluence": true, "strong_trend": true, ... }
  },
  "polymarket": {
    "signal": "BULLISH",
    "confidence": 65,
    "top_markets": [...]
  },
  "calendar": {
    "events_today": [...],
    "regime_override": false
  },
  "regime": "LONG",
  "regime_reason": "LLM BULLISH +1.8, tecnici BULLISH 83%",
  "validation_flags": [],
  "setup": {
    "direction": "LONG",
    "entry_price": 19875.50,
    "stop_loss": 19820.25,
    "take_profit": 19985.75,
    "risk_reward": "1:2",
    "quality_score": 4,
    "tradeable": true
  }
}
```

**Files coinvolti:**
- `app/services/analyzer.py` — NUOVO
- `app/api/analysis.py` — NUOVO

### 6.2 Asset Detail Page

**Cosa implementare:**
- [ ] `app/templates/asset_detail.html` — pagina singolo asset
- [ ] **Grafico TradingView Lightweight Charts** con:
  - Candlestick chart (dati daily da price_data)
  - Linee EMA20 (blu) ed EMA50 (arancione)
  - Linee key levels (PDH/PDL orizzontali tratteggiate)
  - Marker entry/SL/TP sul grafico
- [ ] **Card Sentiment**: score, bias, key drivers, confidence bar
- [ ] **Card Tecnici**: tabella 8 indicatori con label colorate
- [ ] **Card Key Levels**: tutti i livelli con distanza % dal prezzo
- [ ] **Card MTF**: trend per timeframe con badge alignment
- [ ] **Card Quality Score**: breakdown 5 fattori con badge TRADEABLE/SKIP
- [ ] **Card Polymarket**: segnale, confidenza, top mercati
- [ ] **Card Calendario**: eventi del giorno con countdown
- [ ] **Box Setup** (in evidenza in alto): direzione, entry, SL, TP, QS, R:R
- [ ] **Box Regime**: LONG/SHORT/NEUTRAL con ragione
- [ ] Bottone "Monitor This Asset" → avvia background monitoring
- [ ] Bottone "Send to Telegram" → invia setup al bot

**Files coinvolti:**
- `app/templates/asset_detail.html` — NUOVO
- `app/static/js/chart.js` — NUOVO (TradingView Lightweight Charts setup)
- `app/static/js/asset.js` — NUOVO (interazioni pagina asset)

### 6.3 Entry/SL/TP Calculator

**Cosa implementare:**
- [ ] `app/services/signal_detector.py` — logica di calcolo setup
- [ ] Calcolo automatico:
  - Entry = prezzo corrente (o prezzo al livello key piu' vicino)
  - SL = entry -/+ ATR × 1.5
  - TP = entry +/- (distanza SL × 2) per R:R 1:2
  - Size = (capitale × risk%) / distanza SL (in euro)
- [ ] Input configurabili nella pagina: capitale, risk%, R:R ratio
- [ ] Visualizzazione sul grafico (linee orizzontali entry/SL/TP)

**Files coinvolti:**
- `app/services/signal_detector.py` — NUOVO
- `app/templates/asset_detail.html` — sezione calculator

---

## Phase 7 — Telegram Notifications

> Obiettivo: ricevi notifica sul telefono quando il sistema rileva un setup.
> "NQ=F LONG — Entry 19875, SL 19820, TP 19985, QS 4/5"

### 7.1 Telegram Bot Setup

**Cosa implementare:**
- [ ] `app/services/notifier.py` — modulo notifiche
- [ ] Classe `TelegramNotifier` con metodi:
  - `send_signal(symbol, direction, entry, sl, tp, qs, regime)` — segnale trade
  - `send_regime_change(old_regime, new_regime, reason)` — cambio regime
  - `send_calendar_alert(event, countdown)` — evento imminente
  - `send_monitor_status(symbol, status)` — monitor avviato/fermato
- [ ] Configurazione in config.yaml:
  ```yaml
  telegram:
    bot_token: "your_token_here"
    chat_id: "your_chat_id"
    enabled: true
  ```
- [ ] Endpoint POST `/api/telegram/test` — invia messaggio di test
- [ ] Pagina settings nella dashboard per configurare bot_token e chat_id

**Formato messaggio Telegram:**
```
🟢 LONG SIGNAL — NQ=F (NASDAQ 100)
━━━━━━━━━━━━━━━━━━━━━━
📍 Entry:  19,875.50
🔴 SL:     19,820.25  (-55.25 pts)
🟢 TP:     19,985.75  (+110.25 pts)
━━━━━━━━━━━━━━━━━━━━━━
⚡ R:R      1:2.0
📊 QS:      4/5 (C+T+L+V)
📈 MTF:     ALIGNED (W↑ D↑ 1H↑)
🎯 Regime:  LONG (+1.8 sentiment)
🕐 Session: NYSE Open (HIGH)
━━━━━━━━━━━━━━━━━━━━━━
Next event: NFP in 4h 20m
```

**Files coinvolti:**
- `app/services/notifier.py` — NUOVO
- `config.yaml` — sezione telegram
- `app/api/settings.py` — NUOVO (gestione configurazione)
- `app/templates/settings.html` — NUOVO

### 7.2 Notification Triggers

**Cosa implementare:**
- [ ] Notifica su "Analyze" manuale (bottone nella detail page)
- [ ] Notifica su cambio regime (da LONG a SHORT, o viceversa)
- [ ] Notifica evento calendario entro 2 ore
- [ ] Notifica automatica quando il monitor rileva un segnale (Phase 8)
- [ ] Toggle on/off per ogni tipo di notifica nella settings page
- [ ] Rate limiting: max 1 notifica per asset ogni 15 minuti

**Files coinvolti:**
- `app/services/notifier.py` — estendere
- `app/models/database.py` — tabella notification_log

---

## Phase 8 — Real-Time Monitor

> Obiettivo: il sistema monitora gli asset in background e ti avvisa
> quando le condizioni di entry si allineano. Non devi stare davanti allo schermo.

### 8.1 Background Price Monitor

**Cosa implementare:**
- [ ] `app/services/monitor.py` — background worker
- [ ] Classe `AssetMonitor` con:
  - `start(symbol, interval_seconds=60)` — avvia polling per un asset
  - `stop(symbol)` — ferma polling
  - `get_status()` — stato di tutti i monitor attivi
- [ ] Ogni ciclo di polling:
  1. Fetch prezzo corrente (yfinance, fast — solo last price)
  2. Fetch indicatori tecnici (EMA, RSI, VWAP) dal 5min data
  3. Confronta con ultimo stato noto
  4. Se le condizioni cambiano → trigger signal detection
- [ ] APScheduler per gestione job periodici
- [ ] Stato monitor persistito in SQLite (sopravvive a restart)

**Condizioni monitorate (ogni 1-5 min):**
```
Prezzo attraversa EMA20?       → Pre-segnale (cyan diamond)
Prezzo rimbalza da EMA20?      → Segnale potenziale
RSI entra in zona estrema?     → Warning
VWAP cross?                    → Cambio forza sessione
Key level raggiunto?           → Alert prossimita'
```

**Files coinvolti:**
- `app/services/monitor.py` — NUOVO
- `app/api/monitor.py` — NUOVO (start/stop/status endpoints)
- `app/models/database.py` — tabella monitor_sessions

### 8.2 Signal Detection Engine

**Cosa implementare:**
- [ ] In `app/services/signal_detector.py` — estendere con logica real-time
- [ ] Funzione `check_entry_conditions(symbol, price_data, sentiment_cache)`:
  - EMA20 > EMA50 (o viceversa per SHORT)
  - Prezzo tocca EMA20 (pullback)
  - Candela di conferma (chiude sopra/sotto EMA20)
  - Prezzo sopra/sotto VWAP
  - RSI non in zona estrema
  - Quality Score >= 4
  - MTF ALIGNED
  - Sessione HIGH quality (London/NYSE open)
  - Nessun evento calendario entro 2h
- [ ] Quando TUTTE le condizioni sono vere → SIGNAL FIRED
- [ ] Push via WebSocket + Telegram

**Files coinvolti:**
- `app/services/signal_detector.py` — estendere
- `app/services/notifier.py` — integrazione

### 8.3 WebSocket Real-Time Push

**Cosa implementare:**
- [ ] `app/api/websocket.py` — WebSocket endpoint `/ws/signals`
- [ ] Broadcast a tutti i client connessi quando:
  - Prezzo si aggiorna (ogni 1-5 min)
  - Segnale rilevato
  - Regime cambia
  - Evento calendario imminente
- [ ] Client JS nella dashboard per ricevere e aggiornare UI in real-time
- [ ] Aggiornamento grafico in tempo reale (nuove candele, livelli)
- [ ] Badge notifica nel browser tab ("🟢 SIGNAL" nel titolo)

**Formato messaggio WebSocket:**
```json
{
  "type": "price_update",
  "symbol": "NQ=F",
  "price": 19880.25,
  "change_pct": -0.32,
  "timestamp": "2026-03-20T15:35:00+01:00"
}

{
  "type": "signal",
  "symbol": "NQ=F",
  "direction": "LONG",
  "entry": 19875.50,
  "sl": 19820.25,
  "tp": 19985.75,
  "quality_score": 4,
  "mtf": "ALIGNED",
  "regime": "LONG"
}
```

**Files coinvolti:**
- `app/api/websocket.py` — NUOVO
- `app/static/js/websocket.js` — NUOVO (client WebSocket)
- `app/templates/asset_detail.html` — integrazione live updates

---

## Phase 9 — Trade Journal & Analytics

> Obiettivo: registra i trade dalla dashboard, visualizza performance,
> identifica pattern di errore.

### 9.1 Trade Journal UI

**Cosa implementare:**
- [ ] `app/templates/trades.html` — pagina trade journal
- [ ] Form per registrare un trade:
  - Asset, direzione, entry price, exit price, SL, TP
  - Quality Score al momento del trade
  - Regime, sentiment score, MTF alignment
  - Note libere
  - Outcome (auto-calcolato da entry/exit)
- [ ] Tabella storica con tutti i trade
- [ ] Filtri: per asset, per direzione, per periodo, per QS
- [ ] Migrazione da `trade_log.csv` a SQLite (import automatico)
- [ ] Endpoint CRUD: GET/POST/PUT `/api/trades`

**Files coinvolti:**
- `app/templates/trades.html` — NUOVO
- `app/api/trades.py` — NUOVO
- `app/models/database.py` — estendere (tabella trades)

### 9.2 Performance Analytics

**Cosa implementare:**
- [ ] `app/templates/analytics.html` — pagina analytics
- [ ] Metriche calcolate:
  - Win rate % (totale e per asset)
  - Profit factor (gross profit / gross loss)
  - Average R-multiple
  - Max drawdown
  - Best/worst trade
  - Win rate per regime (LONG vs SHORT)
  - Win rate per Quality Score (QS 4 vs QS 5)
  - Win rate per sessione (London vs NYSE)
  - Win rate per MTF alignment
- [ ] Grafici:
  - Equity curve (P&L cumulativo)
  - Win rate nel tempo (rolling 20 trades)
  - Distribuzione R-multiples (istogramma)
  - Heatmap performance per ora del giorno
- [ ] Insights automatici:
  - "I trade con QS 5 hanno win rate 72% vs 48% con QS 4"
  - "La sessione NYSE produce il 65% dei profitti"
  - "Il regime SHORT ha profit factor 2.1 vs 1.3 per LONG"

**Files coinvolti:**
- `app/templates/analytics.html` — NUOVO
- `app/api/trades.py` — estendere con endpoint analytics
- `app/static/js/charts.js` — grafici analytics

### 9.3 Signal History

**Cosa implementare:**
- [ ] Tabella storica di tutti i segnali generati (anche non tradati)
- [ ] Per ogni segnale: timestamp, asset, direzione, entry/SL/TP, QS, regime
- [ ] Outcome post-hoc: il prezzo ha raggiunto il TP o il SL?
- [ ] Win rate "teorico" dei segnali (se avessi tradato tutto)
- [ ] Confronto win rate teorico vs reale (discipline gap)

**Files coinvolti:**
- `app/models/database.py` — tabella signal_history
- `app/templates/signals.html` — NUOVO
- `app/api/analysis.py` — estendere (salva segnali generati)

---

## Cosa NON Aggiungere

| Tentazione | Perche' No |
|---|---|
| Esecuzione automatica ordini | CFD su Fineco non ha API pubblica. L'esecuzione manuale con disciplina e' il workflow corretto per ora. |
| Multi-user / autenticazione | Sistema personale, single-user. Aggiungere auth e' complessita' inutile. |
| Deploy cloud (AWS/GCP) | Docker Compose gira ovunque — MacBook locale, VPS a 5€/mese, Raspberry Pi. Non serve AWS. |
| React/Vue/Angular frontend | HTMX + Alpine.js basta per un dashboard personale. No build step, no node_modules. |
| Kubernetes / orchestration | Un singolo `docker compose up` basta. K8s e' per servizi con decine di container. |
| Backtesting engine | TradingView Strategy Tester fa gia' questo. Non duplicare. |
| ML/AI prediction | 4 asset, storia limitata → overfit garantito. Il sistema e' basato su regole, non su predizioni. |

---

## Schema Database (SQLAlchemy ORM)

Il modello e' definito una volta sola in `app/models/database.py` e funziona
sia con SQLite che con PostgreSQL. SQLAlchemy genera lo schema corretto per
ciascun backend automaticamente.

```python
# app/models/database.py — SQLAlchemy 2.0 Async Models

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Signal(Base):
    """Segnali generati dal sistema (ogni volta che le condizioni si allineano)."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)       # LONG / SHORT
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    quality_score = Column(Integer, default=0)
    mtf_alignment = Column(String(20))                   # ALIGNED / PARTIAL / CONFLICTING
    regime = Column(String(10))                          # LONG / SHORT / NEUTRAL
    sentiment_score = Column(Float)
    composite_score = Column(String(10))                 # BULLISH / BEARISH / NEUTRAL
    confidence_pct = Column(Float)
    session = Column(String(20))                         # LONDON / NYSE / DEAD_ZONE
    outcome = Column(String(20), default="PENDING")      # PENDING / TP_HIT / SL_HIT / MANUAL
    outcome_price = Column(Float)
    outcome_pips = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    trades = relationship("Trade", back_populates="signal")

    __table_args__ = (
        Index("ix_signals_symbol_ts", "symbol", "timestamp"),
    )


class Trade(Base):
    """Trade registrati manualmente dal trader."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    quality_score = Column(Integer, default=0)
    regime = Column(String(10))
    sentiment_score = Column(Float)
    outcome_pips = Column(Float, default=0)
    r_multiple = Column(Float, default=0)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    signal = relationship("Signal", back_populates="trades")


class MonitorSession(Base):
    """Sessioni di monitoraggio attive per asset."""
    __tablename__ = "monitor_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, unique=True)
    interval_seconds = Column(Integer, default=60)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_check = Column(DateTime(timezone=True))
    status = Column(String(10), default="ACTIVE")        # ACTIVE / PAUSED / STOPPED
    last_price = Column(Float)
    last_signal = Column(Text)                            # JSON


class NotificationLog(Base):
    """Log notifiche inviate (per rate limiting e debugging)."""
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    type = Column(String(20), nullable=False)             # SIGNAL / REGIME_CHANGE / CALENDAR
    symbol = Column(String(20))
    message = Column(Text)
    channel = Column(String(20), nullable=False)          # TELEGRAM / WEBSOCKET / BOTH


class AnalysisCache(Base):
    """Cache analisi per evitare re-fetch continui."""
    __tablename__ = "analysis_cache"

    symbol = Column(String(20), primary_key=True)
    data_type = Column(String(20), primary_key=True)     # TECHNICALS / SENTIMENT / POLYMARKET
    data_json = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
```

```python
# app/models/engine.py — Database Engine Factory

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


def get_engine(database_url: str):
    """Crea l'engine async dal connection string in config.yaml.

    Esempi:
      SQLite:     "sqlite+aiosqlite:///./trading.db"
      PostgreSQL: "postgresql+asyncpg://trading:trading@localhost:5432/trading"
    """
    return create_async_engine(database_url, echo=False)


def get_session_factory(engine):
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

---

## Phase 10 — Docker & PostgreSQL

> Obiettivo: `docker compose up` e hai tutto lo stack — FastAPI, PostgreSQL,
> volume persistente, environment variables. Zero setup manuale.

### 10.1 Dockerfile

**Cosa implementare:**
- [ ] `Dockerfile` multi-stage (builder + runtime) per immagine leggera
- [ ] Stage 1 (builder): installa dipendenze Python in virtualenv
- [ ] Stage 2 (runtime): copia solo il necessario, espone porta 8000
- [ ] `.dockerignore` — esclude `.venv/`, `reports/`, `*.log`, `.env`, `__pycache__/`
- [ ] Health check endpoint `/api/health` usato da Docker

**Dockerfile:**
```dockerfile
# ── Stage 1: builder ──────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────
FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Non-root user per sicurezza
RUN useradd -m trader && chown -R trader:trader /app
USER trader

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Files coinvolti:**
- `Dockerfile` — NUOVO
- `.dockerignore` — NUOVO
- `app/api/health.py` — NUOVO (endpoint `/api/health`)

### 10.2 Docker Compose

**Cosa implementare:**
- [ ] `docker-compose.yml` con due servizi: `trading-app` + `postgres`
- [ ] Volume `pgdata` per persistenza dati PostgreSQL
- [ ] Volume mount `./config.yaml` per configurazione live
- [ ] Volume mount `./reports/` per report HTML generati
- [ ] Environment variables per secrets (GROQ_API_KEY, TELEGRAM_BOT_TOKEN)
- [ ] Network interna per comunicazione app ↔ postgres
- [ ] Profile `lite` per avviare solo l'app con SQLite (senza PostgreSQL)

**docker-compose.yml:**
```yaml
version: "3.9"

services:
  # ── PostgreSQL ──────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: trading
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-trading_local}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U trading"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Trading App ─────────────────────────────────────
  trading-app:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      # Database — PostgreSQL (override da .env se presente)
      DATABASE_URL: "postgresql+asyncpg://trading:${POSTGRES_PASSWORD:-trading_local}@postgres:5432/trading"
      # API keys (da .env file)
      GROQ_API_KEY: ${GROQ_API_KEY:-}
      TWELVE_DATA_API_KEY: ${TWELVE_DATA_API_KEY:-}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:-}
      TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID:-}
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./reports:/app/reports
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  pgdata:
```

**`.env` file (non committato, in .gitignore):**
```bash
# Database
POSTGRES_PASSWORD=your_secure_password

# API Keys
GROQ_API_KEY=gsk_your_key_here
TWELVE_DATA_API_KEY=your_key_here

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

**Files coinvolti:**
- `docker-compose.yml` — NUOVO
- `.env.example` — NUOVO (template senza secrets)
- `.gitignore` — aggiornare (escludere `.env`, `pgdata/`)

### 10.3 Database Migration con Alembic

**Cosa implementare:**
- [ ] `alembic.ini` configurato per leggere `DATABASE_URL` da environment
- [ ] `alembic/env.py` che supporta async engine (SQLite e PostgreSQL)
- [ ] Migration iniziale con tutte le tabelle (signals, trades, monitor_sessions, etc.)
- [ ] Script `migrate.sh` che rileva il backend e applica le migrazioni
- [ ] Auto-migrate al startup di FastAPI (opzionale, configurabile)

**Comandi:**
```bash
# Locale (SQLite) — sviluppo
alembic upgrade head

# Docker (PostgreSQL) — eseguito automaticamente al startup
docker compose exec trading-app alembic upgrade head

# Creare una nuova migrazione dopo aver modificato i modelli
alembic revision --autogenerate -m "add_new_column"
```

**Files coinvolti:**
- `alembic.ini` — NUOVO
- `alembic/env.py` — NUOVO
- `alembic/versions/001_initial.py` — NUOVO (migration iniziale)

### 10.4 Comandi Operativi

**Uso quotidiano:**
```bash
# ── Avvio completo (PostgreSQL + App) ──────────────
docker compose up -d
# Apri http://localhost:8000

# ── Solo l'app con SQLite (no PostgreSQL) ──────────
DATABASE_URL="sqlite+aiosqlite:///./trading.db" python run_webapp.py

# ── CLI classico (invariato, funziona sempre) ──────
python main.py

# ── Logs ───────────────────────────────────────────
docker compose logs -f trading-app

# ── Stop ───────────────────────────────────────────
docker compose down

# ── Stop e cancella dati (reset completo) ──────────
docker compose down -v

# ── Rebuild dopo modifiche al codice ───────────────
docker compose up -d --build

# ── Backup database ───────────────────────────────
docker compose exec postgres pg_dump -U trading trading > backup.sql

# ── Restore database ──────────────────────────────
cat backup.sql | docker compose exec -T postgres psql -U trading trading
```

**Files coinvolti:**
- `README.md` — aggiornare con istruzioni Docker

---

## Tracking Avanzamento

| Phase | Feature | Status | Dipendenze |
|-------|---------|--------|------------|
| 5.1 | Struttura progetto + FastAPI + SQLAlchemy | `DONE` | Nessuna |
| 5.2 | Dashboard HTML | `DONE` | 5.1 |
| 5.3 | Config management UI | `TODO` | 5.2 |
| 6.1 | Analysis service layer | `DONE` | 5.1 |
| 6.2 | Asset detail page + chart | `DONE` | 6.1 |
| 6.3 | Entry/SL/TP calculator | `DONE` | 6.2 |
| 7.1 | Telegram bot setup | `TODO` | 5.1 |
| 7.2 | Notification triggers | `TODO` | 7.1 + 6.1 |
| 8.1 | Background price monitor | `TODO` | 6.1 |
| 8.2 | Signal detection engine | `TODO` | 8.1 + 6.3 |
| 8.3 | WebSocket real-time push | `TODO` | 8.2 |
| 9.1 | Trade journal UI | `TODO` | 5.2 |
| 9.2 | Performance analytics | `TODO` | 9.1 |
| 9.3 | Signal history | `TODO` | 8.2 + 9.1 |
| 10.1 | Dockerfile | `TODO` | 5.1 |
| 10.2 | Docker Compose + PostgreSQL | `TODO` | 10.1 |
| 10.3 | Alembic migrations | `DONE` | 5.1 |
| 10.4 | Comandi operativi + docs | `TODO` | 10.2 |

### Ordine di Implementazione Consigliato

```
Phase 5.1 → 5.2 → 6.1 → 6.2 → 6.3   (dashboard + analisi funzionante)
  ↓              ↘ 7.1 → 7.2           (notifiche Telegram in parallelo)
  ↓                    ↘ 8.1 → 8.2 → 8.3 (monitor real-time)
  ↓                                  ↘ 9.1 → 9.2 → 9.3 (journal)
  ↓
  └→ 10.1 → 10.2 → 10.3 → 10.4       (Docker — parallelizzabile da Phase 5.1)
```

**Nota**: Phase 10 (Docker) puo' partire subito dopo 5.1 — basta avere il
FastAPI base funzionante per containerizzarlo. Non deve aspettare le fasi
successive. Conviene farlo presto cosi' tutto lo sviluppo successivo
viene testato sia in locale (SQLite) che in Docker (PostgreSQL).

**MVP raggiungibile**: Phase 5 + 6 + 7.1 = dashboard con analisi singolo asset
e notifica Telegram del setup. Gia' operativo per il trading quotidiano.

**MVP Docker**: Phase 5 + 10.1 + 10.2 = `docker compose up` con dashboard base
e PostgreSQL. Da qui si aggiungono le feature incrementalmente.

---

*Ultimo aggiornamento: 20 Marzo 2026*
