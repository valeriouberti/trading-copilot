# Trading Copilot — Trading System Roadmap

Miglioramenti alla logica di trading, signal quality e risk management. Prioritizzato per impatto sulla profittabilita' reale.

**Stato attuale del sistema:**
- 6 indicatori direzionali con composite score (soglia 4/6)
- LLM sentiment two-pass con FinBERT cross-validation
- Quality Score 1-5 con soglia entry >= 4
- SL/TP fisso ATR x 1.5 / R:R 1:2
- MTF alignment (Weekly/Daily/1H)
- Polymarket prediction market signal
- Correlazione 30 giorni con filtro 0.7

**Punti di forza:** Multi-layer confluence (tecnici + sentiment + prediction markets + calendario). Buona difesa (key levels, MTF, session filter, calendar override).

**Aree di miglioramento:** Signal quality, risk management adattivo, backtesting, e uso piu' sofisticato dell'LLM.

---

## Phase T1 — Signal Quality: Ridurre i Falsi Segnali

> Obiettivo: aumentare il win rate dal ~50% stimato al 55-60% eliminando segnali di bassa qualita'.

### T1.1 Adaptive Indicator Weights

**Problema:** Il composite score tratta tutti i 6 indicatori con peso uguale. Ma in mercati trending, EMA e ADX sono affidabili; in range, RSI e Bollinger sono migliori. Il peso fisso genera segnali contradittori.

**Cosa implementare:**
- [x] Classificazione regime di mercato: TRENDING vs RANGING vs VOLATILE
  - ADX > 25 + EMA spread > 0.5% → TRENDING
  - ADX < 20 + BB bandwidth < 4% → RANGING
  - ATR_pct > 2% + ADX < 25 → VOLATILE
- [x] Pesi dinamici per regime:
  - TRENDING: EMA_TREND x2, ADX x2, RSI x0.5 (mean reversion inutile in trend)
  - RANGING: RSI x2, BB x2, Stoch x2, EMA x0.5 (trend following inutile in range)
  - VOLATILE: VWAP x2, ATR x2 (livelli chiave e volatilita' contano di piu')
- [x] Composite score pesato: `sum(signal * weight) / sum(weights)`
- [x] Log del regime di mercato nel report e nel trade journal

**Impatto atteso:** +5-8% win rate. Evitare segnali trend-following in mercati range e viceversa.

**Files coinvolti:**
- `modules/price_data.py` — market regime classifier + weighted composite
- `app/services/signal_detector.py` — usare regime nel filtering

### T1.2 Volume Profile Analysis

**Problema:** Il Quality Score usa solo "volume sopra media 20 giorni" come fattore. Non considera DOVE il volume si concentra (a quali livelli di prezzo).

**Cosa implementare:**
- [ ] Volume Profile semplificato: distribuzione volume per livello di prezzo (ultimi 20 giorni)
- [ ] Point of Control (POC): livello di prezzo con piu' volume
- [ ] Value Area (70% del volume): range di prezzo "fair value"
- [ ] Segnale: entry fuori dalla Value Area in direzione del POC → mean reversion
- [ ] Segnale: breakout della Value Area con volume → continuation
- [ ] Aggiungere POC e VA al report e ai key levels

**Impatto atteso:** Migliore timing delle entry. Entry vicino al POC hanno stop piu' stretti.

**Files coinvolti:**
- `modules/price_data.py` — volume profile calculation
- `modules/report.py` — sezione volume profile
- `app/services/signal_detector.py` — POC proximity come condizione aggiuntiva

### T1.3 Candle Pattern Recognition Avanzato

**Problema:** Il QS riconosce solo engulfing e pin bar. Mancano pattern ad alta affidabilita': morning star, three white soldiers, hammer, doji a livelli chiave.

**Cosa implementare:**
- [x] Libreria pattern: engulfing, pin bar, inside bar detection
- [x] Contesto: pattern valido SOLO se appare a key level (supporto per bullish, resistenza per bearish)
- [x] Scoring: pattern a key level = +2 QS (invece di +1)
- [x] Pattern nel report con nome e direzione implicita

**Impatto atteso:** Migliore entry timing. I pattern a key level hanno win rate storicamente 60-70%.

**Files coinvolti:**
- `modules/price_data.py` — pattern recognition esteso
- `modules/report.py` — colonna pattern

---

## Phase T2 — Risk Management Adattivo

> Obiettivo: massimizzare i profitti sui trade vincenti e minimizzare le perdite sui perdenti. Passare da R:R fisso 1:2 a dinamico.

### T2.1 ATR-Adaptive SL/TP

**Problema:** SL = ATR x 1.5 e TP = ATR x 3.0 sono fissi. Ma in condizioni di alta volatilita' (NFP, FOMC), ATR spike e gli stop sono troppo larghi. In bassa volatilita', gli stop sono troppo stretti e si viene stoppati dal rumore.

**Cosa implementare:**
- [x] ATR percentile: calcolare dove si posiziona l'ATR corrente vs gli ultimi 50 giorni
  - ATR > 80th percentile → "HIGH VOL" → SL = ATR x 1.0 (piu' stretto, posizioni piu' piccole)
  - ATR < 20th percentile → "LOW VOL" → SL = ATR x 2.0 (piu' largo per evitare noise)
  - ATR 20th-80th → "NORMAL" → SL = ATR x 1.5 (corrente)
- [x] TP dinamico basato su struttura di mercato:
  - Se prossima resistenza/supporto e' a < 2R → TP al livello (non forzare 2R)
  - Se prossimo livello e' a > 3R → TP a 3R con trailing
- [x] Mostrare ATR percentile e TP adattivo nel setup box

**Impatto atteso:** Ridurre i falsi stop in bassa vol (-10% SL hit). Proteggere in alta vol (posizioni piu' piccole).

**Files coinvolti:**
- `modules/price_data.py` — ATR percentile calculation
- `app/services/analyzer.py` — TP adattivo con key levels
- `app/services/signal_detector.py` — SL/TP dinamici
- `tradingview/trading_copilot.pine` — ATR percentile input

### T2.2 Dynamic Position Sizing (Kelly Criterion)

**Problema:** Il Pine Script usa 1% rischio fisso per trade. Non tiene conto del win rate storico o dell'edge del sistema. Se il sistema ha edge positivo, rischia troppo poco; se l'edge e' marginale, rischia troppo.

**Cosa implementare:**
- [x] Calcolo Kelly Fraction dal trade journal:
  - `f* = (p * b - q) / b`
  - dove p = win rate, q = 1 - p, b = avg win / avg loss
- [x] Half-Kelly per conservativismo: `risk_pct = f* / 2`
- [x] Floor: mai meno di 0.25% rischio per trade
- [x] Ceiling: mai piu' di 2% rischio per trade
- [x] Mostrare Kelly suggerito nella pagina Analytics
- [x] Suggerire position size nel setup box

**Impatto atteso:** Con edge positivo (win rate 55%, avg win 2R), Half-Kelly suggerisce ~0.8% vs 1% fisso. Protegge dal ruin risk.

**Files coinvolti:**
- `app/api/trades.py` — calcolo Kelly nelle analytics
- `app/services/signal_detector.py` — suggerimento position size
- `app/templates/analytics.html` — visualizzazione Kelly

### T2.3 Drawdown Circuit Breaker

**Problema:** Nessun meccanismo per fermare il trading in drawdown. Un trader che perde 5 trade consecutivi dovrebbe ridurre il rischio, non continuare con la stessa size.

**Cosa implementare:**
- [x] Monitorare drawdown corrente dal trade journal (daily/weekly P&L)
- [x] Regole:
  - Daily loss > 100 pips → pausa segnali
  - Weekly loss > 250 pips → pausa segnali
- [x] Drawdown status visibile nel health check
- [x] Monitor checks drawdown breaker prima di generare segnali

**Impatto atteso:** Prevenire il "revenge trading". Limitare il drawdown massimo al 5-7%.

**Files coinvolti:**
- `app/services/signal_detector.py` — check drawdown pre-signal
- `app/api/trades.py` — calcolo drawdown corrente
- `app/services/notifier.py` — alert drawdown

---

## Phase T3 — LLM Avanzato: Analisi Piu' Intelligente

> Obiettivo: usare l'LLM non solo per il sentiment, ma per ragionamento strutturato su mercato e setup.

### T3.1 LLM Trade Thesis

**Problema:** L'LLM produce solo un sentiment score (-3/+3). Non spiega il "perche'" in modo strutturato. Il trader deve interpretare il ragionamento da solo.

**Cosa implementare:**
- [x] Nuovo prompt che genera una "trade thesis" strutturata:
  ```
  {
    "direction": "LONG",
    "conviction": 7,  // 1-10
    "thesis": "Fed dovish pivot + CPI sotto attese = risk-on.",
    "risks": ["Earnings season prossima settimana"],
    "catalysts": ["FOMC minuti domani ore 20:00"],
    "invalidation": "Chiusura sotto 20500 invalida il setup long",
    "time_horizon": "2-5 giorni"
  }
  ```
- [x] Thesis visibile nella pagina asset detail (campo `trade_thesis` nel response)
- [x] Thesis inclusa nella notifica Telegram

**Impatto atteso:** Migliore decision making. Il trader capisce il "perche'" e puo' valutare se concorda.

**Files coinvolti:**
- `modules/sentiment.py` — nuovo prompt per trade thesis
- `app/services/analyzer.py` — integrare thesis nel pipeline
- `app/templates/asset_detail.html` — card thesis

### T3.2 LLM News Summarizer per Asset

**Problema:** Il trader riceve 5 articoli filtrati per asset ma deve leggerli tutti. L'LLM potrebbe sintetizzare le notizie in 3 bullet points rilevanti.

**Cosa implementare:**
- [x] Dopo il fetch delle news per asset, passare i titoli+summary all'LLM
- [x] Prompt: "Summarize into N concise bullet points focusing on market impact"
- [x] Output nella pagina asset detail (campo `news_summary`)
- [x] Cache del riassunto via TTL cache in analyzer pipeline

**Impatto atteso:** Tempo di decisione ridotto da 5 minuti a 30 secondi per asset.

**Files coinvolti:**
- `modules/sentiment.py` — funzione `summarize_news_for_asset()`
- `app/services/analyzer.py` — integrare nel pipeline
- `app/templates/asset_detail.html` — sezione news summary

### T3.3 Post-Trade LLM Review

**Problema:** Il trade journal registra P&L ma non analizza il "perche'" un trade ha funzionato o no. Nessun feedback loop.

**Cosa implementare:**
- [ ] Quando un trade viene chiuso, l'LLM analizza:
  - Condizioni di entry (QS, MTF, regime, calendario)
  - Price action durante il trade
  - Se SL/TP erano ottimali
  - Cosa avrebbe fatto diversamente
- [ ] Output: breve review (3-5 righe) salvata nel trade record
- [ ] Dashboard: pattern ricorrenti nei trade perdenti ("80% dei trade perdenti erano in sessione morta")
- [ ] Weekly digest: LLM analizza tutti i trade della settimana e suggerisce 3 miglioramenti

**Impatto atteso:** Feedback loop sistematico. Invece di fare journaling manuale, il sistema impara dai propri errori.

**Files coinvolti:**
- `app/services/trade_reviewer.py` — NUOVO
- `app/api/trades.py` — trigger review alla chiusura
- `app/templates/trades.html` — visualizzare review

---

## Phase T4 — Backtesting: Validare Prima di Tradare

> Obiettivo: prima di modificare qualsiasi parametro (soglie, pesi, SL/TP), validare l'impatto su dati storici.

### T4.1 Backtester Core

**Problema:** Nessun modo per validare se le modifiche migliorano o peggiorano i risultati. Tutti i parametri sono scelti arbitrariamente.

**Cosa implementare:**
- [x] Backtester engine che:
  1. Scarica dati storici per asset
  2. Computa indicatori e genera segnali
  3. Simula trade con SL/TP
  4. Calcola: win rate, profit factor, max drawdown, Sharpe ratio, avg R-multiple
- [x] Parametri configurabili: QS threshold, SL multiplier, TP multiplier
- [x] Kelly position sizing integrato nel backtester
- [x] CLI: `python -m modules.backtester --symbol NQ=F --period 6mo`

**Impatto atteso:** Ogni modifica puo' essere validata oggettivamente. Stop al "parameter tuning per intuizione".

**Files coinvolti:**
- `backtest.py` — NUOVO entry point
- `modules/backtester.py` — NUOVO engine
- `modules/price_data.py` — riutilizzare indicatori esistenti

### T4.2 Walk-Forward Optimization

**Problema:** Un backtest su tutto il periodo e' in-sample. Serve out-of-sample validation per evitare overfitting.

**Cosa implementare:**
- [x] Walk-forward: train su N giorni, test su M giorni, avanza di step
- [x] Per ogni finestra: run backtest su train, misura su test
- [x] Output: performance aggregata su tutti i periodi di test (out-of-sample)
- [x] Confronto in-sample vs out-of-sample metrics

**Impatto atteso:** Parametri robusti che funzionano in condizioni diverse, non solo nel periodo di backtest.

**Files coinvolti:**
- `modules/backtester.py` — estendere con walk-forward

### T4.3 Monte Carlo Simulation

**Problema:** Un backtest produce UNA equity curve. Ma il rischio reale e' nelle code della distribuzione (worst case scenario).

**Cosa implementare:**
- [x] Monte Carlo (1000 permutazioni dell'ordine dei trade)
- [x] Output: distribuzione equity curves con median + 5th/95th percentile bands
- [x] Confidence interval per max drawdown
- [x] Statistical distribution of final equity

**Impatto atteso:** Comprensione del rischio reale. Se il Monte Carlo mostra 15% ruin probability, il sistema e' troppo aggressivo.

---

## Phase T5 — Market Microstructure: Capire il "Quando"

> Obiettivo: non solo sapere "cosa" tradare, ma il momento esatto in cui entrare.

### T5.1 Order Flow Proxy (Volume Delta)

**Problema:** Il prezzo dice "dove" siamo, il volume dice "quanto interesse c'e'", ma manca la direzione del volume (compratori vs venditori).

**Cosa implementare:**
- [ ] Volume Delta proxy: per ogni barra, stimare buy vs sell volume
  - Up bar (close > open): volume attribuito 70% buy, 30% sell
  - Down bar: volume attribuito 30% buy, 70% sell
  - Doji: 50/50
- [ ] Cumulative Volume Delta (CVD): somma running del delta
- [ ] Divergenza CVD/Prezzo: prezzo sale ma CVD scende → smart money vende (bearish divergence)
- [ ] Aggiungere al report e al Quality Score (+1 se CVD conferma direzione)

**Impatto atteso:** Distinguere breakout genuini (con volume delta positivo) da fakeout (volume delta piatto/negativo).

**Files coinvolti:**
- `modules/price_data.py` — CVD calculation
- `modules/report.py` — sezione CVD

### T5.2 Heatmap Volume per Ora (deferred da Phase 3.2)

**Problema:** Il session filter blocca la "dead zone" (11-14 CET) ma non distingue tra ore buone e ottime. Lunedi' mattina e' diverso da venerdi' pomeriggio.

**Cosa implementare:**
- [ ] Analisi storica volume per ora del giorno e giorno della settimana (ultimi 60 giorni)
- [ ] Heatmap nel report: 5 giorni x 24 ore, colore = volume medio relativo
- [ ] Score orario 1-5 per il Quality Score: ora ad alto volume = +1, basso volume = -1
- [ ] "Best time to trade": suggerimento basato sui dati storici dell'asset specifico

**Impatto atteso:** Precision timing. Sapere che NQ ha il picco alle 15:30-16:00 CET e' piu' utile di un generico "NYSE open".

**Files coinvolti:**
- `modules/price_data.py` — volume per ora calculation
- `modules/report.py` — heatmap HTML
- `app/templates/asset_detail.html` — visualizzazione heatmap

### T5.3 Intermarket Analysis

**Problema:** Il sistema analizza ogni asset in isolamento. Ma NQ e' influenzato dal DXY (dollaro), dal VIX, e dai rendimenti dei Treasury (US10Y). Gold e' inversamente correlato al dollaro.

**Cosa implementare:**
- [x] Reference assets: DXY, US10Y per correlazione
- [x] Per ogni asset tradabile, definire correlazioni attese:
  - NQ/ES: inversamente correlato a US10Y
  - GC: inversamente correlato a DXY
  - EURUSD: inversamente correlato a DXY
- [x] Divergenza intermarket: se Gold + DXY entrambi salgono → warning
- [x] Funzione `compute_intermarket_signals()` in price_data.py

**Impatto atteso:** Anticipare rotazioni di mercato. Le divergenze intermarket precedono i reversal di 1-3 giorni.

**Files coinvolti:**
- `modules/price_data.py` — fetch reference assets, divergence detection
- `modules/report.py` — sezione intermarket

---

## Phase T6 — Portfolio Intelligence

> Obiettivo: passare da "analizzare singoli asset" a "gestire un portafoglio di trade".

### T6.1 Portfolio Heat Map

**Problema:** Il filtro correlazione attuale e' binario (>0.7 → skip). Non mostra l'esposizione aggregata del portafoglio.

**Cosa implementare:**
- [x] Endpoint `GET /api/analytics/heatmap` con matrice correlazione
- [x] Mappa calore delle correlazioni rolling (30 giorni)
- [x] Ritorna matrice correlazione per tutti gli asset configurati
- [ ] Suggerimento hedge automatico — DEFERRED

**Files coinvolti:**
- `app/api/trades.py` — endpoint portfolio exposure
- `app/templates/analytics.html` — portfolio heat map

### T6.2 Sector Rotation Detection

**Problema:** Il sistema non rileva rotazioni settoriali (risk-on → risk-off, growth → value). Queste rotazioni durano giorni/settimane e influenzano tutti gli asset.

**Cosa implementare:**
- [ ] Monitorare rapporti chiave: NQ/ES (growth vs value), GC/SPY (safe haven vs risk), DXY trend
- [ ] Classificare regime di mercato:
  - Risk-On: NQ > ES, VIX cala, DXY cala → favorire LONG su NQ, SHORT su GC
  - Risk-Off: ES > NQ, VIX sale, GC sale, DXY sale → favorire LONG su GC, SHORT su NQ
- [ ] Aggiungere al report come "Market Regime" (diverso dal trading regime LONG/SHORT)

**Impatto atteso:** Allineare i trade con il flusso macro. I trader retail perdono spesso perche' tradano contro il flow istituzionale.

---

## Cosa NON Aggiungere (Aggiornato)

| Tentazione | Perche' No |
|---|---|
| Machine Learning per predizioni di prezzo | Con 6 asset e dati limitati, qualsiasi modello ML va in overfit. L'LLM per reasoning e' piu' robusto. |
| Esecuzione automatica | Su Fineco CFD, l'esecuzione manuale con disciplina batte l'automazione. Troppi edge case (slippage, parziali, errori broker). |
| 50+ indicatori tecnici | 6 indicatori con pesi adattivi > 50 indicatori con peso fisso. Piu' indicatori = piu' rumore. |
| Crypto/altcoin trading | Focus su 4-8 asset liquidi con spread bassi. Crypto ha spread, funding, e volatilita' ingestibili per un sistema rule-based. |
| Social media sentiment | Twitter/Reddit sono rumore, non segnale. Le news aggregate + Polymarket coprono gia' il sentiment retail e istituzionale. |
| Multi-broker execution | Un broker, un set di regole, nessuna complessita' inutile. |

---

## Tracking Avanzamento

| Phase | Feature | Status | Impatto Stimato |
|-------|---------|--------|-----------------|
| T1.1 | Adaptive Weights | `DONE` | +5-8% win rate |
| T1.2 | Volume Profile | `DEFERRED` | Richiede tick data (non disponibile da yfinance) |
| T1.3 | Candle Patterns | `DONE` | +1-2 QS accuracy |
| T2.1 | Adaptive SL/TP | `DONE` | -10% SL hit rate |
| T2.2 | Kelly Position Sizing | `DONE` | Ottimizzazione rischio |
| T2.3 | Drawdown Breaker | `DONE` | Max DD < 7% |
| T3.1 | LLM Trade Thesis | `DONE` | Decision quality |
| T3.2 | News Summarizer | `DONE` | Tempo decisione -80% |
| T3.3 | Post-Trade Review | `DEFERRED` | Post Sprint 6 |
| T4.1 | Backtester | `DONE` | Validazione parametri |
| T4.2 | Walk-Forward | `DONE` | Robustezza |
| T4.3 | Monte Carlo | `DONE` | Risk awareness |
| T5.1 | Volume Delta/CVD | `DEFERRED` | Richiede tick data |
| T5.2 | Volume Heatmap | `DEFERRED` | Richiede tick data |
| T5.3 | Intermarket | `DONE` | Anticipare reversal |
| T6.1 | Portfolio Heat Map | `DONE` | Exposure control |
| T6.2 | Sector Rotation | `DEFERRED` | Rilevante con 10+ asset |

---

*Creato: 20 Marzo 2026 — analisi quant/trading v5.2.0*
*Aggiornato: 20 Marzo 2026 — 12/17 task completati in v5.3.0–v6.0.0*
