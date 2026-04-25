# 10%+ Price Move Analysis Report

Generated: 2026-04-23 21:38:51

Analysis Period: Last 30 days

---

## Executive Summary

- **Total 10%+ Moves Detected:** 4821
- **UP Moves:** 2560 (53.1%)
- **DOWN Moves:** 2261 (46.9%)
- **Unique Symbols with 10%+ Moves:** 20


## Dataset Summary

### Move Size Distribution

| Move Range | Count | Percentage |
|------------|-------|------------|
| 10-15% | 2704 | 56.1% |
| 15-20% | 1013 | 21.0% |
| 20-30% | 677 | 14.0% |
| 30-50% | 321 | 6.7% |
| 50%+ | 106 | 2.2% |


### Top 20 Symbols by Frequency of 10%+ Moves

| Rank | Symbol | Total Moves | UP Moves | DOWN Moves |
|------|--------|-------------|----------|------------|
| 1 | RAVEUSDT | 200 | 108 | 92 |
| 2 | SIRENUSDT | 190 | 97 | 93 |
| 3 | AIOTUSDT | 175 | 80 | 95 |
| 4 | ARIAUSDT | 129 | 73 | 56 |
| 5 | BULLAUSDT | 124 | 70 | 54 |
| 6 | STOUSDT | 98 | 53 | 45 |
| 7 | BLESSUSDT | 89 | 43 | 46 |
| 8 | BASUSDT | 86 | 49 | 37 |
| 9 | 币安人生USDT | 86 | 51 | 35 |
| 10 | ONUSDT | 86 | 48 | 38 |
| 11 | NOMUSDT | 83 | 47 | 36 |
| 12 | TRADOORUSDT | 81 | 44 | 37 |
| 13 | BRUSDT | 80 | 36 | 44 |
| 14 | AKEUSDT | 78 | 42 | 36 |
| 15 | DUSDT | 77 | 39 | 38 |
| 16 | PIPPINUSDT | 57 | 27 | 30 |
| 17 | PLAYUSDT | 57 | 34 | 23 |
| 18 | BSBUSDT | 56 | 27 | 29 |
| 19 | BASEDUSDT | 56 | 31 | 25 |
| 20 | CYSUSDT | 54 | 33 | 21 |


## Indicator Pattern Analysis

### Patterns Before UP Moves

| Pattern | Occurrences | Coverage (%) |
|---------|-------------|--------------|
| Volume > 1.5x | 1084 | 42.3% |
| BB%B > 0.8 | 982 | 38.4% |
| RSI > 70 | 683 | 26.7% |
| Z-score > 2.0 | 487 | 19.0% |
| SMA Slope > 0.3% | 411 | 16.1% |
| BB%B < 0.2 | 367 | 14.3% |
| RSI < 30 | 275 | 10.7% |
| SMA Slope < -0.3% | 171 | 6.7% |
| Z-score < -2.0 | 105 | 4.1% |


### Patterns Before DOWN Moves

| Pattern | Occurrences | Coverage (%) |
|---------|-------------|--------------|
| Volume > 1.5x | 951 | 42.1% |
| BB%B > 0.8 | 665 | 29.4% |
| BB%B < 0.2 | 493 | 21.8% |
| RSI > 70 | 471 | 20.8% |
| SMA Slope > 0.3% | 459 | 20.3% |
| RSI < 30 | 304 | 13.4% |
| Z-score > 2.0 | 269 | 11.9% |
| Z-score < -2.0 | 196 | 8.7% |
| SMA Slope < -0.3% | 186 | 8.2% |


## Key Insights

### Average Indicator Values Before Moves

| Indicator | Before UP Moves | Before DOWN Moves |
|-----------|-----------------|-------------------|
| rsi | 56.22 | 53.00 |
| bb_pct_b | 0.65 | 0.54 |
| zscore | 0.60 | 0.16 |
| volume_ratio | 7.52 | 3.69 |
| sma_slope_pct | 0.07 | 0.08 |


## Current Bot Configuration Comparison

### Bot Entry Criteria (from config.py)

- **Strategy:** MEAN_REVERSION (inverted signals)
- **RSI Thresholds:** <25 (LONG), >75 (SHORT)
- **Entry Threshold:** 45.0 composite score
- **SMA Slope Threshold:** ±0.3% (blocks counter-trend)


### Estimated Bot Coverage

- **UP Moves with RSI >75 or <25:** 636/2560 (24.8%)
- **DOWN Moves with RSI >75 or <25:** 518/2261 (22.9%)


## Recommendations

1. **Pattern Detection:** Focus on patterns with >30% coverage for reliable signals
2. **Volume Confirmation:** High volume ratio (>1.5x) appears frequently before moves
3. **Trend Alignment:** SMA slope shows directional bias - consider trend-following strategies
4. **RSI Extremes:** Current thresholds (25/75) may be too conservative - analyze optimal levels
5. **Combination Signals:** Multi-indicator confirmation may improve accuracy


---

**Data Source:** Binance USDT-M Futures

**Analysis Method:** Pre-move indicator snapshots (15 minutes before 1-hour 10%+ candles)

**Dataset:** See `pre_move_indicators_30d.csv` for raw data