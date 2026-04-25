# Research Analysis: 10%+ Price Move Indicator Patterns

## Quick Start

### Run the Complete Analysis

```bash
# Navigate to project root
cd /c/Users/je2al/Desktop/binance-railway-bot

# Execute research script (30-60 minute runtime)
python analysis/research_10pct_indicator_patterns.py
```

### Expected Output

The script will generate two files:

1. **pre_move_indicators_30d.csv** - Raw dataset with 1000-5000 records
2. **10pct_move_analysis_report.md** - Comprehensive analysis report

### Progress Monitoring

The script provides real-time progress updates:
- Symbol-by-symbol analysis status
- Progress percentage every 25 symbols
- ETA for completion
- Error tracking

### Sample Output

```
Fetching all USDT-M Futures symbols...
Found 143 active USDT pairs

Analyzing 143 symbols for 10%+ moves in the last 30 days...
This will take 30-60 minutes depending on network speed...

Analyzing BTCUSDT...
  Found 12 instances of 10%+ moves
  ✓ BTCUSDT: Collected 12 pre-move snapshots

Analyzing ETHUSDT...
  Found 8 instances of 10%+ moves
  ✓ ETHUSDT: Collected 8 pre-move snapshots

Progress: 25/143 (17.5%) | Analyzed: 24 | Errors: 1 | Records: 187 | ETA: 42.3 min
```

## Files in This Directory

### Research Scripts

- **research_10pct_indicator_patterns.py** - Main research script
- **RESEARCH_METHODOLOGY.md** - Detailed methodology documentation
- **README.md** - This file

### Generated Output (after running)

- **pre_move_indicators_30d.csv** - Raw dataset
- **10pct_move_analysis_report.md** - Analysis report

## What the Analysis Does

### 1. Data Collection

- Scans 143 USDT-M Futures pairs
- Identifies all 1-hour candles with 10%+ price movement
- For each move, captures indicator values 15 minutes before
- Calculates: RSI, BB%B, Z-score, Volume Ratio, Funding Rate, SMA Slope

### 2. Pattern Detection

- Analyzes indicator distributions for UP vs DOWN moves
- Calculates coverage percentage for each pattern
- Identifies most common pre-move conditions

### 3. Bot Configuration Comparison

- Compares findings to current bot thresholds (RSI 25/75)
- Estimates how many moves the bot would catch
- Provides optimization recommendations

## Understanding the Results

### Key Metrics to Look For

**High Coverage Patterns (>30%):**
- These patterns appear frequently before 10%+ moves
- Good candidates for entry signals

**Directional Bias:**
- If RSI >70 appears before 60% of DOWN moves → consider as short signal
- If Volume >1.5x appears before 70% of all moves → add as filter

**Current Bot Performance:**
- If bot would only catch 20% of moves → thresholds too strict
- If bot would catch 80% of moves → may have too many false positives

### Example Insights

```
Pattern: RSI < 30
- Before UP moves: 45%
- Before DOWN moves: 15%
→ Insight: Oversold condition predicts upward moves better

Pattern: Volume > 1.5x
- Before UP moves: 68%
- Before DOWN moves: 71%
→ Insight: Volume spike is a universal precursor, use as filter

Pattern: SMA Slope > 0.3%
- Before UP moves: 58%
- Before DOWN moves: 12%
→ Insight: Strong uptrend blocks downward moves
```

## Next Steps After Analysis

### 1. Review the Report

Read `10pct_move_analysis_report.md` for comprehensive findings.

### 2. Identify Optimization Opportunities

Look for:
- Patterns with >40% coverage for one direction
- Low coverage for opposite direction (directional bias)
- Multi-indicator confluence (2+ aligned)

### 3. Propose Configuration Changes

Example adjustments to `src/config.py`:

```python
# If analysis shows RSI <30 predicts 50% of UP moves:
RSI_LONG_THRESHOLD = 30  # Increased from 25

# If Volume >1.5x appears in 70% of all moves:
VOLUME_SPIKE_REQUIRED = True
VOLUME_SPIKE_THRESHOLD = 1.5
```

### 4. Backtest Changes

- Implement proposed changes in test environment
- Run historical backtest over 60-90 days
- Measure: win rate, average P&L, max drawdown

### 5. Forward Test

- Deploy to paper trading account
- Monitor for 7-14 days
- Compare to baseline performance

## Troubleshooting

### Script Fails with Network Error

```bash
# Increase timeout or add retry logic
# The script already has 3 retries with exponential backoff
# If persistent, check internet connection or Binance API status
```

### Too Few Records Collected

```bash
# Causes:
# 1. Low volatility period (< expected 10%+ moves)
# 2. Insufficient pre-move data (< 50 candles)
# 3. API rate limiting

# Solutions:
# - Extend analysis period from 30 to 60 days
# - Reduce DAYS_TO_ANALYZE in script for faster test run
```

### Script Takes Too Long

```bash
# Speed up by reducing symbols:
# Edit script, line ~395:
symbols = symbols[:50]  # Test with first 50 symbols only
```

## Data Analysis Tips

### Using the CSV Dataset

```python
import pandas as pd

# Load dataset
df = pd.read_csv('analysis/pre_move_indicators_30d.csv')

# Filter for large moves (>20%)
large_moves = df[df['move_pct'] > 20]

# Analyze RSI distribution before UP moves
up_moves = df[df['direction'] == 'UP']
print(up_moves['rsi'].describe())

# Find symbols with most moves
top_symbols = df['symbol'].value_counts().head(10)
print(top_symbols)

# Correlation analysis
print(df[['rsi', 'bb_pct_b', 'zscore', 'volume_ratio']].corr())
```

### Visualization Ideas

```python
import matplotlib.pyplot as plt
import seaborn as sns

# RSI distribution before UP vs DOWN moves
plt.figure(figsize=(12, 5))
plt.subplot(1, 2, 1)
df[df['direction'] == 'UP']['rsi'].hist(bins=20, alpha=0.7, label='UP')
df[df['direction'] == 'DOWN']['rsi'].hist(bins=20, alpha=0.7, label='DOWN')
plt.legend()
plt.title('RSI Distribution Before Moves')

# Volume ratio vs move size
plt.subplot(1, 2, 2)
plt.scatter(df['volume_ratio'], df['move_pct'], alpha=0.5)
plt.xlabel('Volume Ratio')
plt.ylabel('Move %')
plt.title('Volume Ratio vs Move Size')
plt.show()
```

## Technical Details

### System Requirements

- Python 3.9+
- Stable internet connection
- 30-60 minutes runtime
- ~50MB disk space for output

### API Usage

- ~4,000-6,000 API requests total
- Binance rate limit: 2,400 requests/minute (weight-based)
- Script uses 0.1s delays to stay well below limit

### Data Quality

- Requires 50+ candles per symbol (for SMA calculation)
- Missing data handled gracefully (skipped with warning)
- Funding rate approximation (current value, not historical)

## Support

For issues or questions:
1. Check `RESEARCH_METHODOLOGY.md` for detailed explanations
2. Review script source code comments
3. Verify Binance API connectivity: `curl https://fapi.binance.com/fapi/v1/ping`

---

**Last Updated:** 2026-04-23
**Script Version:** 1.0
**Author:** Research Agent
