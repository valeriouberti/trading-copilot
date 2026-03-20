# Trading Copilot — Manuale Operativo Completo

### Un sistema algoritmico multi-segnale per CFD su mercati finanziari

**Versione 4.1 — Marzo 2026**

---

> **Disclaimer**: Questo documento ha finalità esclusivamente educative e informative.
> Nessuna parte di questo manuale costituisce consulenza finanziaria,
> legale o fiscale. Il trading su CFD comporta un rischio elevato di perdita
> del capitale. Opera solo con fondi che puoi permetterti di perdere.

---

## Indice

1. [Filosofia del Sistema](#1-filosofia-del-sistema)
2. [Architettura Generale](#2-architettura-generale)
3. [Layer 1 — Feed News e Aggregazione](#3-layer-1--feed-news-e-aggregazione)
4. [Layer 2 — Analisi LLM del Sentiment](#4-layer-2--analisi-llm-del-sentiment)
5. [Layer 3 — Indicatori Tecnici](#5-layer-3--indicatori-tecnici)
6. [Layer 4 — Polymarket Signal](#6-layer-4--polymarket-signal)
7. [Il Sistema di Confluenza](#7-il-sistema-di-confluenza)
8. [I Tre Regimi Operativi](#8-i-tre-regimi-operativi)
9. [Tutti i Casi Possibili](#9-tutti-i-casi-possibili)
10. [La Strategia di Entry](#10-la-strategia-di-entry)
11. [Gestione del Rischio](#11-gestione-del-rischio)
12. [Key Levels — Supporti e Resistenze](#12-key-levels--supporti-e-resistenze)
13. [Calendario Economico](#13-calendario-economico)
14. [Multi-Timeframe Alignment](#14-multi-timeframe-alignment)
15. [Session Time Filter](#15-session-time-filter)
16. [Setup Quality Score](#16-setup-quality-score)
17. [Correlation Filter](#17-correlation-filter)
18. [Trailing Stop Engine](#18-trailing-stop-engine)
19. [Il Report Giornaliero](#19-il-report-giornaliero)
20. [Routine Operativa Quotidiana](#20-routine-operativa-quotidiana)
21. [Validazione e Miglioramento Continuo](#21-validazione-e-miglioramento-continuo)
22. [Limitazioni e Rischi del Sistema](#22-limitazioni-e-rischi-del-sistema)

---

## 1. Filosofia del Sistema

### Il Problema che Risolve

Un trader retail che opera su CFD affronta ogni giorno lo stesso problema:
i mercati finanziari sono influenzati da centinaia di variabili simultanee —
notizie macroeconomiche, decisioni delle banche centrali, tensioni geopolitiche,
dati societari, sentiment degli investitori istituzionali.

Processare manualmente tutte queste informazioni ogni mattina è impossibile.
Il cervello umano è soggetto a bias cognitivi, stanchezza, overconfidence.

**Il Trading Assistant risolve questo problema** costruendo un sistema che:

- Aggrega automaticamente centinaia di fonti informative
- Le processa con intelligenza artificiale in pochi secondi
- Le combina con analisi tecnica quantitativa
- Le valida attraverso i mercati predittivi
- Produce un report strutturato che guida la decisione operativa

### Cosa il Sistema NON è

Il sistema **non sostituisce** il giudizio umano. Non è un robot che piazza
ordini automaticamente. Non garantisce profitti. Non prevede il futuro.

È uno strumento di **decision support** — riduce il rumore informativo,
aumenta la qualità delle decisioni, e impone disciplina operativa attraverso
regole chiare e verificabili.

### Il Principio della Confluenza

Il concetto centrale dell'intero sistema è la **confluenza**:
una singola fonte di segnale può sbagliare. Tre fonti indipendenti
che concordano hanno una probabilità statisticamente più alta di essere corrette.

```

Fonte 1 (News + LLM)  ──→ BEARISH
Fonte 2 (Tecnici)     ──→ BEARISH  ──→ CONFLUENZA → Alta probabilità
Fonte 3 (Polymarket)  ──→ BEARISH

```

Il sistema è progettato per identificare questi momenti di alta confluenza
e segnalarli chiaramente al trader, che prende la decisione finale.

---

## 2. Architettura Generale

Il sistema è composto da quattro layer informativi indipendenti,
ciascuno con una fonte dati distinta e una logica di elaborazione propria.

```

╔══════════════════════════════════════════════════════════════╗
║                    TRADING ASSISTANT                          ║
╠══════════════════════════════════════════════════════════════╣
║                                                               ║
║  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌────────┐ ║
║  │  LAYER 1    │  │  LAYER 2    │  │ LAYER 3  │  │LAYER 4 │ ║
║  │  Feed News  │  │  LLM        │  │ Tecnici  │  │Poly-   │ ║
║  │  RSS        │→ │  Sentiment  │  │ yfinance │  │market  │ ║
║  │             │  │             │  │ +12Data  │  │        │ ║
║  └─────────────┘  └─────────────┘  └──────────┘  └────────┘ ║
║         │                │               │            │       ║
║         └────────────────┴───────────────┴────────────┘       ║
║                                   │                           ║
║              ┌────────────────────┼────────────────────┐      ║
║              │                    │                    │       ║
║    ┌─────────▼────────┐ ┌────────▼────────┐ ┌────────▼─────┐ ║
║    │ Key Levels       │ │ Econ Calendar   │ │ MTF Analysis │ ║
║    │ PDH/PDL/Pivots   │ │ ForexFactory    │ │ W/D/1H EMA   │ ║
║    └─────────┬────────┘ └────────┬────────┘ └────────┬─────┘ ║
║              └────────────────────┼────────────────────┘      ║
║                                   │                           ║
║                     ┌─────────────▼──────────────┐           ║
║                     │   MOTORE DI CONFLUENZA      │           ║
║                     │   Hallucination Guard       │           ║
║                     │   Quality Score (1-5)       │           ║
║                     │   Correlation Filter        │           ║
║                     │   Validation Flags          │           ║
║                     └─────────────┬──────────────┘           ║
║                                   │                           ║
║                     ┌─────────────▼──────────────┐           ║
║                     │       REPORT HTML           │           ║
║                     │   + Terminal Summary        │           ║
║                     └─────────────┬──────────────┘           ║
║                                   │                           ║
║                     ┌─────────────▼──────────────┐           ║
║                     │     TRADER (umano)          │           ║
║                     │   TradingView + Fineco      │           ║
║                     │   (Trailing Stop Engine)    │           ║
║                     └─────────────────────────────┘           ║
╚══════════════════════════════════════════════════════════════╝

```

Ogni layer opera in modo indipendente: un guasto o un'assenza di dati
in uno non blocca gli altri. Il sistema è progettato per degradare
in modo controllato.

### Ottimizzazioni Architetturali

- **I/O Parallelo**: I Layer 1, 3 e 4 vengono eseguiti in parallelo tramite
  `concurrent.futures.ThreadPoolExecutor` (3 worker), riducendo il tempo totale
  del pipeline da sequenziale (~30s) a parallelo (~12-15s).
- **Twelve Data fallback**: Se yfinance fallisce, il sistema tenta automaticamente
  Twelve Data come fonte alternativa (richiede `TWELVE_DATA_API_KEY`, free tier).
- **Retry con backoff**: Tutti i componenti di I/O (RSS, yfinance, Twelve Data, Polymarket API)
  implementano retry con backoff esponenziale (3 tentativi, base 2s).
- **Progress bar**: `tqdm` mostra lo stato di avanzamento durante il fetch parallelo.
- **Trade Log**: Il sistema registra i trade in `trade_log.csv` (con quality score) e fornisce
  statistiche di accuracy dopo 30+ trade direzionali (flag `--log-trade`, `--review-trades`).
- **Fuso orario italiano**: Report e terminal summary mostrano l'ora italiana (Europe/Rome).
- **Key Levels**: PDH/PDL/PDC, PWH/PWL, Pivot Points classici e livelli psicologici
  con distanza % dal prezzo corrente.
- **Calendario Economico**: Eventi high-impact da Forex Factory con regime override
  automatico a NEUTRAL entro 2 ore dall'evento.
- **Multi-Timeframe Analysis**: EMA20/EMA50 su Weekly, Daily e 1H con classificazione
  di allineamento (ALIGNED/PARTIAL/CONFLICTING) e penalità nel composite score.
- **Session Time Filter**: Finestre operative London (08:00-09:00 CET) e NYSE (15:30-16:30 CET)
  con blocco dead zone (11:00-14:00 CET).
- **Quality Score**: Score 1-5 per setup basato su confluenza, ADX>25, key level,
  candle pattern e volume. Regola: trade solo score >= 4.
- **Correlation Filter**: Matrice correlazione 30 giorni tra asset. Blocca trade
  same-direction su coppie con correlazione > 0.7.
- **Trailing Stop Engine**: 3 modalità di uscita nel Pine Script (Fixed TP, Trailing,
  Partial+Trail) con breakeven a +1R e trail a +2R.

---

## 3. Layer 1 — Feed News e Aggregazione

### Cos'è un Feed RSS

RSS (Really Simple Syndication) è un formato standard usato da tutti
i principali media finanziari per pubblicare i propri articoli in tempo reale.
È la stessa tecnologia usata da Bloomberg, Reuters, Yahoo Finance per
distribuire le notizie ai propri abbonati.

Il sistema si connette a questi feed ogni volta che viene eseguito,
scaricando automaticamente tutti gli articoli pubblicati nelle ultime
N ore (configurabile, default 16 ore).

### Fonti Utilizzate

Il sistema aggrega news da queste fonti gratuite:

| Fonte                       | Tipo di contenuto                              | Affidabilità |
| --------------------------- | ---------------------------------------------- | ------------ |
| **Yahoo Finance RSS**       | Notizie societarie e macro per asset specifici | Alta         |
| **CNBC Top News**           | Notizie finanziarie e macro USA                | Molto alta   |
| **Investing.com**           | Analisi mercati, dati economici                | Media-Alta   |
| **MarketWatch Top Stories** | Notizie mercati, macro, earnings               | Alta         |

### Il Processo di Pulizia

Le notizie grezze contengono molto rumore: titoli duplicati da
fonti diverse, articoli irrilevanti, notizie troppo vecchie.
Il sistema applica tre filtri automatici:

1. **Filtro temporale**: esclude articoli pubblicati prima della
   finestra temporale configurata (es. ultimi 16 ore)

2. **Deduplicazione**: rimuove articoli con titoli simili ≥ 85%
   (stesso evento riportato da fonti diverse conta una volta sola)

3. **Filtro per asset**: quando possibile, prioritizza news che
   menzionano esplicitamente l'asset che si intende tradare

### Perché le News sono Importanti per il Trading

I mercati finanziari sono "anticipatori" — il prezzo di un asset
riflette le aspettative future degli operatori, non solo i dati presenti.
Le notizie cambiano queste aspettative istantaneamente.

Un dato sull'inflazione superiore alle attese → aspettative di tassi
più alti → vendite sulle obbligazioni e pressione sulle azioni growth
come il Nasdaq → movimento intraday significativo in pochi minuti.

Il feed news cattura questi eventi **prima** che si riflettano
completamente sul prezzo, dando un vantaggio informativo strutturato.

---

## 4. Layer 2 — Analisi LLM del Sentiment

### Cosa Sono i Large Language Models

Un Large Language Model (LLM) è un sistema di intelligenza artificiale
addestrato su enormi quantità di testo (libri, articoli, forum, documenti
accademici). Ha "letto" miliardi di pagine di testo finanziario, report
di analisti, commenti di mercato, trascrizioni di banche centrali.

Questa formazione gli permette di **comprendere il significato** di un
testo finanziario con una precisione simile a quella di un analista esperto,
ma in millisecondi e su centinaia di articoli simultaneamente.

### Il Compito Specifico: Sentiment Analysis (v2 — Two-Pass Chain-of-Thought)

Il sistema usa un approccio a due passaggi per migliorare la qualità dell'analisi:

**Pass 1 — Ragionamento (Chain-of-Thought):**
L'LLM ragiona step-by-step sulle notizie con temperatura più alta (0.4)
e 1000 token. Identifica i driver chiave, analizza l'impatto su ogni asset
specifico, e valuta il contesto macro.

**Pass 2 — Estrazione strutturata (JSON):**
L'output del ragionamento viene dato in input a un secondo prompt con
temperatura bassa (0.1) e few-shot calibration examples per estrarre
un JSON strutturato con:

- **Sentiment score** (da -3 a +3): quanto è positivo o negativo il
  quadro informativo complessivo per i mercati?
- **Per-asset scores**: punteggio specifico per OGNI asset (es. Fed hawkish
  è bearish per NQ ma può essere bullish per USD)
- **Key drivers** (3 fattori): quali sono le tre notizie o tendenze
  principali che guidano il sentiment oggi?
- **Directional bias** (BULLISH/BEARISH/NEUTRAL): in quale direzione
  il sentiment spinge i prezzi?
- **Risk events**: ci sono eventi nelle prossime 4-8 ore che potrebbero
  causare movimenti bruschi?

Se il two-pass fallisce, il sistema fa fallback su un singolo prompt
(single-pass, comportamento v1).

### Temporal Weighting delle Notizie

Le notizie vengono taggate con la loro recency prima di essere inviate
all'LLM (es. `[2h fa]`, `[30m fa]`). Il prompt istruisce il modello
che notizie recenti pesano 3x rispetto a quelle più vecchie.

### Few-Shot Calibration

Il prompt di estrazione include esempi calibrati per ancorare i punteggi:

- +3.0 = Fed taglia tassi a sorpresa + occupazione record + CPI sotto attese
- +1.0 = Dati mixed ma leggermente positivi
- 0.0 = Nessuna notizia rilevante
- -1.0 = Dati occupazione deboli, tensioni commerciali
- -3.0 = Crisi bancaria + recessione confermata + panic selling

### FinBERT Ensemble Cross-Validation

Quando Groq ha successo, il sistema esegue FinBERT in parallelo come
cross-validazione (non solo come fallback):

- **AGREE** (divergenza ≤ 1.0): boost confidenza +5%
- **PARTIAL** (divergenza 1.0-2.0): nessuna modifica
- **DISAGREE** (divergenza > 2.0): riduzione confidenza -15%

Questo aiuta a rilevare allucinazioni dell'LLM e fornisce un secondo
punto di vista indipendente.

### La Scala del Sentiment

```

-3  ──  -2  ──  -1  ──  0  ──  +1  ──  +2  ──  +3
│        │       │      │       │       │       │
Crisi   Molto  Lieve  Neutro  Lieve  Buono  Euforia
acuta   neg.   neg.          pos.

```

Valori estremi (±3) sono rari e segnalano eventi eccezionali
(crolli improvvisi, annunci Fed inattesi, eventi geopolitici gravi).
La maggior parte delle giornate si muove tra -1 e +1.

### Perché l'LLM è Migliore dell'Analisi per Parole Chiave

Un approccio naïve conterebbe semplicemente le parole positive e negative
("rally", "crash", "growth", "loss"). L'LLM capisce il **contesto**:

- _"La Fed non taglierà i tassi"_ → bearish per le azioni
  (un sistema a parole chiave non vedrebbe né "crash" né "sell")

- _"Il PIL è cresciuto meno del previsto"_ → bearish, anche se
  "cresciuto" è una parola positiva

- _"I mercati hanno già scontato il rialzo dei tassi"_ → potenzialmente
  bullish, perché la cattiva notizia era già nel prezzo

Questa comprensione contestuale è il valore principale dell'LLM nel sistema.

### Il Modello Utilizzato: Llama 3.3 70B via Groq

Il sistema usa **Llama 3.3 70B**, un modello open-source sviluppato da Meta,
accessibile gratuitamente attraverso l'infrastruttura Groq.

Groq è una piattaforma cloud che offre inferenza LLM ultra-veloce
(risposta in < 1 secondo) con un livello gratuito sufficiente per
l'uso quotidiano descritto in questo sistema.

**Perché Llama 3.3 70B:**

- 70 miliardi di parametri: capacità di ragionamento complessa
- Ottimizzato per task di analisi e classificazione
- Disponibile gratuitamente (free tier Groq: 14.400 richieste/giorno)
- Performance paragonabile a GPT-4 su task finanziari

### Il Meccanismo Anti-Allucinazione

Gli LLM possono "allucinare" — produrre informazioni plausibili ma false.
Nel contesto finanziario questo è pericoloso.

Il sistema implementa un **Hallucination Guard** che cross-verifica
l'output dell'LLM contro:

1. **Baseline a parole chiave**: il sentiment score LLM deve essere
   coerente con un conteggio semplice di parole bullish/bearish nei titoli
   (divergenza > 3 punti → flag di allerta)

2. **Coerenza con i tecnici**: il bias direzionale LLM non deve
   contraddire tutti gli indicatori tecnici simultaneamente

3. **Coerenza con Polymarket**: il bias LLM non deve contraddire
   mercati predittivi con confidence > 65%

Se uno o più check falliscono, il report mostra un **flag di allerta rosso**
e il trader deve approfondire manualmente prima di operare.

---

## 5. Layer 3 — Indicatori Tecnici

### Fonti Dati: yfinance + Twelve Data Fallback

Il sistema utilizza **yfinance** come fonte primaria per i dati OHLCV
(Open, High, Low, Close, Volume). Se yfinance fallisce (timeout, rate
limit, errore di rete), il sistema tenta automaticamente **Twelve Data**
come fallback.

| Fonte          | Costo      | Copertura                  | Intraday         |
| -------------- | ---------- | -------------------------- | ---------------- |
| **yfinance**   | Gratuito   | Futures, Forex, Azioni     | 5m (ultimi 5gg)  |
| **Twelve Data**| Free tier  | Futures, Forex, Azioni     | 5m (30+ giorni)  |

Per attivare il fallback Twelve Data:
```bash
export TWELVE_DATA_API_KEY="la_tua_chiave_qui"
```

Il report mostra un badge "via twelvedata" accanto all'asset quando
il fallback viene utilizzato. Se la chiave non è impostata, il fallback
è semplicemente disabilitato.

### Perché Servono i Tecnici se Abbiamo l'LLM

L'LLM analizza il **perché** il mercato potrebbe muoversi (notizie, contesto).
Gli indicatori tecnici analizzano il **come** si sta muovendo effettivamente
(prezzi, volumi, momentum). Sono informazioni complementari, non alternative.

Un bias LLM bearish su news macro + un trend tecnico ancora rialzista
significa che il mercato sta resistendo alla pressione — segnale di
possibile inversione imminente, ma non ancora confermata. In questo caso
si aspetta prima di operare.

### Gli Indicatori Utilizzati (8 totali)

**EMA 20 e EMA 50 (Exponential Moving Average)**

Le medie mobili esponenziali calcolano il prezzo medio degli ultimi
20 e 50 periodi, dando più peso ai periodi recenti.

- EMA20 > EMA50 → trend rialzista strutturale (i prezzi recenti
  sono mediamente più alti di quelli passati)
- EMA20 < EMA50 → trend ribassista strutturale
- Incrocio EMA20/EMA50 → possibile cambio di tendenza

Nel sistema, la posizione relativa delle due EMA determina
il **trend strutturale** dell'asset — condizione necessaria
per qualsiasi entry direzionale.

**VWAP (Volume Weighted Average Price)**

Il VWAP è il prezzo medio della sessione ponderato per i volumi
scambiati. È il riferimento usato dai trader istituzionali e
dagli algoritmi delle banche per valutare la qualità di un'esecuzione.

- Prezzo sopra VWAP → gli acquirenti hanno il controllo della sessione
- Prezzo sotto VWAP → i venditori hanno il controllo
- Il VWAP agisce come supporto/resistenza dinamica intraday

Il sistema usa il VWAP come filtro di qualità dell'entry:
si entra long solo sopra il VWAP, short solo sotto.

**RSI — Relative Strength Index (14 periodi)**

L'RSI misura la velocità e la magnitudine dei movimenti di prezzo
recenti, producendo un valore tra 0 e 100.

- RSI > 70: mercato ipercomprato (il prezzo ha salito troppo velocemente)
  → attenzione ai long, possibile correzione
- RSI < 30: mercato ipervenduto (il prezzo ha sceso troppo velocemente)
  → attenzione agli short, possibile rimbalzo
- RSI 30-70: zona neutra, segnali operativi validi

Il sistema blocca i segnali di entry quando l'RSI è in zona estrema,
evitando di entrare su movimenti già esauriti.

**ATR — Average True Range (14 periodi)**

L'ATR misura la volatilità media dell'asset nelle ultime 14 candele.
Non ha un'interpretazione direzionale — indica solo quanto si muove
tipicamente il mercato in un dato periodo.

Il sistema usa l'ATR per **calibrare automaticamente** Stop Loss e
Take Profit:

- Stop Loss = distanza ATR × 1.5 dal prezzo di entry
- Take Profit = distanza ATR × 3.0 (Risk/Reward 1:2)

Questo meccanismo è fondamentale: lo stesso asset in un giorno volatile
(ATR alto) avrà stop più ampi rispetto a un giorno tranquillo (ATR basso),
adattando automaticamente il rischio alle condizioni di mercato.

**MACD (Moving Average Convergence Divergence)**

Il MACD misura la relazione tra due medie mobili (12 e 26 periodi)
e produce un segnale di momentum direzionale.

- MACD line sopra Signal line → momentum rialzista
- MACD line sotto Signal line → momentum ribassista
- Crossover → possibile cambio di momentum

Il sistema usa il MACD come conferma del momentum, non come
segnale primario di entry.

**Bollinger Bands (20 periodi, 2 deviazioni standard)**

Le Bande di Bollinger creano un canale dinamico attorno al prezzo
basato sulla deviazione standard. Quando le bande si restringono
(squeeze), la volatilità è compressa e un breakout è imminente.

- Prezzo > banda superiore → BEARISH (overextended, possibile ritorno)
- Prezzo < banda inferiore → BULLISH (oversold, possibile rimbalzo)
- Squeeze (bandwidth < 4%) → NEUTRAL (breakout imminente, attendere direzione)
- Prezzo tra media e superiore → BULLISH (momentum positivo)
- Prezzo tra media e inferiore → BEARISH (momentum negativo)

Le BB completano l'RSI: entrambi misurano eccesso, ma con metodi diversi
(deviazione standard vs. rapporto forza relativa).

**Stochastic (14, 3, 3)**

Lo Stocastico misura la posizione del prezzo di chiusura rispetto al
range high-low degli ultimi 14 periodi. Produce due linee: %K (veloce)
e %D (lenta, media mobile di %K).

- %K > 80 → BEARISH (ipercomprato)
- %K < 20 → BULLISH (ipervenduto)
- %K incrocia %D dal basso → BULLISH crossover (segnale di entry)
- %K incrocia %D dall'alto → BEARISH crossover (segnale di exit)

Il valore principale dello Stocastico è il **crossover**: segnala
il momento esatto in cui il momentum cambia direzione, particolarmente
utile nella strategia EMA pullback per confermare l'esaurimento del
ritracciamento.

**ADX — Average Directional Index (14 periodi)**

L'ADX misura la **forza del trend**, non la direzione. Produce un
valore da 0 a 100:

- ADX > 25 → trend forte (il mercato si muove con convinzione)
- ADX < 20 → mercato in range (movimenti senza direzione chiara)

Il sistema mostra anche +DI e -DI che indicano la direzione:
+DI > -DI = trend rialzista, -DI > +DI = trend ribassista.

L'ADX è **non-direzionale** nel punteggio composito (come l'ATR) —
serve come filtro di qualità: un segnale di entry ha più valore
quando ADX > 25 perché il trend ha forza.

### Il Punteggio Tecnico Composito

Il sistema combina **6 indicatori direzionali** in un unico score
(ATR e ADX sono informativi, non contano nel punteggio):

```

Indicatore    Condizione Bullish                Tipo
────────────────────────────────────────────────────────
EMA20/50      EMA20 > EMA50                    Direzionale (+1)
VWAP          Prezzo > VWAP                    Direzionale (+1)
RSI           30 < RSI < 70 + trending up      Direzionale (+1)
MACD          Signal bullish crossover/pos.    Direzionale (+1)
BB            Prezzo sopra media BB            Direzionale (+1)
Stochastic    %K < 80 + bullish crossover      Direzionale (+1)
────────────────────────────────────────────────────────
ATR           Volatilità alta/bassa            Informativo
ADX           Trend forte/debole               Informativo
────────────────────────────────────────────────────────
Score 4-6/6  → BULLISH  (67-100% confidence)
Score 3/6    → NEUTRAL  (50% confidence)
Score 0-2/6  → BEARISH  (67-100% confidence)

```

Con 6 indicatori invece di 4, il punteggio composito è più robusto:
un singolo indicatore rumoroso ha meno impatto sul risultato finale.

---

## 6. Layer 4 — Polymarket Signal

### Cosa sono i Mercati Predittivi

I mercati predittivi sono piattaforme dove le persone scommettono
denaro reale sull'esito di eventi futuri. La probabilità implicita
nei prezzi di questi mercati riflette il consenso aggregato di
migliaia di partecipanti con incentivi economici reali ad essere accurati.

**La differenza rispetto ai sondaggi**: un analista che pubblica
una previsione non perde nulla se sbaglia. Un trader su Polymarket
che scommette su un evento ci mette soldi propri — ha un forte
incentivo a valutare correttamente la probabilità reale.

### Polymarket nel Dettaglio

Polymarket è la piattaforma di mercati predittivi più liquida al mondo,
con volumi che superano $1 miliardo al mese su eventi finanziari,
politici e macroeconomici.

I mercati più rilevanti per il trading su CFD includono:

```

Esempi di mercati attivi:
─────────────────────────────────────────────────────────────
"La Fed taglierà i tassi a Maggio 2026?"
→ Prob. SÌ: 34%  | Volume: \$2.4M
→ Lettura: il mercato si aspetta che la Fed rimanga ferma (bearish bonds)

"Gli USA entreranno in recessione nel 2026?"
→ Prob. SÌ: 41%  | Volume: \$1.8M
→ Lettura: rischio recessione elevato ma non dominante

"L'inflazione USA supererà il 3% a Marzo 2026?"
→ Prob. SÌ: 67%  | Volume: \$890K
→ Lettura: consenso su inflazione persistente (bearish azionario growth)
─────────────────────────────────────────────────────────────

```

### Come il Sistema Interpreta Polymarket

Il modulo Polymarket del sistema opera in 5 fasi:

1. **Recupero via /events con tag_slug curati** (v3): il sistema interroga
   l'endpoint `/events` dell'API Gamma di Polymarket utilizzando tag_slug
   finanziari specifici per gli asset configurati. Per ogni asset, vengono
   selezionati tag_slug curati tra quelli realmente disponibili su Polymarket:

   | Asset            | Tag slugs utilizzati                                           |
   | ---------------- | -------------------------------------------------------------- |
   | NQ, ES, S&P      | `fed`, `inflation`, `gdp`, `unemployment`, `tariffs`, `stocks`, `economy`, `geopolitics` |
   | EUR              | `fed`, `inflation`, `interest-rates`, `economy`, `tariffs`, `geopolitics` |
   | Gold (GC)        | `gold`, `commodities`, `geopolitics`, `fed`, `inflation`, `oil` |
   | Oil (CL)         | `oil`, `commodities`, `geopolitics`, `fed`                    |

   Ogni evento contiene mercati nidificati che vengono estratti e deduplicati.

   > **Nota tecnica (v3)**: l'endpoint `/markets` ignora completamente il
   > parametro `tag` — restituisce tutti i mercati indipendentemente dalla
   > categoria, includendo sport, meteo e intrattenimento. L'endpoint
   > `/events` con `tag_slug` è l'unico che filtra correttamente server-side.

2. **Filtro per categoria e volume**: ogni mercato viene classificato in una
   categoria tematica (FED, MACRO, COMMODITY, GEOPOLITICAL, CRYPTO) tramite
   parole chiave nel titolo. I mercati classificati come OTHER (sport, meteo,
   intrattenimento) vengono **scartati automaticamente** (category gate).
   Mercati illiquidi sotto la soglia volume vengono esclusi perché le
   probabilità con pochi partecipanti sono inaffidabili.

3. **Classificazione LLM con Impact Magnitude**: ogni mercato viene
   inviato al modello LLM (Llama 3.3 70B via Groq) che classifica
   l'impatto dell'evento con DUE criteri:
   - **Direzione**: `BULLISH_IF_YES` o `BEARISH_IF_YES`
   - **Magnitude** (1-5): quanto è market-moving l'evento
     - 1 = marginale (politica minore)
     - 3 = moderato (dati economici, tensioni commerciali)
     - 5 = market-moving (decisioni Fed a sorpresa, crisi)

   **Fallback**: se Groq non è disponibile, usa classificazione keyword
   con magnitude default = 3.

4. **Segnale pesato (v2 — fixed probability inversion)**: il segnale
   finale tiene conto di ENTRAMBI i lati di ogni mercato.

   **Il problema della v1**: "Recessione USA al 12% SÌ" veniva conteggiato
   solo come 12% bearish, ignorando che l'88% di probabilità NO recessione
   è un segnale fortemente bullish.

   **La formula v2**: per ogni mercato:

   ```
   Se BEARISH_IF_YES:
     bearish_score += prob_yes × weight
     bullish_score += (100 - prob_yes) × weight  ← NUOVO: lato NO

   Se BULLISH_IF_YES:
     bullish_score += prob_yes × weight
     bearish_score += (100 - prob_yes) × weight  ← NUOVO: lato NO

   weight = volume × time_weight × magnitude
   ```

   **Temporal decay**: mercati che scadono presto pesano di più.
   Formula: `time_weight = 1.0 / (1.0 + days_to_resolution / 14.0)`
   (half-life di 2 settimane). Un mercato che scade oggi ha peso ~1.0,
   uno che scade tra 6 mesi ha peso ~0.07.

   ```

   Esempio di calcolo v2:
   ─────────────────────────────────────────────────────────
   Mercato A: "Recessione USA?" (BEARISH_IF_YES)
   Prob SÌ: 12% | Volume: $500K | Time: 0.5 | Mag: 4
   Weight = 500K × 0.5 × 4 = 1M
   Bearish: 12 × 1M = 12M
   Bullish: 88 × 1M = 88M  ← la probabilità NO è BULLISH!

   Net = (88M - 12M) / 1M = +76 → fortemente BULLISH
   ─────────────────────────────────────────────────────────

   ```

5. **Soglie decisionali v2**:
   - Net score > +15 → segnale BULLISH
   - Net score < -15 → segnale BEARISH
   - Altrimenti → NEUTRAL
   - Confidenza = min(100%, 50 + |net_score|)

### Perché Polymarket è una Fonte Valida

La ricerca accademica ha documentato che i mercati predittivi battono
sistematicamente i modelli econometrici tradizionali e le previsioni
degli analisti professionisti nella stima delle probabilità di eventi macro.

Per il trader retail, il valore principale è diverso dalle news:
le news dicono cosa è successo, Polymarket dice cosa il mercato
**si aspetta che succeda**. Questa informazione forward-looking
è complementare all'analisi retrospettiva delle notizie.

### Dettagli Tecnici dell'Implementazione

```

Architettura del modulo Polymarket (v3):
════════════════════════════════════════════════════════════

  Asset configurati (config.yaml)
         │
         ▼
  ┌──────────────────────────┐
  │ _get_tag_slugs_for_assets │ → tag_slugs: ["fed", "gdp", "tariffs", ...]
  └──────────────────────────┘   (curati per asset, basati su slug reali)
         │
         ▼
  ┌──────────────────────────┐
  │   fetch_markets() v3      │ → GET /events?tag_slug=X (per ogni slug)
  │                            │ → Estrazione mercati da eventi nidificati
  │   + dedup                  │ → Deduplicazione cross-tag
  │   + category gate          │ → Scarta OTHER (sport, meteo, ecc.)
  └──────────────────────────┘
         │
         ▼
  ┌─────────────────────────────┐
  │ classify_markets_with_llm() │ → Groq LLM: direction + magnitude (1-5)
  │   (fallback: keyword)       │ → Gestisce ambiguità semantica
  └─────────────────────────────┘
         │
         ▼
  ┌──────────────────────────┐
  │  compute_signal() v2      │ → Entrambi i lati (YES + NO) per mercato
  │  × volume × time × mag   │ → Temporal decay (2-week half-life)
  │                            │ → BULLISH / BEARISH / NEUTRAL + confidenza
  └──────────────────────────┘

```

---

## 7. Il Sistema di Confluenza

### Come i Tre Segnali si Combinano

Il cuore del sistema è il motore di confluenza, che combina
i tre segnali indipendenti in un giudizio operativo.

```

MATRICE DI CONFLUENZA
══════════════════════════════════════════════════════════════
LLM          TECNICI       POLYMARKET    RISULTATO
──────────────────────────────────────────────────────────────
BEARISH  +   BEARISH   +   BEARISH    = ✅ TRIPLE CONFLUENCE
Setup SHORT prioritario

BULLISH  +   BULLISH   +   BULLISH    = ✅ TRIPLE CONFLUENCE
Setup LONG prioritario

BEARISH  +   BEARISH   +   NEUTRAL    = ⚡ STRONG SIGNAL
Setup SHORT valido

BULLISH  +   BULLISH   +   NEUTRAL    = ⚡ STRONG SIGNAL
Setup LONG valido

BEARISH  +   NEUTRAL   +   BEARISH    = ⚡ MODERATE SIGNAL
Setup SHORT con cautela

BEARISH  +   NEUTRAL   +   NEUTRAL    = ⚠️ WEAK SIGNAL
Solo osservazione

BEARISH  +   BULLISH   +   NEUTRAL    = ❌ CONFLITTO
Nessun trade, attendi

BULLISH  +   BEARISH   +   BEARISH    = ❌ CONFLITTO
Nessun trade, attendi

NEUTRAL  +   qualsiasi +   qualsiasi  = ⚠️ GIORNO FLAT
Solo trade con setup perfetto
══════════════════════════════════════════════════════════════

```

### I Validation Flags

Il sistema genera automaticamente flag di allerta in queste situazioni:

```

🔴 SENTIMENT_MISMATCH
Quando: LLM score diverge di più di 3 punti dalla baseline
a parole chiave.
Significato: l'LLM potrebbe stare "allucinando" il sentiment.
Azione: non tradare, verifica manualmente le news.

🔴 DIRECTION_CONFLICT / DIRECTION_CONFLICT_{ASSET}
Quando: LLM bias è opposto al segnale tecnico composito.
Con per-asset scoring (v2): il conflitto viene rilevato per ogni
singolo asset (es. DIRECTION_CONFLICT_NQ=F: LLM BULLISH vs tech BEARISH).
Significato: news e prezzi raccontano storie diverse.
Azione: aspetta che uno dei due si allinei.

🟠 POLYMARKET_CONFLICT
Quando: LLM e Polymarket sono in direzioni opposte
con confidence > 65%.
Significato: il consenso del mercato predittivo
contraddice il sentiment news.
Azione: tratta con estrema cautela, riduci size.

✅ TRIPLE_CONFLUENCE
Quando: tutti e tre i segnali concordano nella stessa direzione.
Significato: massima probabilità statistica di setup valido.
Azione: attendi il segnale tecnico su TradingView,
poi esegui con size standard.

```

**Regola assoluta**: se validation_flags contiene anche solo
un flag rosso, non si opera. Punto.

---

## 8. I Tre Regimi Operativi

Il sistema classifica ogni giornata in uno di tre regimi.
Il regime determina il comportamento operativo per tutta la giornata.

### Regime LONG

**Condizione**: LLM score ≥ +0.9 + tecnici BULLISH (o NEUTRAL)

- nessun flag rosso

```

Cosa significa:
Il contesto informativo e tecnico favorisce i rialzi.
Il vento è alle tue spalle se operi long.

Comportamento operativo:
→ Cerchi SOLO setup long su TradingView
→ Ignori qualsiasi segnale short (anche se si forma)
→ Se non trovi un setup long pulito, stai flat
→ Take Profit puoi allargarlo leggermente (trend favorevole)
→ Stop Loss standard (non ridurlo per "sicurezza")

```

**Esempio tipico**: Fed annuncia pausa sui tassi,
dati occupazione solidi, Polymarket abbassa probabilità recessione.
Tutti i segnali spingono al rialzo → regime LONG.

### Regime SHORT

**Condizione**: LLM score ≤ -0.9 + tecnici BEARISH (o NEUTRAL)

- nessun flag rosso

```

Cosa significa:
Il contesto informativo e tecnico favorisce i ribassi.
Il vento è alle tue spalle se operi short.

Comportamento operativo:
→ Cerchi SOLO setup short su TradingView
→ Ignori qualsiasi segnale long (anche se si forma)
→ Se non trovi un setup short pulito, stai flat
→ Take Profit puoi allargarlo leggermente (trend favorevole)
→ Stop Loss standard

```

**Esempio tipico**: CPI sopra attese, Fed hawkish,
Polymarket alza probabilità recessione, mercati europei
già in rosso. Tutti i segnali spingono al ribasso → regime SHORT.

### Regime NEUTRAL / FLAT

**Condizione**: LLM score tra -0.9 e +0.9, O segnali in conflitto,
O flag rossi presenti

```

Cosa significa:
Non c'è un'informazione direzionale chiara.
Il mercato potrebbe andare in entrambe le direzioni.
Il rischio è alto, il vantaggio è basso.

Comportamento operativo:
→ Nessun trade direzionale
→ Osservazione e studio della struttura
→ Aggiornamento del trade log con "FLAT"
→ Eccezionalmente: solo se si forma un setup
tecnico perfettissimo con RSI estremo
e livello S/R fortissimo

```

**Esempio tipico**: giornata senza dati macro rilevanti,
news miste (alcune positive, alcune negative),
mercati che oscillano senza direzione → regime NEUTRAL.

---

## 9. Tutti i Casi Possibili

### Caso 1 — Triple Confluence SHORT ✅

```

Report:  LLM: -2.5 | Tecnici: BEARISH 75% | Polymarket: BEARISH 67%
Flags:   ✅ TRIPLE_CONFLUENCE
TradingView: EMA20 < EMA50, prezzo sotto VWAP, RSI 58

→ Regime SHORT attivo
→ Attendi EMA20 retest con candela rossa di rigetto
→ Entry short alla chiusura della candela
→ SL sopra massimo candela + ATR×1.5
→ TP = SL×2 (R:R 1:2)
→ Size = 1% del capitale

```

### Caso 2 — Triple Confluence LONG ✅

```

Report:  LLM: +2.0 | Tecnici: BULLISH 100% | Polymarket: BULLISH 71%
Flags:   ✅ TRIPLE_CONFLUENCE
TradingView: EMA20 > EMA50, prezzo sopra VWAP, RSI 52

→ Regime LONG attivo
→ Attendi EMA20 retest con candela verde di conferma
→ Entry long alla chiusura della candela
→ SL sotto minimo candela + ATR×1.5
→ TP = SL×2 (R:R 1:2)
→ Size = 1% del capitale

```

### Caso 3 — Segnale Forte ma Script Silenzioso ⏳

```

Report:  LLM: -2.0 | Tecnici: BEARISH | Polymarket: BEARISH
Flags:   ✅ TRIPLE_CONFLUENCE
TradingView: nessuna freccia SHORT visualizzata

→ Regime SHORT attivo ma entry non disponibile
→ Il prezzo è troppo lontano dall'EMA20, O
RSI già ipervenduto, O struttura non chiara
→ Attendi alert TradingView (già configurato)
→ Non entrare a mercato
→ Non "rincorrere" il trade
→ Se l'entry non arriva oggi → log: FLAT, nessuna perdita

```

### Caso 4 — Conflitto LLM vs Tecnici ❌

```

Report:  LLM: -1.5 (BEARISH) | Tecnici: BULLISH 75%
Flags:   🔴 DIRECTION_CONFLICT

→ Il mercato sta resistendo alla pressione ribassista delle news
→ Possibile inversione in formazione, MA non ancora confermata
→ Nessun trade in nessuna direzione
→ Monitoraggio: se i tecnici si allineano al LLM nelle ore
successive → potenziale setup short nelle prossime sessioni
→ Log: FLAT con nota "direction conflict"

```

### Caso 5 — LLM Allucinazione Rilevata 🔴

```

Report:  LLM: +3 (BULLISH) | Keyword baseline: -1 (BEARISH)
Flags:   🔴 SENTIMENT_MISMATCH

→ L'LLM ha prodotto un output incoerente con le fonti
→ Potrebbe aver sovra-interpretato una notizia positiva
ignorando il quadro generale negativo
→ STOP: leggi manualmente i titoli news nel report
→ Valuta tu stesso il sentiment
→ Se ritieni il quadro negativo: ignora LLM, usa solo tecnici
→ Log: FLAT o operazione solo-tecnica con size ridotta (0.5%)

```

### Caso 6 — Risk Event Imminente ⚠️

```

Report:  LLM: +1 | risk_events: ["Fed FOMC Decision ore 20:00"]
Flags:   nessuno

→ Anche con segnale positivo: NO TRADE prima dell'evento
→ Il mercato può invertire violentemente all'annuncio
→ Se sei già in posizione aperta da prima:
considera di chiuderla PRIMA dell'evento
→ Log: FLAT (risk event)
→ Dopo l'evento: nuovo lancio script per assessment aggiornato

```

### Caso 7 — Script Non Eseguito / Errore ⛔

```

Situazione: lo script ha restituito errori, report non generato

→ STOP ASSOLUTO: nessun trade oggi
→ Il sistema non ha le informazioni per valutare il contesto
→ Non sostituire con "sensazione" o analisi improvvisata
→ Usa Perplexity Pro manualmente per una valutazione rapida
(non equivale al sistema, ma meglio di nulla)
→ Log: FLAT (system error)

```

---

## 10. La Strategia di Entry

### Il Pine Script su TradingView

Il sistema include uno script Pine Script v6 (`tradingview/trading_copilot.pine`)
che visualizza automaticamente sul grafico:

- Le linee EMA20 (blu) ed EMA50 (arancione)
- Il VWAP della sessione
- Frecce LONG/SHORT quando tutte le condizioni tecniche sono soddisfatte
- Diamanti cyan come pre-segnale (struttura pronta, prezzo tocca EMA20)
- Una tabella informativa (22 righe) con: regime, bias, confidenza, quality score,
  EMA, RSI, VWAP, MACD, ATR, session, exit mode, trailing info, distanze SL/TP e R:R
- Le linee di Stop Loss e Take Profit calcolate automaticamente via ATR
- Linea trailing stop dinamica (verde/rossa) che si aggiorna in tempo reale
- Marcatori R-multiple sul grafico (+1R, +2R, +3R...) per tracking visivo
- Deduplicazione segnali: un solo segnale per trend, reset su rottura struttura

### Filtri Aggiuntivi nel Pine Script

Oltre alle condizioni tecniche base, lo script applica tre filtri addizionali:

**Session Filter**: I segnali vengono generati solo durante le finestre ad alto
volume — London open (08:00-09:00 CET) e NYSE open (15:30-16:30 CET). I segnali
nella dead zone (11:00-14:00 CET) vengono bloccati. Le finestre sono configurabili
negli input dello script.

**Quality Score Filter**: Il quality score dal report (0-5) viene inserito
manualmente negli input dello script. Se il QS è sotto la soglia minima
(default 4), i segnali vengono bloccati. QS = 0 disabilita il filtro
(per retrocompatibilità).

**Trailing Stop Engine**: Lo script offre 3 modalità di uscita selezionabili:

1. **Fixed TP** (default): uscita a R:R fisso 1:2
2. **Trailing Stop**: dopo +1R lo SL si sposta a breakeven, dopo +2R lo SL
   trail a +1R dietro il prezzo massimo/minimo raggiunto
3. **Partial + Trail**: 50% della posizione esce a 2R, il restante trail
   con stop ATR-based

La modalità si seleziona dall'input "Exit Mode" nelle impostazioni dello script.

### Entry LONG — Condizioni Tecniche

```

1. EMA20 > EMA50 (trend rialzista strutturale)
2. Prezzo scende e tocca l'EMA20 dal basso (pullback)
3. Una candela chiude SOPRA l'EMA20 (rimbalzo confermato)
4. Prezzo sopra VWAP (forza della sessione)
5. RSI < 70 (non ipercomprato)
6. Bias LLM impostato = BULLISH o NEUTRAL

→ ENTRY: alla chiusura della candela di conferma
→ STOP LOSS: sotto il minimo della candela (- ATR × 1.5)
→ TAKE PROFIT: entry + (distanza SL × 2)

```

### Entry SHORT — Condizioni Tecniche

```

1. EMA20 < EMA50 (trend ribassista strutturale)
2. Prezzo sale e tocca l'EMA20 dall'alto (pullback rialzista)
3. Una candela chiude SOTTO l'EMA20 (rigetto confermato)
4. Prezzo sotto VWAP (debolezza della sessione)
5. RSI > 30 (non ipervenduto)
6. Bias LLM impostato = BEARISH o NEUTRAL

→ ENTRY: alla chiusura della candela di rigetto
→ STOP LOSS: sopra il massimo della candela (+ ATR × 1.5)
→ TAKE PROFIT: entry - (distanza SL × 2)

```

### Impostazione dei Parametri su TradingView

Il collegamento manuale tra il report Python e TradingView:

1. Leggi il report → vedi `directional_bias: BEARISH`
2. Apri TradingView → click sull'ingranaggio del tuo script
3. Campo "Bias LLM" → seleziona `BEARISH`
4. Campo "Quality Score (from report)" → inserisci il QS dell'asset
5. Campo "Exit Mode" → scegli Fixed TP / Trailing / Partial+Trail
6. Lo script filtrerà automaticamente i segnali in base a bias, QS e sessione

Questo passaggio richiede 1 minuto ogni mattina ed è il punto
di integrazione tra il sistema algoritmico e l'analisi tecnica.

---

## 11. Gestione del Rischio

### La Regola dell'1%

**Mai rischiare più dell'1-2% del capitale su un singolo trade.**

Questa non è una preferenza — è la regola matematica che determina
la sopravvivenza nel trading a lungo termine.

```

Esempio con capitale di 5.000€:

Rischio per trade = 1% = 50€

Se lo Stop Loss è a 50 punti e il valore del punto è 1€:
Size = 50€ / (50 punti × 1€/punto) = 1 contratto

Risultato:

- Se SL scatta: perdi 50€ (1% del capitale)
- Se TP raggiunto (R:R 1:2): guadagni 100€ (2% del capitale)

```

Con questa regola, anche una serie di 10 trade perdenti consecutivi
riduce il capitale del 10% — non porta alla rovina.

### Il Risk/Reward Ratio

Il sistema usa un R:R minimo di 1:2: per ogni euro rischiato,
l'obiettivo è guadagnarne due.

La matematica di questa scelta è precisa:

```

Con R:R 1:2:

- Devi avere ragione solo il 34% delle volte per andare in pari
- Con il 50% di accuracy: +50% sul capitale in un anno
- Con il 60% di accuracy: risultati eccezionali

Con R:R 1:1:

- Devi avere ragione il 50% delle volte per andare in pari
- Con il 50% di accuracy: perdi per le commissioni

```

### Stop Loss: Regole Assolute

- **Non spostare mai lo stop loss in perdita** per "dare più spazio"
  al trade. Lo stop loss è il punto in cui il tuo scenario è sbagliato.
  Se il mercato lo raggiunge, lo scenario era sbagliato.
- **Non chiudere il trade in anticipo** se non ha senso tecnico.
  Lasciar correre i vincitori è altrettanto importante che tagliare le perdite.
- **Lo stop loss si calcola sempre prima di entrare**, non dopo.

---

## 12. Key Levels — Supporti e Resistenze

### Perché i Livelli Sono Fondamentali

Un segnale LONG perfetto che punta dritto in una resistenza maggiore è un trade
perdente. Senza conoscere i livelli chiave, il sistema produce segnali tecnicamente
corretti ma operativamente inutili.

I key levels rappresentano zone di prezzo dove il mercato ha storicamente reagito
con forza — sono i punti dove confluiscono ordini istituzionali, stop loss di massa,
e liquidità concentrata.

### Livelli Calcolati

Il sistema calcola automaticamente 5 categorie di livelli:

```

1. Previous Day High / Low / Close (PDH / PDL / PDC)
   Fonte: candela daily precedente da yfinance
   Importanza: livelli più reattivi — il mercato "ricorda" dove è stato ieri

2. Previous Week High / Low (PWH / PWL)
   Fonte: candela weekly precedente
   Importanza: livelli strutturali — break di PWH/PWL indica cambio di regime

3. Pivot Points Classici (PP, R1, R2, S1, S2)
   Formula: PP = (H + L + C) / 3
   R1 = 2×PP - L    R2 = PP + (H - L)
   S1 = 2×PP - H    S2 = PP - (H - L)
   Importanza: usati universalmente da istituzionali e algoritmi

4. Livelli Psicologici Rotondi
   Es. NQ 20000, Gold 3000, EURUSD 1.1000
   Importanza: attraggono ordini retail e istituzionali in massa

5. Distanza % dal Livello Più Vicino
   Calcolo: |prezzo_corrente - livello| / prezzo_corrente × 100
   Regola: entry entro 0.5% di un livello = setup di qualità (+1 al QS)

```

### Come Usarli nel Trading

- **Entry LONG vicino a supporto** (PDL, S1, S2, livello psicologico) → setup ad alta qualità
- **Entry SHORT vicino a resistenza** (PDH, R1, R2, livello psicologico) → setup ad alta qualità
- **Entry LONG verso resistenza** → rischio alto, il prezzo potrebbe rimbalzare
- **Entry SHORT verso supporto** → rischio alto, il prezzo potrebbe rimbalzare

Il report mostra i livelli nella sezione dedicata con distanza % dal prezzo corrente.

---

## 13. Calendario Economico

### Il Problema

L'LLM rileva gli eventi macro *dopo* che appaiono nelle news, ma a quel punto
il movimento è già avvenuto. Serve sapere *prima* della sessione che NFP è alle
14:30 o FOMC alle 20:00.

### Implementazione

Il modulo `modules/economic_calendar.py` recupera il calendario settimanale da
Forex Factory (`https://nfs.faireconomy.media/ff_calendar_thisweek.json`) — gratuito,
nessuna API key richiesta.

### Eventi Monitorati

Solo eventi **HIGH impact** vengono visualizzati:

| Evento | Frequenza | Impatto Tipico |
|--------|-----------|----------------|
| NFP (Non-Farm Payrolls) | Mensile | Spike 50-200 punti su NQ in 5 minuti |
| CPI (Consumer Price Index) | Mensile | Forte impatto su tassi e azioni |
| FOMC Decision | 8 volte/anno | Market-mover principale |
| GDP | Trimestrale | Conferma/smentisce recessione |
| Retail Sales | Mensile | Salute del consumatore USA |
| PMI (Purchasing Managers) | Mensile | Leading indicator economia |

### Regime Override Automatico

**Regola critica**: se un evento high-impact è previsto entro **2 ore**,
il regime viene automaticamente forzato a **NEUTRAL**, indipendentemente
da LLM e tecnici.

```

Esempio:
─────────────────────────────────────────────────────
Ore 13:00: Report dice regime LONG (LLM +2.0, tecnici BULLISH)
Ore 14:30: NFP previsto

→ Il sistema mostra: "FOMC tra 1h 30m — REGIME FORZATO NEUTRAL"
→ Il trader NON opera fino a dopo il dato
→ Dopo NFP: nuovo lancio script per assessment aggiornato
─────────────────────────────────────────────────────

```

### Visualizzazione nel Report

Il report HTML include una sezione dedicata con:
- Tabella eventi del giorno con orario, importanza e countdown
- Alert visivo per eventi imminenti (< 2h)
- Badge "REGIME OVERRIDE" quando il calendario forza NEUTRAL

---

## 14. Multi-Timeframe Alignment

### Il Problema

Analizzare solo il timeframe daily e il 5 minuti lascia un gap: il daily dà il
trend macro, il 5m è rumore. Manca il timeframe intermedio (1H) e quello macro
(Weekly) per confermare che il trend sia coerente su più orizzonti.

### Come Funziona

Il sistema calcola il trend EMA20/EMA50 su tre timeframe:

```

Timeframe    Fonte Dati          Trend Logic
──────────────────────────────────────────────────────
Weekly       yfinance/12Data     EMA20 > EMA50 → BULLISH
                                  EMA20 < EMA50 → BEARISH

Daily        yfinance/12Data     EMA20 > EMA50 → BULLISH
                                  EMA20 < EMA50 → BEARISH

1-Hour       yfinance/12Data     EMA20 > EMA50 → BULLISH
                                  EMA20 < EMA50 → BEARISH

```

### Classificazione Allineamento

```

ALIGNED      Weekly + Daily + 1H concordano      → Segnale forte
PARTIAL      2 su 3 concordano                   → Segnale con cautela
CONFLICTING  Tutti diversi / nessun accordo      → Segnale debole

```

### Impatto sul Composite Score

Quando il MTF alignment è CONFLICTING, il composite score riceve una **penalità**
che riduce la confidenza del segnale tecnico. Un BULLISH con 67% di confidenza
ma MTF CONFLICTING viene degradato, rendendo meno probabile che generi un trade.

### Regola Operativa

**Trade solo quando Weekly + Daily + 1H concordano** (ALIGNED). In caso di
PARTIAL, operare con cautela e size ridotta. In caso di CONFLICTING, preferire
FLAT.

### Visualizzazione nel Report

Il report mostra card per ogni asset con:
- Trend per timeframe (Weekly ↑, Daily ↑, 1H ↓)
- Badge di allineamento (ALIGNED verde, PARTIAL giallo, CONFLICTING rosso)
- Dettaglio EMA20/EMA50 per timeframe

---

## 15. Session Time Filter

### Il Problema

Non tutte le ore sono uguali. Le migliori opportunità sono a London open e NYSE open.
I segnali nella "dead zone" (11:00-14:00 CET) hanno aspettativa negativa per via
della bassa liquidità e del chop.

### Finestre Operative

```

Sessione          Orario (CET)     Qualità     Note
──────────────────────────────────────────────────────
London Open       08:00 - 09:00    ALTA        Volatilità europea, breakout
London Session    09:00 - 11:00    MEDIA       Continuazione trend London
Dead Zone         11:00 - 14:00    BASSA       Chop, bassa liquidità — SKIP
NYSE Pre-market   14:00 - 15:30    MEDIA       Build-up pre-apertura USA
NYSE Open         15:30 - 16:30    ALTA        Massima liquidità e volume
NYSE Session      16:30 - 22:00    MEDIA       Continuazione trend USA

```

### Implementazione

**Pine Script**: lo script filtra i segnali per sessione usando
`hour(time, "Europe/Rome")`. Segnali nella dead zone vengono bloccati.
Le finestre sono configurabili negli input.

**Report**: la sezione Session Filter mostra:
- Sessione corrente (es. "London Session")
- Qualità della sessione (HIGH/MEDIUM/LOW)
- Countdown alla prossima finestra ad alta qualità

### Regola Operativa

Meno trade, ma di qualità superiore. Operare solo durante London Open e NYSE Open
per massimizzare la probabilità di movimenti puliti e direzionali.

---

## 16. Setup Quality Score

### Il Problema

Tutti i segnali vengono trattati come uguali. Un LONG su supporto con ADX 35 e
engulfing bullish vale molto più di un LONG random su EMA touch con ADX 12 nel chop.
Serviva un sistema per quantificare la qualità di ogni setup.

### Come Funziona

Il Quality Score (QS) è un punteggio da **1 a 5** basato su 5 fattori binari
(ciascuno vale +1):

```

Fattore              Condizione                            +1 se
──────────────────────────────────────────────────────────────────
C  Confluenza        4+ indicatori direzionali concordano   ✓
T  Trend Forte       ADX > 25                               ✓
L  Key Level         Entry entro 0.5% di un S/R             ✓
P  Candle Pattern    Engulfing o Pin Bar rilevato            ✓
V  Volume            Volume sopra media 20 giorni            ✓
──────────────────────────────────────────────────────────────────
                                            Totale: 0-5

```

### Candle Pattern Detection

Il sistema rileva automaticamente due pattern:

**Engulfing** (bullish/bearish): l'ultima candela "avvolge" completamente il body
della candela precedente. Indica forte pressione direzionale.

**Pin Bar** (bullish/bearish): candela con wick dominante > 2× il body e > 2× il
wick opposto. Indica rigetto di un livello di prezzo.

### Regola Operativa

```

QS 5  →  Setup perfetto — size standard, alta confidenza
QS 4  →  Setup buono — size standard
QS 3  →  Setup mediocre — SKIP (sotto soglia)
QS 2  →  Setup debole — SKIP
QS 1  →  Setup pessimo — SKIP

Regola assoluta: trade SOLO con QS >= 4

```

### Visualizzazione

- **Report HTML**: colonna QS nella tabella asset con badge colorato e iniziali
  dei fattori attivi (es. "4/5 C+T+L+V"). Sezione dedicata con breakdown per asset.
- **Pine Script**: input "Quality Score (from report)" filtra i segnali sotto la soglia.
- **Trade Log**: il QS viene registrato per analisi post.

---

## 17. Correlation Filter

### Il Problema

NQ e ES hanno correlazione ~0.95. Andare LONG su entrambi raddoppia il rischio
su un singolo trade. Se il segnale è sbagliato, si perde 2% invece di 1%.

### Come Funziona

Il sistema calcola una **matrice di correlazione pairwise** basata sui rendimenti
giornalieri degli ultimi 30 giorni:

```

Calcolo:
1. Per ogni asset: daily_returns = Close.pct_change()
2. Ultimi 30 rendimenti giornalieri
3. Correlazione di Pearson tra tutte le coppie

Esempio matrice:
         NQ=F    ES=F    EURUSD=X   GC=F
NQ=F     1.00    0.95    -0.32      -0.15
ES=F     0.95    1.00    -0.28      -0.12
EURUSD=X -0.32   -0.28   1.00       0.41
GC=F     -0.15   -0.12   0.41       1.00

```

### Regole di Filtro

1. **Soglia**: correlazione > 0.7 tra due asset
2. **Condizione**: entrambi gli asset hanno lo STESSO segnale direzionale
   (entrambi BULLISH o entrambi BEARISH)
3. **Azione**: tra i due asset correlati, il sistema **mantiene** quello
   con Quality Score più alto e **filtra** l'altro
4. **Segnali NEUTRAL**: non vengono mai filtrati

### Esempio Pratico

```

NQ=F: BULLISH, QS=4
ES=F: BULLISH, QS=3
Correlazione NQ-ES: 0.95 (> 0.7)

→ ES=F viene filtrato (QS inferiore)
→ Report mostra "CORR-SKIP" accanto a ES=F
→ Il trader opera solo su NQ=F

```

### Visualizzazione nel Report

- **Heatmap**: tabella con celle colorate (rosso > 0.7, giallo > 0.5, grigio)
- **Warning**: alert quando due asset correlati vanno nella stessa direzione
- **Auto-select**: indicazione di quale asset è stato scelto e quale filtrato

---

## 18. Trailing Stop Engine

### Il Problema

Il R:R fisso 1:2 esce a 2R anche quando il trade potrebbe correre a 5R o 10R.
In mercati trending, uscire troppo presto costa più delle perdite.

### Le 3 Modalità di Uscita

Il Pine Script offre 3 modalità selezionabili dall'input "Exit Mode":

**1. Fixed TP (default)**

```

Entry → SL = -1.5 ATR | TP = +3.0 ATR (R:R 1:2)
Comportamento: uscita automatica al raggiungimento del TP.
Quando usarlo: mercati in range, movimenti contenuti.

```

**2. Trailing Stop**

```

Entry → SL iniziale = -1.5 ATR
Dopo +1R: SL si sposta a breakeven (zero risk)
Dopo +2R: SL trail a +1R dietro il massimo/minimo raggiunto
Il trade rimane aperto finché il prezzo non ritraccia fino allo SL trailing.

Quando usarlo: mercati trending con movimenti estesi.
Vantaggio: cattura 5-10R sui trend forti, zero risk dopo +1R.

```

**3. Partial + Trail**

```

Entry → SL iniziale = -1.5 ATR
A +2R: chiudi 50% della posizione (profitto assicurato)
Restante 50%: trail con stop ATR-based dietro il prezzo.

Quando usarlo: incertezza sulla durata del trend.
Vantaggio: combina profitto sicuro con upside illimitato.

```

### Visualizzazione sul Grafico

- **Linea trailing stop dinamica**: verde per LONG, rossa per SHORT, si aggiorna
  candela per candela
- **Marcatori R-multiple**: label "+1R", "+2R", "+3R" sul grafico per tracking visivo
- **Alert**: notifica quando lo SL si sposta a breakeven e quando il trade viene chiuso

### Impatto sulla Performance

Con win-rate 50% e trailing stop, il profit factor passa da ~1.5x (fixed TP) a ~2.5x.
I pochi trade che corrono 5-10R compensano molte piccole perdite da -1R.

---

## 19. Il Report Giornaliero

### Struttura del Report HTML

Il sistema genera automaticamente un report HTML consultabile
nel browser, organizzato in queste sezioni:

**1. Header**
Data, ora di generazione, sessione di mercato corrente
(pre-market / regular / after-hours calcolato automaticamente
in base al fuso orario italiano).

**2. Sentiment LLM**
Grande card colorata con:

- Score numerico (-3 a +3) con gradiente cromatico
- Label testuale (es. "Moderatamente ribassista")
- Confidence dell'LLM

**3. Polymarket Signal**
Card con segnale predittivo:

- Signal (BULLISH/BEARISH/NEUTRAL) con confidence %
- Barra di confidenza visiva
- Tabella dei top 5 mercati con probabilità e volumi

**4. Confluenza Box**
Evidenziazione colorata del livello di accordo tra i segnali:

- Verde: Triple Confluence
- Arancione: Conflitto rilevato
- Grigio: Segnale neutro

**5. Key Drivers**
I 3 fattori principali che guidano il sentiment oggi,
estratti dall'LLM.

**6. Risk Events**
Box di allerta se ci sono eventi macro nelle prossime ore
(dati Fed, CPI, NFP, earnings, ecc.)

**7. Calendario Economico**
Tabella eventi high-impact del giorno con orario, importanza e countdown.
Alert visivo per eventi imminenti (< 2h) e badge "REGIME OVERRIDE" se attivo.

**8. Session Filter**
Sessione corrente (London/NYSE/Dead Zone), qualità (HIGH/MEDIUM/LOW),
e countdown alla prossima finestra ad alta qualità.

**9. Tabella Asset (15 colonne)**
Una riga per ogni asset configurato, con 15 colonne:

- Prezzo corrente e variazione %
- RSI (valore + label), MACD (label), Bollinger Bands (label + dettaglio),
  Stochastic (%K + label), posizione vs VWAP, EMA Trend, ADX (forza trend)
- Score tecnico composito (6 indicatori direzionali)
- MTF Alignment (ALIGNED/PARTIAL/CONFLICTING)
- Quality Score (1-5) con badge fattori attivi
- Bias LLM per-asset
- Segnale Polymarket
- Hint operativo (LONG / SHORT / Wait / Conflict / CORR-SKIP)
- Badge "via twelvedata" se il fallback è stato usato

**10. Multi-Timeframe Alignment**
Card per ogni asset con trend EMA20/50 su Weekly, Daily e 1H.
Badge di allineamento colorato.

**11. Quality Score Breakdown**
Card per ogni asset con i 5 fattori (C+T+L+P+V) e badge
TRADEABLE (QS >= 4) o SKIP (QS < 4).

**12. Matrice Correlazione**
Heatmap pairwise con celle colorate (rosso > 0.7, giallo > 0.5).
Warning per coppie correlate con same-direction e nota CORR-SKIP.

**13. Key Levels**
Per ogni asset: PDH/PDL/PDC, PWH/PWL, Pivot Points (PP, R1, R2, S1, S2),
livelli psicologici con distanza % dal prezzo corrente.

**14. News Raw (collassabile)**
Tutti i titoli di notizie aggregati con fonte e orario,
per verifica manuale anti-allucinazione.

**15. Footer**
Disclaimer legale obbligatorio.

---

## 20. Routine Operativa Quotidiana

### Orario Consigliato (fuso orario italiano, ora legale)

```

07:30  Lettura rapida news finanziarie (Perplexity Pro, 5 min)
Contestualizzazione manuale del quadro macro del giorno

08:00  Script Python gira automaticamente (cron/scheduler)
Report disponibile in reports/

08:10  Lettura report:
→ Verifica validation_flags (flag rossi = stop)
→ Controlla calendario economico (eventi HIGH nelle prossime ore?)
→ Verifica sessione corrente (London/NYSE/Dead Zone)
→ Leggi 3-5 titoli news manualmente (anti-allucinazione)
→ Determina il Regime del giorno (LONG / SHORT / FLAT)
→ Controlla Quality Score per ogni asset (solo QS >= 4)
→ Controlla matrice correlazione (no same-direction su asset correlati)
→ Imposta bias LLM + Quality Score su TradingView

08:15  TradingView:
→ Analizza struttura grafico (S/R, EMA, VWAP, Key Levels dal report)
→ Seleziona Exit Mode (Fixed TP / Trailing / Partial+Trail)
→ Attiva alert per segnale Pine Script
→ Poi chiudi TradingView e fai altro

14:00  Secondo lancio script (pre-mercato USA)
→ Aggiornamento news ultime 6 ore
→ Possibile cambio di regime se arrivano news importanti
→ Aggiorna bias LLM su TradingView se necessario

14:30  Mercato USA pre-market:
→ TradingView aperto, in attesa segnale
→ Massima attenzione ai primi 30 minuti di sessione

Al segnale:
→ Apri report → checklist → Fineco → entry

Fine giornata:
→ Compila trade_log.csv (2 minuti)
→ Nota mentale su cosa ha funzionato e cosa no

```

### La Checklist Pre-Entry (Stampabile)

```

╔══════════════════════════════════════════════════════════╗
║         CHECKLIST PRE-ENTRY — Trading Assistant v4.1      ║
╠══════════════════════════════════════════════════════════╣
║  □ Script eseguito senza errori oggi?                      ║
║  □ validation_flags è vuoto nel report?                    ║
║  □ Nessun evento HIGH nel calendario entro 2 ore?          ║
║  □ Sessione corrente è HIGH quality (London/NYSE open)?    ║
║  □ Ho letto 3+ titoli news manualmente?                    ║
║  □ Sentiment LLM coerente con quello che ho letto?         ║
║  □ Tecnici e LLM concordano sulla direzione?               ║
║  □ MTF Alignment è ALIGNED (Weekly+Daily+1H)?              ║
║  □ Quality Score >= 4 per questo asset?                    ║
║  □ Asset non filtrato dalla matrice correlazione?          ║
║  □ Ho identificato il livello di entry sul grafico?        ║
║  □ Entry vicino a key level (PDH/PDL, Pivot, psicologico)?║
║  □ Ho calcolato Stop Loss (in punti)?                      ║
║  □ Ho calcolato Take Profit / selezionato exit mode?       ║
║  □ Ho calcolato la size (max 1% del capitale)?             ║
╠══════════════════════════════════════════════════════════╣
║  SE ANCHE SOLO 1 RISPOSTA È NO → NON ENTRARE              ║
╚══════════════════════════════════════════════════════════╝

```

---

## 21. Validazione e Miglioramento Continuo

### Il Trade Log

Ogni operazione — incluse le giornate flat — può essere registrata
automaticamente nel file `trade_log.csv` tramite il flag `--log-trade`:

```bash
# Registra l'analisi odierna come trade
python main.py --log-trade

# Rivedi le statistiche di accuracy
python main.py --review-trades
```

Struttura del file `trade_log.csv`:

```

Colonne:
date          | Data del trade (YYYY-MM-DD)
asset         | Es. NAS100, EURUSD
llm_score     | Score sentiment dal report (-3 a +3)
tech_signal   | BULLISH / BEARISH / NEUTRAL
poly_signal   | BULLISH / BEARISH / NEUTRAL
direction     | LONG / SHORT / FLAT
quality_score | Quality Score 0-5 (0 se non disponibile)
entry_price   | Prezzo di entrata (0 se FLAT)
exit_price    | Prezzo di uscita (0 se FLAT)
outcome_pips  | Punti guadagnati/persi (0 se FLAT)
llm_correct   | TRUE / FALSE / N/A (se FLAT)
notes         | Note libere

```

### Analisi della Performance

Dopo 30 trade è possibile calcolare metriche significative:

```python
# Accuracy del segnale LLM
accuracy = df[df.direction != 'FLAT']['llm_correct'].mean() * 100

# Interpretazione:
# < 50%  → disabilita LLM, usa solo tecnici
# 50-55% → marginal, ottimizza prompt e parametri
# 55-60% → accettabile, usa come filtro secondario
# > 60%  → ottimo, il sistema funziona bene
```

### Ciclo di Miglioramento

Il sistema migliora iterativamente seguendo questo ciclo:

```
Osserva (trade log) → Analizza (accuracy per asset, per ora, per regime)
      ↑                              ↓
   Monitora          Identifica pattern di errore
      ↑                              ↓
   Implementa  ←   Modifica (prompt, parametri, soglie)
```

---

## 22. Limitazioni e Rischi del Sistema

### Limitazioni Tecniche

**Latenza delle news**: i feed RSS aggiornano con ritardi variabili
(da secondi a minuti). Per trading ultra-intraday (< 1 minuto)
questo sistema non è adatto. È ottimizzato per timeframe da 15 minuti
in su.

**Qualità del modello LLM**: Llama 3.3 70B è un ottimo modello generalista
ma non è stato specificamente fine-tuned su dati finanziari come
FinBERT o BloombergGPT. Il sistema implementa un fallback su FinBERT
in caso di errore, ma le prestazioni possono variare.

**Liquidità Polymarket**: mercati con volume < \$10.000 producono
probabilità inaffidabili (pochi partecipanti = alta volatilità
nelle probabilità). Il sistema filtra automaticamente questi mercati.

### Limitazioni Operative

**Non automatizza l'esecuzione**: l'entry, lo stop e il take profit
vengono inseriti manualmente su Fineco. Questo introduce latenza
e possibilità di errore umano al momento dell'esecuzione.

**Il bias LLM va impostato manualmente su TradingView**: questo
passaggio richiede disciplina quotidiana e può essere dimenticato.

**Backtest non equivale a live trading**: i risultati del backtest
storico nel Strategy Tester di TradingView non tengono conto di
slippage reale, spread Fineco, e discipline psicologica.

### Il Rischio Principale: La Psicologia

Il sistema può essere perfettamente calibrato e comunque produrre
perdite se il trader:

- Ignora la checklist "solo per questa volta"
- Sposta lo stop loss in perdita
- Aumenta la size dopo una serie vincente (overconfidence)
- Riduce la size dopo una serie perdente (fear)
- Opera in regime NEUTRAL per noia o FOMO

La tecnologia risolve il problema informativo.
La disciplina è responsabilità esclusiva del trader.

---

_Trading Assistant v4.1 — Documentazione interna_
_Sviluppato per uso personale. Non distribuire senza autorizzazione._
_Nessuna parte di questo documento costituisce consulenza finanziaria._
