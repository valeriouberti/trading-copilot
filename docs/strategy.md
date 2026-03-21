# Trading Strategy

## Core Concept

The system identifies high-probability setups by requiring **convergence** across multiple independent signals: technical indicators, market regime, multi-timeframe alignment, quality score, news sentiment, and prediction markets.

No single indicator drives a trade. The strategy demands that most evidence points in the same direction before generating a signal.

**LONG-only**: the system only generates BUY signals. Bearish regimes produce SELL_IF_HOLDING advisories (no short entries).

## ETF Universe

| Symbol | Name | Category | Role |
|--------|------|----------|------|
| `SWDA.MI` | iShares Core MSCI World | Equity - Global | Core allocation |
| `CSSPX.MI` | iShares Core S&P 500 | Equity - US | US exposure |
| `EQQQ.MI` | Invesco NASDAQ-100 | Equity - US Tech | High-beta growth |
| `MEUD.MI` | Amundi STOXX Europe 600 | Equity - Europe | European exposure |
| `IEEM.MI` | iShares MSCI EM | Equity - EM | Emerging markets |
| `SGLD.MI` | Invesco Physical Gold | Commodity | Safe haven |
| `SEGA.MI` | iShares Core EU Govt Bond | Bond - EUR | Defensive |
| `AGGH.MI` | iShares Global Agg Bond | Bond - Global | Defensive |

All available on Fineco at EUR 2.95/trade. Yahoo Finance tickers use `.MI` suffix natively.

## Technical Indicators

### 5 Directional Indicators

| Indicator | What It Measures | BULLISH | BEARISH |
|-----------|-----------------|---------|---------|
| **RSI(14)** | Momentum | Regime-aware: <55 in trend, <30 in range | >45 in trend, >70 in range |
| **MACD** | Momentum shift | Histogram rising + positive crossover | Histogram falling + negative crossover |
| **EMA(20/50)** | Trend | EMA20 > EMA50, price above EMA20 | EMA20 < EMA50, price below EMA20 |
| **Bollinger Bands** | Volatility position | Price near lower band (oversold) | Price near upper band (overbought) |
| **Stochastic** | Overbought/oversold | %K < 20 (oversold) with crossover | %K > 80 (overbought) with crossover |

Indicator labels are **regime-aware**: thresholds adapt based on whether ADX indicates a trending or ranging market.

### Supporting Indicators

| Indicator | Role |
|-----------|------|
| **ADX(14)** | Trend strength. >25 = trending, <20 = ranging |
| **ATR(14)** | Volatility for SL/TP distance calculation |

## Composite Score

The 5 directional indicators are combined into a weighted composite:

- Each indicator votes BULLISH (+1), BEARISH (-1), or NEUTRAL (0)
- Weights are regime-adaptive: momentum indicators (RSI, MACD) get 1.5x weight in trending markets, 0.7x in ranging
- **Threshold**: 60% weighted consensus required for a directional signal
- Result: **BULLISH**, **BEARISH**, or **NEUTRAL** with confidence percentage

## Quality Score (QS)

5 binary checks, each worth 1 point:

| Check | Condition | What It Means |
|-------|-----------|---------------|
| **Confluence** | 4+ indicators agree on direction | Strong consensus |
| **Strong Trend** | ADX > 25 | Market is trending, not chopping |
| **Near Key Level** | Price within 0.5% of support/resistance | Favorable entry zone |
| **Candle Pattern** | Engulfing, pin bar, or inside bar | Price action confirmation |
| **Volume Above Avg** | Volume > 20-period average | Institutional participation |

**Minimum QS for a trade: 4/5**. Below 4, the setup is skipped regardless of other signals.

## Multi-Timeframe Alignment (MTF)

Two timeframes are analyzed independently:

| Timeframe | Data | EMA Cross |
|-----------|------|-----------|
| Weekly | 2 years, 1wk | EMA20 vs EMA50 |
| Daily | 10 months, 1d | EMA20 vs EMA50 |

- **ALIGNED**: both agree on direction (highest conviction)
- **PARTIAL**: disagree
- **CONFLICTING**: contradictory signals

A trade requires **ALIGNED** MTF to be marked tradeable.

## Regime Determination

The market regime (LONG / NEUTRAL / BEARISH) is determined by combining:

1. **Technical composite** direction
2. **LLM sentiment** bias
3. **Polymarket** signal (when available)

If these sources conflict, regime defaults to NEUTRAL (no trade).

- `LONG` regime -> BUY signal (compute entry/SL/TP)
- `BEARISH` regime -> SELL_IF_HOLDING advisory (no new entry)
- `NEUTRAL` regime -> HOLD (no action)

## Key Levels

Computed from daily OHLC data:

- **PDH/PDL/PDC**: Previous day high, low, close
- **Pivot Points**: PP, R1, R2, S1, S2 (standard formula)
- **PWH/PWL**: Previous week high, low (when weekly data available)
- **Nearest Level**: closest level to current price with distance %

Key levels are drawn on the chart as dashed lines and factor into the Quality Score ("near key level" check).

## SL/TP Computation

Stop loss and take profit use **ATR multipliers** with adaptive adjustment:

| Asset Class | SL Multiplier | TP Multiplier | Default R:R |
|-------------|--------------|---------------|-------------|
| ETF | 1.5x ATR | 3.0x ATR | 1:2.0 |

**Adaptive mode**: when ATR history is available, the system uses the ATR percentile to adjust:
- Low volatility (ATR < 30th pct): tighter stops
- High volatility (ATR > 70th pct): wider stops

### Commission Viability

Before marking a setup as tradeable, the system checks that the expected TP gain exceeds 2x the round-trip commission cost:

```
Expected gain = (TP distance / entry price) * position_size_eur
Round-trip cost = 2 * 2.95 = EUR 5.90
Viable if: expected gain > 2 * 5.90 = EUR 11.80
```

### Max Hold

Positions are held for a maximum of 10 days. If neither SL nor TP is hit within 10 days, a SELL alert is triggered.

## 7 Entry Conditions

All must be true for a signal to fire:

1. Regime is LONG (not just directional -- must be LONG specifically)
2. EMA trend bullish (EMA20 > EMA50)
3. RSI not overbought (< 75)
4. Quality Score >= 4
5. MTF Aligned (weekly + daily agree)
6. Commission viable (expected gain > 2x round-trip cost)
7. No high-impact calendar event today (informational warning)

## What Cannot Be Backtested

These layers exist only in live mode and are documented gaps in backtesting:

| Layer | Why Live-Only |
|-------|---------------|
| LLM Sentiment | Requires real-time news + LLM |
| Economic calendar | Real-time event data |
| Polymarket | Real-time prediction market data |
| MTF alignment | Could be added but requires multi-TF data fetch |

All non-backtestable layers are **gatekeeping filters** that reduce trade count. Backtest results show an upper bound on frequency and a reasonable estimate of per-trade expectancy.

## Action Plan Logic

The Action Plan translates the analysis into plain English:

**Tradeable setup generates:**
1. Entry instruction (buy at price, supporting evidence)
2. Stop loss placement (exact price, ATR basis, distance in EUR)
3. Take profit target (price, R:R ratio, expected gain in EUR)
4. Multi-timeframe context
5. Sentiment and Polymarket confirmation/conflict
6. Execution rules (don't move SL, when to exit early)

**Non-tradeable setup explains:**
- Which conditions failed and why
- What would need to change for a trade
- Clear instruction to stay flat
