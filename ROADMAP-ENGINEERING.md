# Trading Copilot — Engineering Roadmap

Architettura e qualita' del codice. Prioritizzato per impatto sulla stabilita' e scalabilita'.

**Stato attuale:** Il sistema funziona ma ha debiti tecnici tipici di un prototipo cresciuto velocemente. Le aree critiche sono error handling, performance e sicurezza.

---

## Phase E1 — Resilienza: Non Crashare in Produzione

> Obiettivo: il sistema deve gestire errori gracefully, senza perdere dati o bloccarsi silenziosamente.

### E1.1 Custom Exception Hierarchy

**Problema:** 59+ bare `except Exception` nel codebase. Gli errori vengono loggati e ignorati. Non c'e' distinzione tra errori recuperabili (API timeout) e fatali (schema corrotto).

**Cosa implementare:**
- [ ] Gerarchia di eccezioni in `modules/exceptions.py`:
  - `TradingCopilotError` (base)
  - `DataFetchError` (yfinance, Twelve Data, RSS — recuperabile)
  - `SentimentAnalysisError` (Groq, FinBERT — fallback disponibile)
  - `ConfigurationError` (settings invalidi — fatale)
  - `ExternalAPIError` (Polymarket, Forex Factory — skip gracefully)
- [ ] Sostituire tutti i bare `except Exception` con eccezioni tipizzate
- [ ] Propagare errori significativi all'utente (toast notification in dashboard)

**Files coinvolti:**
- `modules/exceptions.py` — NUOVO
- `modules/price_data.py` — 21 bare except da tipizzare
- `modules/sentiment.py` — 7 bare except
- `app/services/monitor.py` — errori del polling cycle

### E1.2 Circuit Breaker per API Esterne

**Problema:** Se yfinance va down, il monitor continua a chiamare ogni 60 secondi, accumulando errori. Stessa cosa per Groq API.

**Cosa implementare:**
- [ ] Circuit breaker pattern (3 fallimenti consecutivi → apri circuito → retry dopo 5 minuti)
- [ ] Stato del circuito visibile nella dashboard (icona rosso/verde per ogni data source)
- [ ] Fallback chain: yfinance → Twelve Data → cache locale
- [ ] Health check che verifica connettivita' verso tutte le API esterne

**Files coinvolti:**
- `modules/circuit_breaker.py` — NUOVO
- `modules/price_data.py` — wrap delle chiamate yfinance/Twelve Data
- `app/api/health.py` — health check esteso

### E1.3 Retry con Exponential Backoff

**Problema:** `news_fetcher.py` ha retry ma con backoff fisso. `price_data.py` non ha retry. Le chiamate Groq falliscono senza retry.

**Cosa implementare:**
- [ ] Decorator `@retry` riutilizzabile con exponential backoff + jitter
- [ ] Configurabile per max_retries, base_delay, max_delay
- [ ] Applicare a tutte le chiamate HTTP esterne

**Files coinvolti:**
- `modules/retry.py` — NUOVO (o usare `tenacity`)
- `modules/price_data.py`, `sentiment.py`, `polymarket.py` — applicare decorator
- `requirements.txt` — aggiungere `tenacity>=8.0.0`

---

## Phase E2 — Performance: Risposta Veloce

> Obiettivo: ridurre il tempo di analisi da 15-20s a 5s, e il polling del monitor da overhead elevato a trascurabile.

### E2.1 Response Caching (Redis o In-Memory)

**Problema:** `AnalysisCache` esiste come tabella DB ma non e' mai usata. Ogni analisi richiama yfinance 4 volte (daily, weekly, hourly, 5min) anche se i dati non cambiano.

**Cosa implementare:**
- [ ] Implementare `AnalysisCache` con TTL differenziati:
  - Dati prezzo: 60s TTL (per monitor polling)
  - News: 300s TTL
  - Sentiment: 600s TTL
  - Polymarket: 300s TTL
  - Calendario: 3600s TTL
- [ ] In-memory cache (dict + TTL) per ambienti senza Redis
- [ ] Redis opzionale per ambienti Docker (aggiungere al compose)
- [ ] Cache hit/miss metrics nel health check

**Files coinvolti:**
- `app/services/cache.py` — NUOVO
- `app/services/analyzer.py` — wrap ogni fase del pipeline con cache
- `app/models/database.py` — implementare AnalysisCache o rimuovere tabella

### E2.2 Async HTTP Client

**Problema:** Tutte le chiamate HTTP (yfinance, Groq, RSS) sono sync e bridgiate con `asyncio.to_thread()`. Questo spreca thread e limita il parallelismo.

**Cosa implementare:**
- [ ] Sostituire `requests` con `httpx` (async client) per le chiamate dirette
- [ ] Wrapper async per yfinance (usa requests internamente — thread pool come fallback)
- [ ] Groq SDK supporta gia' async — usare `AsyncGroq`
- [ ] Session reuse: singola `httpx.AsyncClient` per tutta l'app (connection pooling)

**Files coinvolti:**
- `modules/news_fetcher.py` — feedparser resta sync (wrappare)
- `modules/sentiment.py` — migrare a AsyncGroq
- `modules/polymarket.py` — migrare a httpx async
- `requirements.txt` — aggiungere `httpx>=0.27.0`

### E2.3 Batch Multi-Timeframe Fetch

**Problema:** Per ogni asset, 4 chiamate separate a yfinance (daily, weekly, hourly, 5min). Con 6 asset = 24 HTTP requests sequenziali.

**Cosa implementare:**
- [ ] Raggruppare le richieste per asset: una sola chiamata `yf.download()` per asset con tutti i periodi
- [ ] Parallelizzare tra asset: 6 asset in parallelo (non sequenziale)
- [ ] Deduplicare: se il monitor chiede lo stesso asset entro 60s, usa la cache

**Files coinvolti:**
- `modules/price_data.py` — refactor `_fetch_data()` per batch

---

## Phase E3 — Database: Query Efficienti

> Obiettivo: eliminare N+1, aggiungere indici, transazioni robuste.

### E3.1 Query Optimization

**Problema:** `monitor._poll_asset()` chiama `get_all_assets()` (SELECT * FROM assets) ogni 60 secondi per trovare UN asset. N+1 classico.

**Cosa implementare:**
- [ ] `get_asset_by_symbol(session_factory, symbol)` — query diretta con WHERE
- [ ] `get_rss_feed_by_id()` — per future operazioni CRUD
- [ ] Aggiungere indici mancanti:
  - `Trade.signal_id` (FK senza indice)
  - `NotificationLog.timestamp + type` (per rate limiting)
  - `Trade.symbol + timestamp` (per analytics)
- [ ] Audit tutte le query con `echo=True` per identificare N+1

**Files coinvolti:**
- `app/models/database.py` — query helpers + indici
- `app/services/monitor.py` — usare `get_asset_by_symbol()`

### E3.2 Transaction Boundaries

**Problema:** `_save_signal()` nel monitor crea il Signal, poi manda Telegram. Se Telegram fallisce, il Signal e' gia' persistito (inconsistenza).

**Cosa implementare:**
- [ ] Wrappare operazioni correlate in transazioni esplicite
- [ ] Pattern: persist → commit → side effects (Telegram) dopo commit
- [ ] Rollback automatico su fallimento DB

**Files coinvolti:**
- `app/services/monitor.py` — refactor `_poll_asset()` con transazioni esplicite

### E3.3 Pulizia AnalysisCache

**Problema:** La tabella `AnalysisCache` esiste nel modello ma non e' mai usata. Dead code.

**Cosa implementare:**
- [ ] Implementare (vedi E2.1) O rimuovere la tabella
- [ ] Se rimossa: creare migration Alembic

---

## Phase E4 — Sicurezza: Proteggere i Dati

> Obiettivo: autenticazione base, rate limiting, protezione secrets.

### E4.1 Autenticazione Base

**Problema:** Zero auth. Chiunque con accesso alla rete puo' avviare monitor, registrare trade, leggere analytics.

**Cosa implementare:**
- [ ] API key authentication (header `X-API-Key`)
- [ ] Generazione API key al primo avvio (salvata in DB)
- [ ] Middleware FastAPI che verifica l'header su tutti gli endpoint (tranne health)
- [ ] Dashboard: API key passata via cookie/session dopo login
- [ ] Login page semplice (password singola configurabile via env var)

**Files coinvolti:**
- `app/middleware/auth.py` — NUOVO
- `app/server.py` — registrare middleware
- `app/templates/login.html` — NUOVO

### E4.2 Rate Limiting

**Problema:** Nessun rate limiting sugli endpoint API. Un client malevolo potrebbe triggerare migliaia di analisi parallele.

**Cosa implementare:**
- [ ] Rate limiter middleware: 60 req/min per IP per gli endpoint di analisi
- [ ] 10 req/min per monitor start/stop
- [ ] Unlimited per health, static, WebSocket

**Files coinvolti:**
- `app/middleware/rate_limit.py` — NUOVO (o usare `slowapi`)

### E4.3 Secrets at Rest

**Problema:** Telegram bot token salvato in plaintext nella tabella `telegram_config`.

**Cosa implementare:**
- [ ] Encryption at rest per il bot token (Fernet symmetric encryption)
- [ ] Chiave di encryption da env var `ENCRYPTION_KEY`
- [ ] Decrypt solo quando serve (lazy)

**Files coinvolti:**
- `app/models/database.py` — encrypt/decrypt helpers
- `app/services/notifier.py` — decrypt prima dell'uso

---

## Phase E5 — Testing: Fiducia nelle Modifiche

> Obiettivo: poter fare refactoring senza paura di rompere cose.

### E5.1 Async Test Suite

**Problema:** Nessun test per il codice async (monitor, WebSocket, API endpoints con lifespan). I 250 test esistenti sono tutti sync.

**Cosa implementare:**
- [ ] `pytest-asyncio` per test async
- [ ] `httpx.AsyncClient` con `ASGITransport` per test API end-to-end
- [ ] Test per: monitor start/stop, WebSocket broadcast, telegram settings CRUD
- [ ] Fixture con DB in-memory (SQLite) per isolamento test

**Files coinvolti:**
- `tests/conftest.py` — aggiungere async fixtures
- `tests/test_api_*.py` — NUOVI (un file per router)
- `requirements.txt` — aggiungere `pytest-asyncio>=0.23.0`, `httpx>=0.27.0`

### E5.2 Mock Tutte le API Esterne

**Problema:** Alcuni test possono fare chiamate reali se `GROQ_API_KEY` e' impostata. Non deterministico.

**Cosa implementare:**
- [ ] `pytest-recording` o fixture globale che blocca TUTTE le chiamate HTTP nei test
- [ ] Fixture `mock_yfinance`, `mock_groq`, `mock_rss` riutilizzabili
- [ ] VCR cassettes per response deterministiche

### E5.3 Database Tests

**Problema:** Nessun test per le operazioni DB (seed, CRUD asset, trade analytics).

**Cosa implementare:**
- [ ] Test per: `seed_assets_from_config`, `seed_rss_feeds`, `upsert_telegram_config`
- [ ] Test per trade analytics queries (win rate, profit factor)
- [ ] Test per signal persistence dal monitor

---

## Phase E6 — Deploy: Produzione Stabile

> Obiettivo: il container Docker funziona in modo affidabile 24/7.

### E6.1 Fix Reload in Produzione

**Problema:** `run_webapp.py` ha `reload=True` che causa restart del server ad ogni modifica file. In Docker, questo puo' causare disconnessioni WebSocket.

**Cosa implementare:**
- [ ] `reload=False` di default, `reload=True` solo se env var `DEV=true`
- [ ] Oppure: CLI flag `--dev` per abilitare reload

**Files coinvolti:**
- `run_webapp.py` — fix immediato

### E6.2 Health Check Esteso

**Problema:** `/api/health` ritorna `{"status": "ok"}` senza verificare nulla. Non rileva DB down o monitor bloccato.

**Cosa implementare:**
- [ ] Verificare connettivita' DB (SELECT 1)
- [ ] Verificare stato monitor (last_check < 5 minuti fa)
- [ ] Verificare disponibilita' Groq API (se configurata)
- [ ] Ritornare `503` se qualsiasi check critico fallisce

**Files coinvolti:**
- `app/api/health.py` — estendere

### E6.3 Structured Logging + Rotation

**Problema:** Log non strutturati, nessuna rotazione. Il file `trading_assistant.log` cresce senza limiti.

**Cosa implementare:**
- [ ] JSON structured logging (per aggregazione in ELK/Grafana)
- [ ] Log rotation (RotatingFileHandler, max 10MB x 5 file)
- [ ] Request logging middleware (metodo, path, status, durata)
- [ ] Correlation ID per tracciare una richiesta end-to-end

**Files coinvolti:**
- `app/middleware/logging.py` — NUOVO
- `main.py` — aggiornare setup_logging()

### E6.4 Graceful Shutdown

**Problema:** `monitor.shutdown()` usa `wait=False` — i job in corso vengono interrotti brutalmente. Possibile perdita di dati.

**Cosa implementare:**
- [ ] `wait=True` con timeout (30s)
- [ ] Signal handler per SIGTERM/SIGINT
- [ ] Completare il polling cycle corrente prima di uscire

**Files coinvolti:**
- `app/services/monitor.py` — fix shutdown
- `app/server.py` — signal handler

---

## Phase E7 — Dependency Management

> Obiettivo: build riproducibili, immagine Docker leggera.

### E7.1 Pin Dependencies

**Problema:** `requirements.txt` usa `>=` — build non riproducibili.

**Cosa implementare:**
- [ ] Generare `requirements.lock` con versioni esatte (`pip freeze`)
- [ ] `requirements.txt` mantiene range per sviluppo
- [ ] Dockerfile usa `requirements.lock`

### E7.2 Separare ML Dependencies

**Problema:** `torch` (2.5GB) e `transformers` (800MB) sono installati sempre, ma usati solo come fallback se Groq non e' configurato.

**Cosa implementare:**
- [ ] `requirements-base.txt` — dipendenze core (FastAPI, SQLAlchemy, yfinance)
- [ ] `requirements-ml.txt` — torch, transformers (opzionale)
- [ ] Dockerfile multi-stage: immagine `lite` senza ML, immagine `full` con ML
- [ ] Runtime check: se FinBERT richiesto ma non installato → messaggio chiaro

**Files coinvolti:**
- `requirements.txt` → split in 2+
- `Dockerfile` — build arg per scegliere variante

---

## Tracking Avanzamento

| Phase | Feature | Status | Priorita' |
|-------|---------|--------|-----------|
| E1.1 | Custom Exceptions | `TODO` | CRITICA |
| E1.2 | Circuit Breaker | `TODO` | ALTA |
| E1.3 | Retry Decorator | `TODO` | ALTA |
| E2.1 | Response Caching | `TODO` | CRITICA |
| E2.2 | Async HTTP Client | `TODO` | ALTA |
| E2.3 | Batch TF Fetch | `TODO` | MEDIA |
| E3.1 | Query Optimization | `TODO` | ALTA |
| E3.2 | Transaction Boundaries | `TODO` | MEDIA |
| E3.3 | AnalysisCache Cleanup | `TODO` | BASSA |
| E4.1 | Autenticazione | `TODO` | CRITICA |
| E4.2 | Rate Limiting | `TODO` | ALTA |
| E4.3 | Secrets Encryption | `TODO` | MEDIA |
| E5.1 | Async Test Suite | `TODO` | ALTA |
| E5.2 | Mock API Esterne | `TODO` | MEDIA |
| E5.3 | Database Tests | `TODO` | MEDIA |
| E6.1 | Fix Reload | `TODO` | CRITICA |
| E6.2 | Health Check Esteso | `TODO` | ALTA |
| E6.3 | Structured Logging | `TODO` | MEDIA |
| E6.4 | Graceful Shutdown | `TODO` | MEDIA |
| E7.1 | Pin Dependencies | `TODO` | ALTA |
| E7.2 | Separare ML Deps | `TODO` | MEDIA |

---

*Creato: 20 Marzo 2026 — analisi architetturale v5.2.0*
