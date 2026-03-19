# Guida al Testing — Trading Assistant

Questa guida copre sia i test automatizzati sia le verifiche manuali necessarie
per validare la qualita' del sistema prima di usarlo per il trading reale.

---

## 1. Test Automatizzati

### Come eseguire

```bash
# Linux / macOS
./run_tests.sh

# Windows
run_tests.bat

# Oppure manualmente
python -m pytest tests/ -v --tb=short --cov=modules --cov-report=term-missing
```

### Cosa viene testato

| Modulo | File di test | Cosa verifica |
|--------|-------------|---------------|
| news_fetcher | test_news_fetcher.py | Parsing RSS, filtro temporale, deduplicazione, retry di rete |
| price_data | test_price_data.py | Calcolo indicatori, range RSI, score composito, gestione errori |
| sentiment | test_sentiment.py | Parsing risposta Groq, range score, fallback FinBERT, retry rate limit |
| report | test_report.py | Creazione file, HTML valido, sezioni presenti, colori, disclaimer |
| hallucination_guard | test_hallucination_guard.py | Mismatch sentiment, conflitto direzione, score estremi |
| integrazione | test_integration.py | Pipeline completo end-to-end con tutti gli external mockati |

### Come leggere il coverage report

Dopo l'esecuzione vedrai un output simile a:

```
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
modules/news_fetcher.py              85     12    86%   45-48, 92
modules/price_data.py               142     18    87%   ...
modules/sentiment.py                120      8    93%   ...
modules/report.py                    95      5    95%   ...
modules/hallucination_guard.py       62      3    95%   ...
---------------------------------------------------------------
TOTAL                               504     46    91%
```

- **Stmts**: righe di codice eseguibili
- **Miss**: righe non coperte dai test
- **Cover**: percentuale di copertura
- **Missing**: numeri delle righe non coperte

**Soglia minima accettabile: 80%**. Se la copertura scende sotto l'80% per un modulo,
aggiungi test per le righe mancanti prima di usare il sistema in produzione.

### Eseguire un singolo file di test

```bash
python -m pytest tests/test_sentiment.py -v
```

### Eseguire un singolo test

```bash
python -m pytest tests/test_sentiment.py::TestValidGroqResponse::test_valid_response_parsed -v
```

---

## 2. Test Manuale: Qualita' del Sentiment LLM

Questi test richiedono la tua valutazione personale e servono a verificare che
il modello LLM produca analisi di sentiment coerenti.

### Procedura

1. **Raccogli un batch di 10 notizie reali**
   - Vai su [Yahoo Finance](https://finance.yahoo.com/) o apri il feed RSS nel browser
   - Copia 10 titoli di notizie recenti (ultime 24h)
   - Scegli un mix: notizie su azioni, macro, forex, commodities

2. **Etichetta manualmente ogni notizia**

   Crea un file `test_batch.csv` con questa struttura:

   ```csv
   titolo,la_mia_etichetta
   "Fed raises rates by 25bps amid inflation concerns",bearish
   "Tech earnings beat expectations across the board",bullish
   "Markets await jobless claims data",neutral
   ...
   ```

   Regole per l'etichettatura:
   - **bullish**: la notizia e' chiaramente positiva per i mercati
   - **bearish**: la notizia e' chiaramente negativa
   - **neutral**: non ha un chiaro impatto direzionale

3. **Esegui l'analisi LLM sul batch**

   ```bash
   python main.py --hours 24
   ```

   Apri il report e confronta il sentiment LLM con le tue etichette.

4. **Calcola l'agreement**

   ```
   Agreement = notizie dove concordi con LLM / totale notizie * 100
   ```

5. **Soglia di accettazione**

   | Agreement | Valutazione |
   |-----------|-------------|
   | >= 70% | Qualita' accettabile |
   | 50-70% | Marginal — migliora il prompt |
   | < 50% | Non affidabile — non usare per il trading |

6. **Se sotto soglia, prova queste modifiche al prompt** (in `modules/sentiment.py`):
   - Aggiungi esempi concreti nella system message
   - Specifica il contesto di mercato attuale
   - Riduci la temperatura da 0.3 a 0.1
   - Prova un modello diverso (es. `llama-3.1-8b-instant` per confronto)

---

## 3. Test Manuale: Verifica Anti-Allucinazione

Questo e' il test piu' importante. Le allucinazioni del LLM possono portare a
decisioni di trading basate su informazioni false.

### Procedura (prime 2 settimane di uso)

Ogni giorno, dopo aver eseguito lo script:

1. **Leggi TUTTE le notizie** nella sezione "Notizie Raw" del report
2. **Leggi l'analisi LLM** (sentiment, key drivers, risk events)
3. **Confronta**: l'analisi LLM riflette quello che hai letto nelle notizie?

### Checklist Red Flags (stampa e tieni sulla scrivania)

Segna con una X ogni anomalia che trovi:

```
[ ] Il LLM cita un'azienda o un evento NON presente in nessun titolo di notizia
    Esempio: "Apple ha riportato utili record" ma nessuna notizia menziona Apple

[ ] Il LLM assegna score +3 o -3 ma le notizie sono prevalentemente neutre
    Esempio: news su dati economici di routine, score -3

[ ] Il LLM menziona un evento specifico (earnings, riunione Fed, CPI)
    che NON appare nei feed RSS di oggi
    Esempio: "La Fed ha tagliato i tassi" ma nessuna notizia lo riporta

[ ] I key_drivers usano linguaggio vago senza fonte concreta
    Esempio: "I mercati sono incerti per vari fattori macro"
    Invece di: "Dati occupazione USA sotto le attese (fonte: Yahoo Finance)"

[ ] Il directional_bias contraddice TUTTI gli indicatori tecnici
    contemporaneamente (RSI, MACD, EMA tutti in una direzione,
    LLM nella direzione opposta)
```

### Come agire

- **1 red flag**: annota e monitora nei giorni successivi
- **2+ red flags nello stesso report**: NON usare quel report per il trading
- **Red flags ricorrenti (3+ giorni di fila)**: modifica il prompt o cambia modello

### Il modulo hallucination_guard

Il sistema include un modulo automatico (`modules/hallucination_guard.py`) che
rileva alcune di queste incongruenze. Controlla il campo `validation_flags` nel
report. Se non e' vuoto, approfondisci PRIMA di tradare.

---

## 4. Validazione Statistica del Segnale (Trade Log)

Dopo le prime 2 settimane di verifica manuale, inizia a tracciare i risultati
dei tuoi trade per validare statisticamente il segnale.

### Struttura del Trade Log

Crea un file `trade_log.csv` con queste colonne esatte:

```csv
date,asset,llm_score,tech_signal,direction_taken,entry_price,exit_price,outcome_pips,llm_was_correct
2026-03-18,NQ=F,1.5,BULLISH,LONG,21450.00,21520.00,70,true
2026-03-18,EURUSD=X,-1.0,BEARISH,SHORT,1.0850,1.0820,30,true
2026-03-19,GC=F,2.0,NEUTRAL,LONG,2350.00,2340.00,-100,false
```

### Colonne

| Colonna | Descrizione |
|---------|-------------|
| date | Data del trade (YYYY-MM-DD) |
| asset | Simbolo dell'asset tradato |
| llm_score | Score del sentiment LLM al momento del trade |
| tech_signal | Score tecnico al momento (BULLISH/BEARISH/NEUTRAL) |
| direction_taken | Direzione del trade (LONG/SHORT) |
| entry_price | Prezzo di ingresso |
| exit_price | Prezzo di uscita |
| outcome_pips | Risultato in pips/punti (positivo = profitto) |
| llm_was_correct | Il bias LLM era coerente col risultato? (true/false) |

### Come calcolare l'accuratezza

Dopo almeno 30 trade:

```
Accuratezza = trade_corretti / trade_totali * 100
```

Dove `trade_corretti` = numero di righe con `llm_was_correct = true`

### Tabella di interpretazione

| Accuratezza | Valutazione | Azione |
|-------------|-------------|--------|
| < 50% | Il segnale e' peggio del caso | Disabilita il LLM (`--no-llm`), usa solo indicatori tecnici |
| 50 - 55% | Marginale | Aumenta `lookback_hours` nel config, prova un modello Groq diverso |
| 55 - 60% | Accettabile | Usa il segnale LLM come filtro secondario, non come segnale primario |
| > 60% | Ottimo | Puoi aumentare il peso del segnale LLM nelle tue decisioni |

### Note importanti
- 30 trade e' il **minimo** per una valutazione statistica significativa
- Rivaluta l'accuratezza ogni 50 trade
- Se il mercato cambia regime (es. da trending a ranging), resetta il conteggio
- Non includere trade dove hai ignorato il segnale del sistema

---

## 5. Test di Stabilita' del Prompt

Il LLM deve dare risposte consistenti per lo stesso input. Se lo stesso batch
di notizie produce risultati molto diversi, il segnale non e' affidabile.

### Procedura

1. **Salva un batch di notizie** in un file (o usa il report di ieri)

2. **Esegui lo script 5 volte** con lo stesso input:

   ```bash
   for i in 1 2 3 4 5; do
       python main.py --no-browser 2>/dev/null
       echo "Run $i completato"
       sleep 5  # Evita rate limiting
   done
   ```

3. **Registra il sentiment_score** di ogni esecuzione:

   ```
   Run 1: +1.5
   Run 2: +1.0
   Run 3: +2.0
   Run 4: +1.5
   Run 5: +1.0
   ```

4. **Calcola la varianza**: differenza tra il valore massimo e il minimo

   ```
   Varianza = max - min = 2.0 - 1.0 = 1.0
   ```

5. **Soglia accettabile**: varianza <= 1.0 punto

### Se la varianza e' troppo alta (> 1.0)

Modifica il file `modules/sentiment.py`:

1. Riduci la `temperature` a `0.1` (riga nella funzione `_analyze_with_groq`)
2. Aggiungi al system message:
   ```
   "Rispondi SEMPRE con JSON valido. Non variare il formato. Sii consistente nelle valutazioni."
   ```
3. Riesegui il test di stabilita'

---

## 6. Checklist Pre-Trading Giornaliera

**Stampa questa checklist e compilala ogni mattina PRIMA di aprire Fineco.**

```
DATA: _______________

PRE-TRADING CHECKLIST
=====================

[ ] Script eseguito senza errori nel log?
    (controlla trading_assistant.log per WARNING o ERROR)

[ ] validation_flags vuoto nel report?
    (se non vuoto, quale flag? _______________)

[ ] Sentiment LLM coerente con i titoli delle news che ho letto?
    (ho letto almeno i primi 5 titoli nel report)

[ ] Score tecnico e bias LLM concordano (stessa direzione)?
    (tecnici: _______ LLM: _______)

[ ] Nessun risk_event critico nelle prossime 4 ore?
    (eventi: _______________)

[ ] Ho verificato manualmente almeno 3 titoli news nel report?
    (i titoli corrispondono a notizie reali che trovo online)


RISULTATO
=========
Tutti SI  →  Posso procedere con il trading
Anche solo 1 NO  →  NON tradare, approfondisci prima

Note: ________________________________________________
      ________________________________________________
```

### Quando compilare la checklist

- **Mercati USA**: prima delle 15:30 ora italiana (apertura NYSE)
- **Futures**: prima delle 09:00 ora italiana
- **Forex**: in qualsiasi momento, ma preferibilmente prima dell'apertura di Londra (09:00 CET)

---

## 7. Strumenti Utili (tutti gratuiti)

### Per i test automatizzati

| Strumento | Descrizione | Link |
|-----------|-------------|------|
| **pytest** | Framework di testing Python | https://docs.pytest.org/ |
| **pytest-cov** | Plugin per il coverage report | https://pytest-cov.readthedocs.io/ |
| **pytest-mock** | Wrapper di unittest.mock per pytest | https://pytest-mock.readthedocs.io/ |
| **hypothesis** | Property-based testing per edge cases | https://hypothesis.readthedocs.io/ |

### Per la validazione del LLM

| Strumento | Descrizione | Link |
|-----------|-------------|------|
| **DeepEval** | Framework di valutazione LLM (free tier) | https://docs.confident-ai.com/ |

DeepEval puo' essere usato per automatizzare i test di qualita' del sentiment:

```bash
pip install deepeval
```

```python
from deepeval.metrics import HallucinationMetric
# Vedi documentazione per configurazione completa
```

### Template Trade Log

Copia e incolla questo template per iniziare il tuo `trade_log.csv`:

```csv
date,asset,llm_score,tech_signal,direction_taken,entry_price,exit_price,outcome_pips,llm_was_correct
```

Puoi aprirlo con Excel, Google Sheets, o qualsiasi editor di testo.

### Per installare le dipendenze di test

```bash
pip install pytest pytest-cov pytest-mock
```

Queste dipendenze NON sono nel `requirements.txt` principale perche' servono
solo per lo sviluppo, non per l'uso quotidiano.

---

## Riepilogo

| Tipo di test | Frequenza | Chi lo fa |
|-------------|-----------|-----------|
| Test automatizzati | Ad ogni modifica del codice | Il computer (./run_tests.sh) |
| Qualita' sentiment LLM | 1 volta alla settimana | Tu, manualmente |
| Verifica anti-allucinazione | Ogni giorno (prime 2 settimane) | Tu, leggendo il report |
| Trade log statistico | Dopo ogni trade | Tu, aggiornando il CSV |
| Stabilita' prompt | Dopo ogni modifica al prompt | Tu, con 5 esecuzioni |
| Checklist pre-trading | Ogni mattina prima di tradare | Tu, con la checklist stampata |
