# Research Analysis Summary: Pre-Move Indicator Patterns

## Executive Overview

This research project analyzes indicator patterns that precede 10%+ hourly price movements across Binance USDT-M Futures pairs to optimize the trading bot's signal detection system.

## Research Deliverables

### 1. Main Research Script
**File:** `analysis/research_10pct_indicator_patterns.py`

**Capabilities:**
- Scans 143 USDT-M Futures pairs over 30-day period
- Detects all 1-hour candles with 10%+ price movement
- Captures pre-move indicator snapshots (15 minutes before)
- Calculates 6 key indicators using bot's existing logic
- Generates comprehensive dataset and analysis report

**Runtime:** 30-60 minutes
**Expected Output:** 1,000-5,000 pre-move records

### 2. Generated Dataset
**File:** `analysis/pre_move_indicators_30d.csv` (generated after run)

**Schema:**
```
symbol, timestamp, datetime, direction, move_pct, low, high,
rsi, bb_pct_b, zscore, volume_ratio, funding_rate, sma_slope_pct
```

**Use Cases:**
- Pattern correlation analysis
- Machine learning training data
- Threshold optimization studies
- Statistical modeling

### 3. Analysis Report
**File:** `analysis/10pct_move_analysis_report.md` (generated after run)

**Sections:**
- Executive Summary (total moves, directional breakdown)
- Dataset Summary (move distribution, top symbols)
- Indicator Pattern Analysis (coverage tables)
- Key Insights (average indicator values)
- Current Bot Comparison (estimated coverage)
- Recommendations (actionable improvements)

### 4. Documentation
**Files:**
- `analysis/RESEARCH_METHODOLOGY.md` - Detailed methodology
- `analysis/README.md` - Quick start guide
- `analysis/RESEARCH_SUMMARY.md` - This file

## Key Research Questions Addressed

### Q1: What indicator values precede 10%+ moves?
**Method:** Calculate average RSI, BB%B, Z-score, Volume Ratio, and SMA Slope for all pre-move snapshots.

**Expected Insight:** Identify if extreme indicator values (e.g., RSI >70, BB%B <0.2) are common before large moves.

### Q2: Are patterns different for UP vs DOWN moves?
**Method:** Separate analysis for upward and downward movements.

**Expected Insight:** Discover directional bias (e.g., "RSI >70 predicts DOWN moves 60% of the time").

### Q3: Would the current bot catch these moves?
**Method:** Apply current thresholds (RSI <25, RSI >75) to historical data.

**Expected Insight:** Estimate bot's hit rate vs miss rate for historical 10%+ moves.

### Q4: Which indicator combinations are most predictive?
**Method:** Pattern coverage analysis (single and multi-indicator).

**Expected Insight:** Find high-coverage patterns (>40%) with directional bias.

## Indicator Definitions

### 1. RSI (Relative Strength Index)
- **Range:** 0-100
- **Calculation:** 14-period momentum oscillator
- **Interpretation:**
  - <30 = Oversold
  - >70 = Overbought
- **Current Bot Threshold:** <25 (LONG), >75 (SHORT)

### 2. Bollinger %B
- **Range:** -∞ to +∞ (typically -0.5 to 1.5)
- **Calculation:** (Price - Lower Band) / (Upper Band - Lower Band)
- **Interpretation:**
  - <0 = Below lower band (oversold)
  - >1 = Above upper band (overbought)
  - 0.5 = At middle band
- **Current Bot Usage:** Part of composite score

### 3. Z-Score
- **Range:** -∞ to +∞ (typically -3 to +3)
- **Calculation:** (Price - Mean) / Std Dev (20-period)
- **Interpretation:**
  - <-2 = Significantly below average
  - >+2 = Significantly above average
- **Current Bot Threshold:** |Z| > 2.5 filtered out (too extreme)

### 4. Volume Ratio
- **Range:** 0 to +∞ (typically 0.5 to 3.0)
- **Calculation:** Current Volume / 20-period Average
- **Interpretation:**
  - <1.0 = Below average volume
  - >1.5 = Volume spike
  - >2.0 = Strong volume surge
- **Current Bot Usage:** Part of composite score

### 5. Funding Rate
- **Range:** -0.01 to +0.01 (typically -0.001 to +0.001)
- **Calculation:** Binance perpetual futures funding rate
- **Interpretation:**
  - Positive = Longs pay shorts (bearish sentiment)
  - Negative = Shorts pay longs (bullish sentiment)
- **Current Bot Usage:** Part of composite score

### 6. SMA Slope
- **Range:** -∞ to +∞ (typically -1.0% to +1.0% per candle)
- **Calculation:** Linear regression slope of 50-period SMA over last 10 candles
- **Interpretation:**
  - >+0.3% = Strong uptrend
  - <-0.3% = Strong downtrend
  - -0.3% to +0.3% = Ranging/weak trend
- **Current Bot Threshold:** |slope| > 0.3% blocks counter-trend entries

## Pattern Analysis Framework

### Single-Indicator Patterns

| Pattern Category | Condition | Expected Behavior |
|-----------------|-----------|-------------------|
| RSI Oversold | RSI < 30 | May precede UP moves (bounce) |
| RSI Overbought | RSI > 70 | May precede DOWN moves (reversal) |
| BB Below Band | BB%B < 0.2 | Extreme low, expect mean reversion |
| BB Above Band | BB%B > 0.8 | Extreme high, expect mean reversion |
| Z-Score Low | Z < -2.0 | Significantly undervalued |
| Z-Score High | Z > +2.0 | Significantly overvalued |
| Volume Spike | Vol Ratio > 1.5 | Increased activity, move imminent |
| Strong Uptrend | SMA Slope > 0.3% | Momentum favors UP moves |
| Strong Downtrend | SMA Slope < -0.3% | Momentum favors DOWN moves |

### Multi-Indicator Confluence

**Bullish Confluence (predict UP move):**
- RSI < 30 + BB%B < 0.2 + Volume > 1.5x
- Z-Score < -2.0 + SMA Slope > 0.3%
- RSI < 30 + Funding Rate > 0.0005 (shorts overextended)

**Bearish Confluence (predict DOWN move):**
- RSI > 70 + BB%B > 0.8 + Volume > 1.5x
- Z-Score > 2.0 + SMA Slope < -0.3%
- RSI > 70 + Funding Rate < -0.0005 (longs overextended)

## Current Bot Configuration Analysis

### Existing Strategy (from src/config.py)

```python
# Strategy Type
STRATEGY_MODE = "MEAN_REVERSION"
SIGNAL_DIRECTION = "inverted"  # oversold → SHORT, overbought → LONG

# Entry Thresholds
RSI_LONG_THRESHOLD = 25   # Only enter if RSI < 25
RSI_SHORT_THRESHOLD = 75  # Only enter if RSI > 75
ENTRY_THRESHOLD = 45.0    # Composite score must be ≥ 45

# Trend Filter
SMA_SLOPE_THRESHOLD = 0.3  # Block if |slope| > 0.3%

# Composite Score Weights
WEIGHTS = {
    "rsi": 0.30,
    "bollinger": 0.20,
    "zscore": 0.15,
    "volume": 0.15,
    "spread": 0.15,
    "funding": 0.05,
}
```

### Research Will Reveal

1. **Threshold Accuracy:**
   - Are RSI 25/75 optimal, or should they be 30/70 or 20/80?
   - What percentage of 10%+ moves had RSI in these ranges?

2. **Weight Optimization:**
   - Should RSI weight be 0.30, or should volume/zscore be higher?
   - Which indicators show strongest correlation to moves?

3. **Strategy Validation:**
   - Does "inverted" strategy (fade extremes) work for 10%+ moves?
   - Or should bot switch to trend-following for large moves?

4. **Filter Effectiveness:**
   - Does SMA slope threshold (0.3%) filter out losers or winners?
   - Should threshold be tightened (0.2%) or loosened (0.5%)?

## Expected Outcomes

### Scenario 1: Mean-Reversion Confirmed
**If analysis shows:**
- RSI <30 precedes 50%+ of UP moves
- RSI >70 precedes 50%+ of DOWN moves
- Z-score extremes correlate with reversals

**Action:** Keep MEAN_REVERSION strategy, optimize thresholds

### Scenario 2: Trend-Following Better
**If analysis shows:**
- RSI >70 precedes 50%+ of UP moves (continuation)
- SMA slope > 0.3% precedes 60%+ of UP moves
- Volume spikes + trend alignment = best predictor

**Action:** Switch to TREND_FOLLOWING mode, adjust scoring logic

### Scenario 3: Mixed Signals
**If analysis shows:**
- No clear pattern in RSI/BB/Z-score
- Volume spike is universal predictor (70%+ of all moves)
- Directional indicators unreliable

**Action:** Focus on volume-based filters, reduce reliance on RSI thresholds

### Scenario 4: Symbol-Specific Patterns
**If analysis shows:**
- BTC/ETH follow mean-reversion
- Altcoins follow trend-continuation
- Low-cap pairs are random

**Action:** Implement symbol-class-specific strategies

## Integration Plan

### Phase 1: Analyze Results (Week 1)
1. Run research script
2. Review generated report
3. Identify top 3-5 high-coverage patterns
4. Document findings in trading journal

### Phase 2: Propose Changes (Week 1-2)
1. Draft config.py modifications
2. Update signal_scorer.py if needed
3. Implement multi-indicator confluence logic
4. Peer review with team/community

### Phase 3: Backtest (Week 2-3)
1. Apply changes to test environment
2. Run 60-day historical backtest
3. Compare metrics: win rate, avg P&L, max DD, Sharpe ratio
4. Iterate on thresholds

### Phase 4: Paper Trade (Week 3-4)
1. Deploy to paper trading account
2. Monitor live performance for 14 days
3. Track: entry accuracy, exit timing, false positives
4. Fine-tune based on live data

### Phase 5: Production (Week 5+)
1. Deploy to live bot with reduced position sizing
2. Gradual ramp-up over 30 days
3. A/B test vs baseline configuration
4. Monthly performance review

## Success Metrics

### Research Quality
- ✅ Dataset size: >1,000 pre-move records
- ✅ Symbol coverage: >100 unique symbols
- ✅ Pattern identification: >5 patterns with >30% coverage
- ✅ Directional bias: >20% difference for UP vs DOWN

### Bot Improvement Targets
- 🎯 Increase entry accuracy by 15-25%
- 🎯 Reduce false positive rate by 20-30%
- 🎯 Improve win rate by 5-10 percentage points
- 🎯 Increase average profit per winning trade by 10-20%

## Risk Mitigation

### Research Limitations
1. **Historical Bias:** Past patterns may not predict future moves
2. **Overfitting:** Optimizing for 30-day sample may not generalize
3. **Market Regime:** Bull/bear/ranging markets have different patterns
4. **Sample Size:** 1,000 moves may be insufficient for rare patterns

### Mitigation Strategies
1. **Out-of-Sample Testing:** Use 30 days for analysis, 30 days for validation
2. **Cross-Validation:** Test patterns across different time periods
3. **Regime Detection:** Analyze patterns separately for bull/bear/ranging
4. **Conservative Thresholds:** Require high confidence (>40% coverage) for changes

## Conclusion

This research framework provides a systematic approach to optimizing the trading bot's signal detection system using empirical data from 10%+ price movements.

**Key Strengths:**
- Uses bot's existing indicator calculation logic (consistency)
- Analyzes real market data (not simulated)
- Generates actionable recommendations (not just analysis)
- Provides full audit trail (dataset + report + methodology)

**Next Steps:**
1. Execute research script: `python analysis/research_10pct_indicator_patterns.py`
2. Review generated report: `analysis/10pct_move_analysis_report.md`
3. Propose configuration changes based on findings
4. Implement and backtest changes
5. Deploy to production after validation

---

**Research Status:** Ready to Execute
**Estimated Completion:** 30-60 minutes runtime + 2-3 hours analysis
**Dependencies:** Python 3.9+, httpx, numpy (already installed)
**Output Location:** `/analysis/` directory

**Contact:** Research Agent
**Date:** 2026-04-23
