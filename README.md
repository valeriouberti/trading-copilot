# Trading Copilot

Sistema di analisi pre-market per trader CFD retail. Genera report giornalieri con analisi tecnica, sentiment macro e notizie aggregate — tutto a costo zero (serve solo una API key Groq gratuita).

Pensato per chi opera manualmente su **Fineco** e usa **TradingView** per i grafici.

---

## Prerequisiti

- Python 3.10 o superiore
- Una API key gratuita di [Groq](https://console.groq.com/) (opzionale ma consigliata)

---

## Setup

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

### 3. Configura la API key di Groq

Registrati su [console.groq.com](https://console.groq.com/) e crea una API key gratuita.

```bash
export GROQ_API_KEY="gsk_la_tua_chiave_qui"  # Linux/macOS
# oppure: set GROQ_API_KEY=gsk_la_tua_chiave_qui  # Windows CMD
# oppure: $env:GROQ_API_KEY="gsk_la_tua_chiave_qui"  # Windows PowerShell
```

Per renderla permanente, aggiungila al tuo `.bashrc`, `.zshrc` o profilo di sistema.

> **Nota:** Se non imposti la chiave Groq, il sistema usa automaticamente FinBERT come fallback (richiede il download del modello al primo avvio, circa 400MB).

---

## Come Usare

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

## Come Interpretare il Report

### Sentiment Macro (-3 a +3)

- **+2 / +3**: Mercato fortemente rialzista — cercare opportunita' LONG
- **+1**: Moderatamente positivo — bias LONG con cautela
- **0**: Neutro — nessuna direzione chiara
- **-1**: Moderatamente negativo — bias SHORT con cautela
- **-2 / -3**: Mercato fortemente ribassista — cercare opportunita' SHORT

### Tabella Assets

- **RSI**: Sotto 30 = ipervenduto (potenziale rimbalzo), Sopra 70 = ipercomprato (potenziale correzione)
- **MACD**: Crossover rialzista/ribassista indica cambio di momentum
- **vs VWAP**: Prezzo sopra VWAP = forza, sotto = debolezza intraday
- **EMA Trend**: EMA20 > EMA50 = trend rialzista, viceversa ribassista
- **Score Tecnico**: Media dei segnali — BULLISH/BEARISH/NEUTRAL con % di confidenza
- **Azione**: Suggerimento sintetico basato su tecnici + sentiment

### Suggerimento per il trading

1. Se Score Tecnico e LLM Bias concordano → segnale piu' affidabile
2. Se sono in conflitto → massima cautela, meglio attendere
3. Usa sempre il report come **punto di partenza**, poi verifica su TradingView

---

## Aggiungere Nuovi Asset

Modifica `config.yaml`:

```yaml
assets:
  - symbol: "NQ=F"
    display_name: "NASDAQ 100 Futures"
  - symbol: "CL=F" # Aggiungi qui
    display_name: "Crude Oil" # Nome che apparira' nel report
```

I simboli seguono la convenzione Yahoo Finance:

- Futures: `ES=F`, `NQ=F`, `GC=F`, `CL=F`
- Forex: `EURUSD=X`, `GBPUSD=X`
- Indici: `^GSPC`, `^IXIC`
- Azioni: `AAPL`, `MSFT`

---

## Routine Giornaliera Consigliata

### Pre-Market (07:00 - 08:30 ora italiana)

1. **Esegui il Trading Assistant**:

   ```bash
   python main.py
   ```

2. **Leggi il report** — concentrati su:
   - Sentiment macro: qual e' il bias generale?
   - Risk events: ci sono eventi che possono muovere il mercato?
   - Score tecnico dei tuoi asset principali

3. **Apri TradingView** e verifica i livelli chiave:
   - Il prezzo rispetta i livelli indicati dal report?
   - Ci sono pattern grafici che confermano o smentiscono il bias?

4. **Decidi la strategia** per la giornata:
   - Direzione preferita (LONG/SHORT/FLAT)
   - Livelli di ingresso e stop loss
   - Size in base alla volatilita' (ATR)

5. **Opera su Fineco** solo quando hai conferma visiva su TradingView

### Tips

- Esegui il report anche dopo la chiusura per avere un riepilogo della giornata
- Se il sentiment e' neutro o conflittuale, riduci la size o resta flat
- I report sono salvati nella cartella `reports/` — utili per tenere un diario di trading

---

## Integrazione Polymarket

Il sistema integra i dati dei **mercati predittivi di Polymarket** come terzo segnale di conferma. Polymarket è una piattaforma dove utenti reali scommettono con denaro vero sulla probabilità di eventi futuri (decisioni della Fed, recessione, conflitti geopolitici, commodity). Queste probabilità riflettono l'opinione aggregata del mercato e possono fornire un segnale complementare all'analisi tecnica e al sentiment LLM.

Il modulo (v3) utilizza l'endpoint `/events` dell'API Gamma con **tag_slug curati** per asset class (es. `fed`, `gdp`, `tariffs`, `gold`, `oil`), garantendo che vengano analizzati solo mercati finanziari rilevanti. I mercati non finanziari (sport, meteo, intrattenimento) vengono scartati automaticamente.

### Utilizzo offline

Se non vuoi o non puoi raggiungere l'API Polymarket (es. senza connessione), usa il flag `--no-polymarket`:

```bash
python main.py --no-polymarket
```

Il pipeline funzionerà esattamente come prima, senza la sezione Polymarket nel report.

### Come interpretare il box Confluenza

- **CONFLUENZA TRIPLA** (verde): LLM, indicatori tecnici e Polymarket concordano sulla stessa direzione. Segnale più affidabile.
- **CONFLITTO** (arancione): Polymarket dice il contrario dell'LLM con alta confidenza. Massima cautela.
- **Segnale neutro o parziale** (grigio): Non c'è accordo forte. Usa come contesto aggiuntivo.

> **Nota:** L'API Polymarket è gratuita e pubblica, non serve nessuna API key.

---

## Struttura del Progetto

```
trading-assistant/
├── main.py                      # Entry point
├── config.yaml                  # Configurazione (asset, feed, parametri)
├── modules/
│   ├── news_fetcher.py          # Aggregatore notizie RSS
│   ├── price_data.py            # Dati prezzo + indicatori tecnici
│   ├── sentiment.py             # Analisi sentiment (Groq / FinBERT)
│   ├── report.py                # Generatore report HTML
│   ├── hallucination_guard.py   # Validazione anti-allucinazione
│   ├── polymarket.py            # Segnale mercati predittivi Polymarket (v3)
│   ├── keywords.py              # Keyword condivise bullish/bearish
│   └── trade_log.py             # Registro trade e statistiche
├── reports/                     # Report HTML generati
├── tests/                       # Test suite
├── requirements.txt             # Dipendenze Python
└── README.md                    # Questa guida
```

---

## Risoluzione Problemi

| Problema                       | Soluzione                                                               |
| ------------------------------ | ----------------------------------------------------------------------- |
| `GROQ_API_KEY non impostata`   | Esporta la variabile d'ambiente (vedi Setup punto 3)                    |
| `No data returned for symbol`  | Verifica che il simbolo sia corretto su Yahoo Finance                   |
| `Rate limit exceeded`          | Aspetta qualche minuto, Groq free tier ha limiti                        |
| `FinBERT download lento`       | Normale al primo avvio, il modello viene cachato                        |
| Report non si apre nel browser | Usa `--no-browser` e apri manualmente il file dalla cartella `reports/` |

---

## Disclaimer

Questo strumento e' solo a scopo informativo e didattico. **Non costituisce consiglio finanziario.** Il trading di CFD comporta un alto rischio di perdita. Opera sempre in modo responsabile e con capitali che puoi permetterti di perdere.
