# Research Methodology: 10%+ Price Move Indicator Patterns

## Objective

Identify indicator patterns that precede 10%+ hourly price moves across 143 Binance USDT-M Futures pairs to improve signal prediction accuracy.

## Research Questions

1. What indicator values are most common 15 minutes before a 10%+ move?
2. Are there distinct patterns for UP vs DOWN moves?
3. What percentage of 10%+ moves would the current bot configuration catch?
4. Which indicator combinations provide the best predictive power?

## Methodology

### Phase 1: Data Collection

**Move Detection:**
- Use 1-hour klines to identify 10%+ price movements
- Definition: (high - low) / low >= 10% within a single 1-hour candle
- Direction: UP if close > open, DOWN if close < open
- Time Period: Last 30 days across all USDT-M Futures pairs

**Pre-Move Indicator Calculation:**
- For each detected move, collect 5-minute candle data from 5 hours before the move
- Calculate indicators at the point 15 minutes (3 candles) before the move starts
- Indicators calculated:
  - **RSI (14-period):** Momentum oscillator (0-100 scale)
  - **Bollinger %B (20-period, 2σ):** Price position relative to bands
  - **Z-score (20-period):** Statistical deviation from mean
  - **Volume Ratio:** Current volume vs 20-period average
  - **Funding Rate:** Current perpetual futures funding rate
  - **SMA Slope (50-period):** Trend direction and strength

### Phase 2: Pattern Analysis

**Single Indicator Patterns:**
- RSI extremes: <30 (oversold), >70 (overbought)
- BB%B extremes: <0.2 (below band), >0.8 (above band)
- Z-score extremes: <-2.0 (oversold), >2.0 (overbought)
- Volume spikes: >1.5x average
- SMA slope: >0.3% (uptrend), <-0.3% (downtrend)

**Multi-Indicator Combinations:**
- Confluence analysis (2+ indicators aligned)
- Divergence analysis (indicators contradicting)
- Statistical correlation between indicators

**Coverage Metrics:**
- Percentage of UP moves with pattern present
- Percentage of DOWN moves with pattern present
- Total coverage across all 10%+ moves

### Phase 3: Bot Configuration Analysis

**Current Bot Settings (from config.py):**
```python
RSI_LONG_THRESHOLD = 25      # Enter on RSI < 25
RSI_SHORT_THRESHOLD = 75     # Enter on RSI > 75
ENTRY_THRESHOLD = 45.0       # Minimum composite score
SMA_SLOPE_THRESHOLD = 0.3    # Block counter-trend if |slope| > 0.3%
```

**Comparison:**
- How many historical 10%+ moves had RSI <25 or >75 before the move?
- Would current thresholds catch these moves?
- Are thresholds too conservative or too aggressive?

## Data Structure

### CSV Dataset: `pre_move_indicators_30d.csv`

| Column | Description | Example |
|--------|-------------|---------|
| symbol | Trading pair | BTCUSDT |
| timestamp | Move start time (ms) | 1713916800000 |
| datetime | Human-readable time | 2024-04-23 14:00 |
| direction | UP or DOWN | UP |
| move_pct | Percentage move | 12.5 |
| low | Lowest price in move | 65000.0 |
| high | Highest price in move | 73125.0 |
| rsi | RSI value 15min before | 72.3 |
| bb_pct_b | BB%B value 15min before | 0.85 |
| zscore | Z-score 15min before | 1.8 |
| volume_ratio | Volume ratio 15min before | 2.1 |
| funding_rate | Funding rate (approximation) | 0.0001 |
| sma_slope_pct | SMA slope 15min before | 0.45 |

### Markdown Report: `10pct_move_analysis_report.md`

**Sections:**
1. **Executive Summary:** Total moves, direction breakdown, unique symbols
2. **Dataset Summary:** Move size distribution, top symbols by frequency
3. **Indicator Pattern Analysis:** Tables showing coverage % for each pattern
4. **Key Insights:** Average indicator values before UP vs DOWN moves
5. **Current Bot Comparison:** Estimated coverage with current thresholds
6. **Recommendations:** Actionable insights for improving bot performance

## Expected Insights

### Hypothesis 1: Mean-Reversion Patterns
- 10%+ moves may be preceded by extreme RSI/BB/Z-score values
- Current "inverted" strategy (oversold → SHORT, overbought → LONG) should show correlation

### Hypothesis 2: Volume Confirmation
- Large moves likely preceded by volume spikes (ratio >1.5x)
- Volume may be a better filter than current spread/slippage filters

### Hypothesis 3: Trend Alignment
- SMA slope may show directional bias before moves
- Counter-trend moves (against SMA slope) may be rarer/riskier

### Hypothesis 4: Indicator Confluence
- Moves with multiple aligned indicators (e.g., RSI + BB%B + Volume) may be more reliable
- Single-indicator signals may have high false positive rates

## Usage

### Running the Analysis

```bash
# Execute the research script (takes 30-60 minutes)
python analysis/research_10pct_indicator_patterns.py
```

### Output Files

1. **analysis/pre_move_indicators_30d.csv** - Raw dataset for further analysis
2. **analysis/10pct_move_analysis_report.md** - Comprehensive findings report

### Next Steps After Analysis

1. **Review Report:** Identify high-coverage patterns (>30%)
2. **Optimize Thresholds:** Adjust RSI/BB/Z-score thresholds based on findings
3. **Implement Multi-Indicator Logic:** Add confluence requirements to signal scorer
4. **Backtest:** Test new configuration against historical data
5. **Forward Test:** Monitor live performance with new settings

## Technical Details

### API Endpoints Used

- `/fapi/v1/exchangeInfo` - Symbol universe
- `/fapi/v1/klines` - Historical price data (1h and 5m intervals)
- `/fapi/v1/premiumIndex` - Funding rates

### Rate Limiting

- 0.1s sleep between requests
- Max 3 retries with exponential backoff
- Persistent HTTP client for connection pooling

### Data Quality

- Requires minimum 50 candles for SMA calculation (4+ hours of 5m data)
- Funding rate is current value (historical funding requires separate API)
- Filters out moves with insufficient pre-move data

### Performance

- ~143 symbols analyzed
- ~30 days of historical data per symbol
- Estimated runtime: 30-60 minutes
- Expected dataset size: 1000-5000 move records

## Limitations

1. **Funding Rate:** Uses current funding rate, not historical (historical funding is complex)
2. **Survivorship Bias:** Only analyzes currently active pairs (delisted pairs excluded)
3. **Market Regime:** 30-day snapshot may not capture all market conditions
4. **Indicator Parameters:** Uses fixed periods (RSI-14, BB-20) - could test other values
5. **Pre-Move Timing:** Fixed 15-minute lookback - could test other windows

## Future Enhancements

1. **Extended Time Periods:** Analyze 60, 90, 180 days for more data
2. **Variable Lookback:** Test 5min, 10min, 20min, 30min pre-move windows
3. **Indicator Parameter Optimization:** Grid search RSI/BB/Z-score periods
4. **Machine Learning:** Train classifier on indicator patterns
5. **Real-Time Integration:** Build live pattern detector for bot integration

---

**Author:** Research Agent
**Date:** 2026-04-23
**Purpose:** Bot optimization through historical pattern analysis
