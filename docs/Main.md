# Trading Copilot — Manuale Operativo Completo

### Un sistema algoritmico multi-segnale per CFD su mercati finanziari

**Versione 2.0 — Marzo 2026**

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
12. [Il Report Giornaliero](#12-il-report-giornaliero)
13. [Routine Operativa Quotidiana](#13-routine-operativa-quotidiana)
14. [Validazione e Miglioramento Continuo](#14-validazione-e-miglioramento-continuo)
15. [Limitazioni e Rischi del Sistema](#15-limitazioni-e-rischi-del-sistema)

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
║  └─────────────┘  └─────────────┘  └──────────┘  └────────┘ ║
║         │                │               │            │       ║
║         └────────────────┴───────────────┴────────────┘       ║
║                                   │                           ║
║                     ┌─────────────▼──────────────┐           ║
║                     │   MOTORE DI CONFLUENZA      │           ║
║                     │   Hallucination Guard       │           ║
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
- **Retry con backoff**: Tutti i componenti di I/O (RSS, yfinance, Polymarket API)
  implementano retry con backoff esponenziale (3 tentativi, base 2s).
- **Progress bar**: `tqdm` mostra lo stato di avanzamento durante il fetch parallelo.
- **Trade Log**: Il sistema registra i trade in `trade_log.csv` e fornisce
  statistiche di accuracy dopo 30+ trade direzionali (flag `--log-trade`, `--review-trades`).
- **Fuso orario italiano**: Report e terminal summary mostrano l'ora italiana (Europe/Rome).

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

### Perché Servono i Tecnici se Abbiamo l'LLM

L'LLM analizza il **perché** il mercato potrebbe muoversi (notizie, contesto).
Gli indicatori tecnici analizzano il **come** si sta muovendo effettivamente
(prezzi, volumi, momentum). Sono informazioni complementari, non alternative.

Un bias LLM bearish su news macro + un trend tecnico ancora rialzista
significa che il mercato sta resistendo alla pressione — segnale di
possibile inversione imminente, ma non ancora confermata. In questo caso
si aspetta prima di operare.

### Gli Indicatori Utilizzati

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

### Il Punteggio Tecnico Composito

Il sistema combina tutti gli indicatori in un unico score:

```

Indicatore    Condizione Bullish           Peso
──────────────────────────────────────────────
EMA20/50      EMA20 > EMA50               +1
VWAP          Prezzo > VWAP               +1
RSI           30 < RSI < 70 + trending    +1
MACD          Signal bullish crossover    +1
──────────────────────────────────────────────
Score 3-4/4  → BULLISH  (75-100% confidence)
Score 2/4    → NEUTRAL  (50% confidence)
Score 0-1/4  → BEARISH  (75-100% confidence)

```

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

1. **Recupero con paginazione e tag**: il sistema interroga l'API Gamma
   di Polymarket utilizzando tag di categoria specifici per gli asset
   configurati (es. `economics`, `politics` per NAS100/S&P500).
   Per ciascun tag, recupera fino a 300 mercati (3 pagine da 100),
   ordinati per volume decrescente. I mercati duplicati tra tag
   diversi vengono automaticamente deduplicati.

2. **Filtro per keyword e volume**: i mercati recuperati vengono filtrati
   client-side per parole chiave rilevanti (es. "fed", "recession",
   "inflation" per NAS100; "ecb", "euro" per EURUSD; ecc.) e per
   volume minimo > $10.000. Mercati illiquidi vengono esclusi
   perché le probabilità con pochi partecipanti sono inaffidabili.

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

Architettura del modulo Polymarket:
════════════════════════════════════════════════════════════

  Asset configurati (config.yaml)
         │
         ▼
  ┌─────────────────────┐
  │ _get_tags_for_assets │ → tag API: ["economics", "politics"]
  │ _get_keywords        │ → keyword client: ["fed", "recession", ...]
  └─────────────────────┘
         │
         ▼
  ┌─────────────────────┐
  │   fetch_markets()    │ → API Gamma con paginazione (fino a 300/tag)
  │   + dedup + filtro   │ → keyword match + volume > $10K
  └─────────────────────┘
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

Il sistema include uno script Pine Script (TradingView) che
visualizza automaticamente sul grafico:

- Le linee EMA20 (arancione) ed EMA50 (blu)
- Il VWAP della sessione (bianco)
- Lo sfondo verde (trend rialzista) o rosso (ribassista)
- Frecce LONG/SHORT quando tutte le condizioni tecniche sono soddisfatte
- Una tabella con RSI, ATR, score tecnico e bias LLM impostato manualmente
- Le linee di Stop Loss e Take Profit calcolate automaticamente via ATR

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

### Impostazione del Bias LLM su TradingView

Il collegamento manuale tra il report Python e TradingView:

1. Leggi il report → vedi `directional_bias: BEARISH`
2. Apri TradingView → click sull'ingranaggio del tuo script
3. Campo "Bias LLM" → seleziona `BEARISH`
4. Lo script filtrerà automaticamente i segnali LONG,
   mostrando solo frecce SHORT

Questo passaggio richiede 30 secondi ogni mattina ed è il punto
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

## 12. Il Report Giornaliero

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

**7. Tabella Asset**
Una riga per ogni asset configurato, con:

- Prezzo corrente
- RSI, MACD signal, posizione vs VWAP
- Score tecnico composito
- Bias LLM
- Segnale Polymarket
- Hint operativo

**8. News Raw (collassabile)**
Tutti i titoli di notizie aggregati con fonte e orario,
per verifica manuale anti-allucinazione.

**9. Footer**
Disclaimer legale obbligatorio.

---

## 13. Routine Operativa Quotidiana

### Orario Consigliato (fuso orario italiano, ora legale)

```

07:30  Lettura rapida news finanziarie (Perplexity Pro, 5 min)
Contestualizzazione manuale del quadro macro del giorno

08:00  Script Python gira automaticamente (cron/scheduler)
Report disponibile in reports/

08:10  Lettura report:
→ Verifica validation_flags (flag rossi = stop)
→ Leggi 3-5 titoli news manualmente (anti-allucinazione)
→ Determina il Regime del giorno (LONG / SHORT / FLAT)
→ Imposta bias LLM su TradingView

08:15  TradingView:
→ Analizza struttura grafico (S/R, EMA, VWAP)
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

╔═══════════════════════════════════════════════════╗
║         CHECKLIST PRE-ENTRY — Trading Assistant    ║
╠═══════════════════════════════════════════════════╣
║  □ Script eseguito senza errori oggi?              ║
║  □ validation_flags è vuoto nel report?            ║
║  □ Ho letto 3+ titoli news manualmente?            ║
║  □ Sentiment LLM coerente con quello che ho letto? ║
║  □ Tecnici e LLM concordano sulla direzione?       ║
║  □ Nessun risk event nelle prossime 4 ore?         ║
║  □ Ho identificato il livello di entry sul grafico?║
║  □ Ho calcolato Stop Loss (in punti)?              ║
║  □ Ho calcolato Take Profit (min R:R 1:2)?         ║
║  □ Ho calcolato la size (max 1% del capitale)?     ║
╠═══════════════════════════════════════════════════╣
║  SE ANCHE SOLO 1 RISPOSTA È NO → NON ENTRARE      ║
╚═══════════════════════════════════════════════════╝

```

---

## 14. Validazione e Miglioramento Continuo

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

## 15. Limitazioni e Rischi del Sistema

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

_Trading Assistant v2.0 — Documentazione interna_
_Sviluppato per uso personale. Non distribuire senza autorizzazione._
_Nessuna parte di questo documento costituisce consulenza finanziaria._
