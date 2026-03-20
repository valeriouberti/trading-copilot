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
- [ ] Score 1-5 per ogni setup basato su:
  - Confluenza segnali (quanti indicatori concordano)
  - Forza del trend (ADX > 25 = +1)
  - Prossimita' a key level (entry vicino a S/R = +1)
  - Pattern candela (engulfing, pin bar = +1)
  - Volume sopra media = +1
- [ ] Regola: trade solo setup con score >= 4
- [ ] Visualizzazione score nel Pine Script e nel report
- [ ] Storico quality score nel trade log per analisi post

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
- [ ] Matrice di correlazione (30 giorni, rendimenti giornalieri) nel report
- [ ] Regola: mai trade same-direction su asset con correlazione > 0.7
- [ ] Selezione automatica: tra asset correlati, scegli quello con quality score migliore
- [ ] Visualizzazione matrice nel report HTML

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
| 4.1 | Quality Score | `TODO` | |
| 4.2 | Correlation Filter | `TODO` | |

---

*Ultimo aggiornamento: 20 Marzo 2026*
