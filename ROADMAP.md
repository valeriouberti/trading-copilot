# Trading Copilot — Roadmap v4.1+

Piano di miglioramento prioritizzato per impatto sulla profittabilita'.

---

## Phase 1 — Difesa: Evitare le Perdite Prevenibili

> Obiettivo: eliminare i trade che perdono per mancanza di informazioni, non per analisi sbagliata.

### 1.1 Key Levels (Support/Resistance)

**Problema:** Il sistema ha indicatori ma nessun concetto di livelli chiave. Un segnale LONG perfetto che punta dritto in una resistenza maggiore e' un trade perdente.

**Cosa implementare:**
- [ ] Previous Day High / Low / Close (PDH / PDL / PDC)
- [ ] Previous Week High / Low (PWH / PWL)
- [ ] Pivot Points classici (PP, R1, R2, S1, S2) calcolati da sessione precedente
- [ ] Livelli psicologici rotondi (es. NQ 20000, Gold 3000, EURUSD 1.1000)
- [ ] Distanza % dal livello piu' vicino nel report HTML
- [ ] Linee dei livelli nel Pine Script

**Fonte dati:** yfinance (gia' disponibile, servono solo i dati daily/weekly precedenti).

**Impatto atteso:** Evitare entry contro livelli forti. Filtrare il 20-30% dei trade che attualmente entrano in zone di congestione.

**Files coinvolti:**
- `modules/price_data.py` — calcolo livelli
- `modules/report.py` — colonna/sezione livelli nel report
- `tradingview/trading_copilot.pine` — disegno livelli sul grafico
- `tests/test_price_data.py` — test nuovi calcoli

---

### 1.2 Calendario Economico

**Problema:** L'LLM rileva gli eventi *dopo* che appaiono nelle news, ma a quel punto il movimento e' gia' avvenuto. Serve sapere *prima* della sessione che NFP e' alle 14:30 o FOMC alle 20:00.

**Cosa implementare:**
- [ ] Nuovo modulo `modules/economic_calendar.py`
- [ ] Fetch da API gratuita Forex Factory (`https://nfs.faireconomy.media/ff_calendar_thisweek.json`)
- [ ] Filtro per eventi HIGH impact (NFP, CPI, FOMC, GDP, Retail Sales, PMI)
- [ ] Countdown nel report: "FOMC tra 3h 20m — regime forzato NEUTRAL"
- [ ] Auto-override regime a NEUTRAL se evento high-impact entro 2 ore
- [ ] Sezione dedicata nel report HTML con tabella eventi del giorno
- [ ] Alert nel Pine Script per eventi imminenti

**Fonte dati:** Forex Factory JSON (gratuito, nessuna API key).

**Impatto atteso:** Eliminare le perdite da volatility spike su dati schedulati. Questi sono tipicamente i trade con SL piu' ampi e le perdite piu' pesanti.

**Files coinvolti:**
- `modules/economic_calendar.py` — NUOVO
- `modules/report.py` — sezione calendario
- `modules/hallucination_guard.py` — override regime pre-evento
- `main.py` — integrazione nel pipeline
- `tests/test_economic_calendar.py` — NUOVO

---

## Phase 2 — Attacco: Massimizzare i Vincenti

> Obiettivo: estrarre piu' profitto dai trade che vanno nella direzione giusta.

### 2.1 Trailing Stop nel Pine Script

**Problema:** Il R:R fisso 1:2 esce a 2R anche quando il trade potrebbe correre a 5R o 10R. In mercati trending, uscire troppo presto costa piu' delle perdite.

**Cosa implementare:**
- [x] Dopo +1R: SL si sposta a breakeven (zero risk)
- [x] Dopo +2R: SL trail a +1R dietro il prezzo
- [x] Opzione partial TP: 50% a 2R, trail rimanente con ATR-based stop
- [x] Toggle nel Pine Script per scegliere tra TP fisso e trailing
- [x] Visualizzazione dinamica della trailing stop line sul grafico

**Impatto atteso:** Con win-rate 50% e trailing, il profit factor passa da ~1.5x a ~2.5x. I pochi trade che corrono 5-10R compensano molte piccole perdite.

**Files coinvolti:**
- `tradingview/trading_copilot.pine` — logica trailing stop

---

## Phase 3 — Precisione: Entrare al Momento Giusto

> Obiettivo: migliorare il timing delle entry filtrando per timeframe e sessione.

### 3.1 Multi-Timeframe Confirmation

**Problema:** Il sistema analizza daily + 5m. Il daily da' il trend, il 5m e' rumore. Manca il timeframe intermedio (1h) e quello macro (weekly).

**Cosa implementare:**
- [x] Fetch dati weekly da yfinance/Twelve Data
- [x] Fetch dati 1h da yfinance/Twelve Data
- [x] Calcolo trend per 3 timeframe: Weekly → Daily → 1h
- [x] Nuovo campo "MTF Alignment" nel report (ALIGNED / PARTIAL / CONFLICTING)
- [x] Regola: trade solo quando Weekly + Daily + 1h concordano
- [x] Penalita' nel composite score se MTF non allineato

**Impatto atteso:** Evitare entry contro-trend su timeframe superiore. Miglioramento win-rate stimato +10-15%.

**Files coinvolti:**
- `modules/price_data.py` — fetch e analisi multi-TF
- `modules/report.py` — sezione MTF alignment
- `tests/test_price_data.py` — test MTF

---

### 3.2 Session Time Filter

**Problema:** Non tutte le ore sono uguali. Le migliori opportunita' sono a London open (08:00-09:00 CET), NYSE open (15:30-16:30 CET), e post-FOMC. I segnali nel "dead zone" (11:00-14:00 CET) hanno aspettativa negativa.

**Cosa implementare:**
- [x] Filtro orario nel Pine Script: segnali solo in finestre ad alto volume
- [x] Configurazione finestre per sessione (London, NYSE, overlap)
- [x] Il report indica quale sessione e' la prossima e countdown
- [ ] Heatmap volume per ora del giorno (basata su dati storici) — deferred to Phase 4+

**Impatto atteso:** Ridurre i trade in orari di bassa liquidita'/chop. Meno trade, ma di qualita' superiore.

**Files coinvolti:**
- `tradingview/trading_copilot.pine` — filtro orario
- `modules/report.py` — info sessione

---

## Phase 4 — Selezione: Tradare Solo i Setup Migliori

> Obiettivo: aumentare la qualita' media dei trade presi.

### 4.1 Setup Quality Score

**Problema:** Tutti i segnali sono trattati come uguali. Un LONG su supporto con ADX 35 e engulfing bullish vale molto piu' di un LONG random su EMA touch con ADX 12 nel chop.

**Cosa implementare:**
- [x] Score 1-5 per ogni setup basato su:
  - Confluenza segnali (quanti indicatori concordano)
  - Forza del trend (ADX > 25 = +1)
  - Prossimita' a key level (entry vicino a S/R = +1)
  - Pattern candela (engulfing, pin bar = +1)
  - Volume sopra media = +1
- [x] Regola: trade solo setup con score >= 4
- [x] Visualizzazione score nel Pine Script e nel report
- [x] Storico quality score nel trade log per analisi post

**Impatto atteso:** Ridurre i trade di bassa qualita' del 30-40%. Aumento netto del profit factor.

**Files coinvolti:**
- `modules/price_data.py` — calcolo quality score
- `modules/report.py` — visualizzazione score
- `tradingview/trading_copilot.pine` — filtro score
- `modules/trade_log.py` — registro score

---

### 4.2 Correlation Filter

**Problema:** NQ e ES hanno correlazione ~0.95. Andare LONG su entrambi raddoppia il rischio su un singolo trade. Se il segnale e' sbagliato, si perde 2% invece di 1%.

**Cosa implementare:**
- [x] Matrice di correlazione (30 giorni, rendimenti giornalieri) nel report
- [x] Regola: mai trade same-direction su asset con correlazione > 0.7
- [x] Selezione automatica: tra asset correlati, scegli quello con quality score migliore
- [x] Visualizzazione matrice nel report HTML

**Impatto atteso:** Evitare concentrazione di rischio. Diversificazione reale del portafoglio trade.

**Files coinvolti:**
- `modules/price_data.py` — calcolo correlazione
- `modules/report.py` — matrice correlazione
- `tests/test_price_data.py` — test correlazione

---

## Cosa NON Aggiungere

| Tentazione | Perche' No |
|---|---|
| Piu' indicatori (Ichimoku, Fibonacci, ecc.) | 8 indicatori sono gia' sufficienti. Aggiungerne causa paralisi, non profitti. |
| Esecuzione automatica | Su Fineco CFD, l'esecuzione manuale con disciplina batte l'automazione prematura. |
| Machine Learning / predizioni | Con 4 asset e storia limitata, qualsiasi modello ML andrebbe in overfit. |
| Ulteriori fonti news | 4 feed RSS sono sufficienti. Piu' fonti = piu' rumore, non piu' segnale. |

---

## Tracking Avanzamento

| Phase | Feature | Status | Note |
|-------|---------|--------|------|
| 1.1 | Key Levels | `DONE` | PDH/PDL/PDC, PWH/PWL, Pivots, Psych levels, nearest level proximity |
| 1.2 | Calendario Economico | `DONE` | Forex Factory API, regime override entro 2h, sezione report HTML |
| 2.1 | Trailing Stop | `DONE` | 3 exit modes (Fixed TP, Trailing Stop, Partial+Trail), BE at +1R, trail at +2R, dynamic SL line, R-multiple markers, exit alerts |
| 3.1 | Multi-Timeframe | `DONE` | Weekly/Daily/1H EMA trend, MTF alignment (ALIGNED/PARTIAL/CONFLICTING), composite score penalty, report cards |
| 3.2 | Session Filter | `DONE` | Pine Script session filter (London/NYSE), dead zone blocking, session info in report, configurable windows |
| 4.1 | Quality Score | `DONE` | Score 1-5 (confluence, ADX>25, key level, candle pattern, volume), QS column in report, Pine Script filter, trade_log recording |
| 4.2 | Correlation Filter | `DONE` | 30-day return correlation matrix, >0.7 threshold filters same-direction trades, auto-select best QS, heatmap in HTML report |

---

## Web App — COMPLETATA (Phase 5-10)

Tutte le fasi webapp sono state implementate (17 sub-fasi).

- **Dashboard interattiva** — lista asset, analisi on-demand, monitor real-time
- **Signal Detection Engine** — 9 condizioni di entry, calcolo automatico SL/TP
- **Notifiche Telegram** — segnali push sul telefono
- **Trade Journal** — registrazione trade con P&L e R-multiple automatici
- **Performance Analytics** — win rate, profit factor, equity curve, insights
- **Docker + PostgreSQL** — deploy con un comando

---

## Phase 11 — Data Quality (v5.1.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| 11.1 | Asset in Database | `DONE` | Tabella `Asset` in DB, seed da config.yaml, CRUD via API, no piu' scrittura su YAML |
| 11.2 | News per Asset | `DONE` | RSS Yahoo Finance per simbolo, filtro rilevanza, ~5 articoli mirati vs 60+ generici |
| 11.3 | TradingView Chart | `DONE` | Candlestick + EMA20/50 + key levels, caricamento auto, endpoint `/api/chart/{symbol}` |
| 11.4 | Pulizia docs | `DONE` | Rimosso ROADMAP-WEBAPP.md e docs/Main.md, aggiornati README/CHANGELOG/ROADMAP |

---

## Phase 12 — Production Config (v5.2.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| 12.1 | Pydantic Settings | `DONE` | `pydantic-settings` con validazione tipizzata, env vars > YAML > defaults |
| 12.2 | Secrets in Env Vars | `DONE` | Rimossi secrets da YAML, tutti via `.env` o env vars |
| 12.3 | Telegram in Database | `DONE` | Tabella `TelegramConfig`, Settings page salva in DB, rimosso `save_config()` |
| 12.4 | RSS Feeds in Database | `DONE` | Tabella `RssFeed`, seed da YAML o defaults, `config.yaml` opzionale |
| 12.5 | Documentazione | `DONE` | README, CHANGELOG, ROADMAP aggiornati |

Vedi **[CHANGELOG.md](CHANGELOG.md)** per lo storico completo delle modifiche.

---

## Phase 13 — Unified Development Plan (v5.3.0–v6.0.0)

Implementazione completa del piano unificato che fonde ROADMAP-ENGINEERING (21 task) e ROADMAP-TRADING (17 task) in 6 sprint. **29 task completati, 9 deferred.** 383 test totali passano.

### Sprint 1 — Foundation (v5.3.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| E6.1 | Fix Reload | `DONE` | `reload=True` condizionato a `TRADING_COPILOT_DEV` |
| E7.1 | Pin Dependencies | `DONE` | `requirements.lock` con versioni esatte |
| E1.3 | Retry Decorator | `DONE` | `tenacity` library, 4 decoratori pre-configurati |
| E1.1 | Custom Exceptions | `DONE` | Gerarchia tipizzata: Transient/Permanent, 8 sottoclassi |
| E6.4 | Graceful Shutdown | `DONE` | `wait=True` 30s, SIGTERM/SIGINT handler |
| T2.3 | Drawdown Breaker | `DONE` | Daily/weekly P&L limits, pausa segnali |

### Sprint 2 — Resilience & Caching (v5.4.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| E1.2 | Circuit Breaker | `DONE` | closed/open/half-open, 4 breaker pre-configurati |
| E2.1 | Response Caching | `DONE` | In-memory TTL cache, 5 stage con TTL differenziati |
| E6.2 | Health Check Esteso | `DONE` | DB, monitor, cache, circuit breakers, drawdown |
| E6.3 | Structured Logging | `DONE` | JSON formatter, rotation 10MB x 5, correlation ID |
| T3.1 | LLM Trade Thesis | `DONE` | Ragionamento strutturato per ogni segnale |

### Sprint 3 — Backtester Core (v5.5.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| T4.1 | Backtester | `DONE` | Engine vectorized con CLI, 36 test |
| E4.2 | Rate Limiting | `DONE` | slowapi, 60/min analisi, 10/min monitor |
| E3.2 | Transaction Boundaries | `DONE` | Persist → commit → side effects |
| T3.2 | News Summarizer | `DONE` | LLM bullet points, fallback titoli |

### Sprint 4 — Signal Quality & Async (v5.6.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| T1.1 | Adaptive Weights | `DONE` | ADX-based trending/ranging/volatile weighting |
| T2.1 | Adaptive SL/TP | `DONE` | ATR percentile, SL 1.0–2.0x dinamico |
| E2.2 | Async HTTP Client | `DONE` | httpx + AsyncGroq |
| E3.1 | Query Optimization | `DONE` | `get_asset_by_symbol()`, DB indexes |

### Sprint 5 — Security & Testing (v5.7.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| E4.1 | Autenticazione | `DONE` | API key middleware, login page |
| T4.2 | Walk-Forward | `DONE` | Rolling window backtest |
| E7.2 | Separare ML Deps | `DONE` | requirements-base.txt, Dockerfile lite target |

### Sprint 6 — Advanced Trading (v6.0.0)

| # | Feature | Status | Note |
|---|---------|--------|------|
| T5.3 | Intermarket Analysis | `DONE` | DXY/Gold, Yields/Equities divergence |
| T1.3 | Candle Patterns | `DONE` | Engulfing, pin bar, inside bar |
| T2.2 | Kelly Sizing | `DONE` | Half-Kelly capped 0.25%–2% |
| T4.3 | Monte Carlo | `DONE` | 1000 equity curve permutazioni |
| T6.1 | Portfolio Heat Map | `DONE` | Endpoint correlazione + heatmap |

### Deferred (Post v6.0.0)

| # | Feature | Motivo |
|---|---------|--------|
| E2.3 | Batch TF Fetch | Coperto parzialmente da caching E2.1 |
| E3.3 | AnalysisCache Cleanup | Risolto con implementazione E2.1 |
| E4.3 | Secrets Encryption | Nice-to-have dopo auth |
| E5.2 | Mock API Esterne | Incrementale |
| E5.3 | Database Tests | Incrementale |
| T1.2 | Volume Profile | Richiede tick data non disponibile da yfinance |
| T3.3 | Post-Trade Review | Richiede piu' dati trade storici |
| T5.1 | Volume Delta/CVD | Richiede tick data |
| T5.2 | Volume Heatmap | Richiede tick data |
| T6.2 | Sector Rotation | Rilevante con 10+ asset |

---

## Roadmap Specializzate

Per i dettagli implementativi, il progetto ha due roadmap dedicate:

- **[ROADMAP-ENGINEERING.md](ROADMAP-ENGINEERING.md)** — Architettura, performance, sicurezza, testing, deploy. 7 fasi, 21 task (17 completati).
- **[ROADMAP-TRADING.md](ROADMAP-TRADING.md)** — Signal quality, risk management, LLM avanzato, backtesting, market microstructure. 6 fasi, 17 task (12 completati).

---

*Ultimo aggiornamento: 20 Marzo 2026 — v6.0.0*
