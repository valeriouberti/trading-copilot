# Trading Strategy

## Core Concept

The system identifies high-probability setups by requiring **convergence** across multiple independent signals: technical indicators, market regime, multi-timeframe alignment, quality score, news sentiment, and prediction markets.

No single indicator drives a trade. The strategy demands that most evidence points in the same direction before generating a signal.

## Assets

| Asset | Symbol | Type | Asset Class |
|-------|--------|------|-------------|
| S&P 500 | `^GSPC` | Cash index | index |
| Gold | `GC=F` | COMEX futures | commodity |
| EUR/USD | `EURUSD=X` | Spot forex | forex |

`^GSPC` is the cash S&P 500 index (not ES=F futures), since CFDs track the cash price, not the futures contract.

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
| **VWAP** | Intraday bias (price above = bullish, below = bearish). Live-only |

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

Three timeframes are analyzed independently:

| Timeframe | Data | EMA Cross |
|-----------|------|-----------|
| Weekly | 2 years, 1wk | EMA20 vs EMA50 |
| Daily | 10 months, 1d | EMA20 vs EMA50 |
| Hourly | 30 days, 1h | EMA20 vs EMA50 |

- **ALIGNED**: all 3 agree on direction (highest conviction)
- **PARTIAL**: 2 of 3 agree
- **CONFLICTING**: no agreement

A trade requires **ALIGNED** MTF to be marked tradeable.

## Regime Determination

The market regime (LONG / SHORT / NEUTRAL) is determined by combining:

1. **Technical composite** direction
2. **LLM sentiment** bias
3. **Polymarket** signal (when available)

If these sources conflict, regime defaults to NEUTRAL (no trade).

## Key Levels

Computed from daily OHLC data:

- **PDH/PDL/PDC**: Previous day high, low, close
- **Pivot Points**: PP, R1, R2, S1, S2 (standard formula)
- **PWH/PWL**: Previous week high, low (when weekly data available)
- **Nearest Level**: closest level to current price with distance %

Key levels are drawn on the chart as dashed lines and factor into the Quality Score ("near key level" check).

## SL/TP Computation

Stop loss and take profit use **per-class ATR multipliers** with adaptive adjustment:

| Asset Class | SL Multiplier | Default R:R |
|-------------|--------------|-------------|
| Index | 1.5x ATR | 1:2.0 |
| Commodity | 2.0x ATR | 1:2.5 |
| Forex | 1.5x ATR | 1:2.0 |

**Adaptive mode**: when ATR history is available, the system uses the ATR percentile to adjust:
- Low volatility (ATR < 30th pct): tighter stops
- High volatility (ATR > 70th pct): wider stops

## 9 Entry Conditions

All must be true for a signal to fire:

1. Regime is LONG or SHORT (not NEUTRAL)
2. EMA trend aligned with regime direction
3. Price above/below VWAP (intraday confirmation)
4. RSI not in extreme zone for the regime
5. Quality Score >= 4
6. MTF Aligned
7. Quality session (London or NYSE open)
8. No high-impact calendar event within 2 hours
9. Setup marked tradeable by the pipeline

## What Cannot Be Backtested

These layers exist only in live mode and are documented gaps in backtesting:

| Layer | Why Live-Only |
|-------|---------------|
| VWAP | Requires 5m intraday volume data |
| LLM Sentiment | Requires real-time news + LLM |
| Session quality | Time-of-day filter |
| Economic calendar | Real-time event data |
| Polymarket | Real-time prediction market data |
| MTF alignment | Could be added but requires multi-TF data fetch |

All non-backtestable layers are **gatekeeping filters** that reduce trade count. Backtest results show an upper bound on frequency and a reasonable estimate of per-trade expectancy.

## Action Plan Logic

The Action Plan translates the analysis into plain English:

**Tradeable setup generates:**
1. Entry instruction (buy/sell, price, supporting evidence)
2. Stop loss placement (exact price, ATR basis, invalidation logic)
3. Take profit target (price, R:R ratio)
4. Multi-timeframe context
5. Sentiment and Polymarket confirmation/conflict
6. Execution rules (don't move SL, when to exit early)

**Non-tradeable setup explains:**
- Which conditions failed and why
- What would need to change for a trade
- Clear instruction to stay flat
