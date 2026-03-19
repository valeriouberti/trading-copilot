---

# NEXT_STEPS.md

# Trading Assistant — Roadmap Operativa

> Aggiornato: Marzo 2026 | Trader: retail, esecuzione manuale su Fineco

---

## Completati

- [x] Integrazione segnale Polymarket

---

## ⚙️ FASE 4 — Ottimizzazione

> Prerequisito: Fase 3 completata con accuracy ≥ 55%
> Tempo stimato: variabile

### 4a. Ottimizzazione Prompt

- [ ] Testare `lookback_hours: 8` vs `16` vs `24` → quale dà accuracy maggiore?
- [ ] Aggiungere contesto macro al prompt: giorno della settimana, sessione di mercato
- [ ] Testare prompt con richiesta esplicita di citare la fonte per ogni key driver
- [ ] Provare modello alternativo `mixtral-8x7b-32768` su Groq → confronta accuracy

### 4b. Nuovi Indicatori Tecnici

- [ ] Aggiungere Bollinger Bands a `price_data.py`
- [ ] Aggiungere Volume Profile (se disponibile via yfinance)
- [ ] Aggiungere rilevamento automatico livelli S/R daily

### 4c. Nuovi Feed News

- [ ] Aggiungere feed specifici per asset tradati (es. feed Bloomberg, FT)
- [ ] Aggiungere Economic Calendar automatico (Forex Factory RSS è gratuito)
- [ ] Filtrare news per rilevanza asset: solo news che menzionano l'asset nel titolo

### 4d. Polymarket Miglioramenti

- [ ] Espandi keyword Polymarket per asset specifici
- [ ] Aggiungi soglia minima volume ($50k) per filtrare mercati illiquidi
- [ ] Testa accuracy Polymarket signal separatamente nel trade log
  (aggiungi colonna poly_signal a trade_log.csv)

### 4e. Report Migliorato

- [ ] Aggiungere mini-chart sparkline (ultimi 5 giorni) nel report HTML
- [ ] Aggiungere sezione "Confronto con ieri" (sentiment oggi vs ieri)
- [ ] Notifica Telegram automatica del summary (bot Telegram = gratuito)

---

## 🚀 FASE 5 — Espansione (Opzionale, Futuro)

> Solo se vuoi evolvere verso semi-automazione
> Prerequisito: 3+ mesi di trade log con buona accuracy

- [ ] **Notifiche automatiche**: script schedulato con `cron` (Linux/Mac)
      o Task Scheduler (Windows) che gira ogni mattina alle 8:00
- [ ] **Broker API**: valutare IBKR (Interactive Brokers) per execution automatizzata
      se Fineco non espone API retail
- [ ] **Backtesting formale**: usare `backtrader` o `vectorbt` per testare
      storicamente la strategia tecnici + filtro LLM
- [ ] **Dashboard web locale**: Flask/Streamlit per visualizzare trade log e
      accuracy nel tempo senza aprire CSV
- [ ] **Multi-asset screening**: espandere a 10-15 CFD simultaneamente con
      ranking per opportunità (score composito LLM + tecnici)

---

## 📅 Timeline Suggerita

| Settimana      | Attività                                                          |
| :------------- | :---------------------------------------------------------------- |
| **Sett. 1**    | Fase 1: setup completo + prima esecuzione funzionante             |
| **Sett. 2**    | Fase 2: test suite verde + validazione manuale anti-allucinazione |
| **Sett. 3-8**  | Fase 3: trade log (minimo 30 trade) + osservazione quotidiana     |
| **Sett. 9-10** | Analisi accuracy + decisione se procedere con Fase 4              |
| **Sett. 11+**  | Fase 4: ottimizzazione mirata sui punti deboli emersi             |

---

## ⚠️ Regole Operative (Non Negoziabili)

1. **Mai tradare se `validation_flags` non è vuoto** nel report
2. **Mai usare il segnale LLM come unico motivo di entrata** — sempre abbinato a setup tecnico
3. **Compilare il trade log subito dopo ogni trade** — la memoria è inaffidabile
4. **Se il sistema non gira per 2+ giorni** → non tradare quel giorno, manca il contesto
5. **Footer del report**: "Solo uso informativo. Nessun consiglio finanziario." — è lì per un motivo

---

## 🔗 Riferimenti Rapidi

| Risorsa                               | Link                                                    |
| :------------------------------------ | :------------------------------------------------------ |
| Groq Console (API key)                | https://console.groq.com                                |
| Groq modelli disponibili              | https://console.groq.com/docs/models                    |
| yfinance ticker lookup                | https://finance.yahoo.com → cerca asset → copia simbolo |
| FinBERT (fallback LLM)                | https://huggingface.co/ProsusAI/finbert                 |
| Forex Factory RSS (economic calendar) | https://www.forexfactory.com/ff_calendar_thisweek.xml   |
| Claude Code docs                      | https://docs.anthropic.com/claude-code                  |

---

_Documento generato nel contesto del progetto trading-assistant._
_Aggiorna questo file dopo ogni fase completata._

````

---

Salvalo direttamente lanciando questo comando nella cartella del progetto:

```bash
curl -o NEXT_STEPS.md https://... # oppure semplicemente crea il file e incolla
```

Oppure, ancora più veloce, incolla in Claude Code:

```
Create a file called NEXT_STEPS.md in the project root with this exact content: [incolla il markdown sopra]
```
````
