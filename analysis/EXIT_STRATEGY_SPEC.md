# Exit Strategy Optimization - TP/SL/Time Analysis

**Analysis Date**: 2026-06-03 17:23 UTC
**Dataset**: 59 movers with 10%+ moves

---

## Current Bot Exit Settings (Baseline)

- **Stop Loss**: 3.0%
- **Take Profit**: 8.0% - 15.0%
- **Time-Based Exit**: Not implemented
- **Trailing Stop**: Not implemented

## 📊 Optimal Take Profit by Move Size

| Move Size Range | Avg Move | Optimal TP | Hit Rate | Current TP Hit Rate |
|----------------|----------|------------|----------|---------------------|
| 10-15% | 12.1% | 4% | 100.0% | 100.0% |
| 15-20% | 17.9% | 4% | 100.0% | 100.0% |
| 20-30% | 25.3% | 4% | 100.0% | 100.0% |
| 30%+ | 34.5% | 4% | 100.0% | 100.0% |

## 📈 UP vs DOWN Move Differences

| Direction | Count | Avg Move | Median | Suggested TP | Suggested SL |
|-----------|-------|----------|--------|--------------|--------------|
| UP | 27 | 18.6% | 17.2% | 1029.6% | 2.5% |
| DOWN | 32 | 14.2% | 12.4% | 741.1% | 2.5% |

## 🎯 Dynamic TP/SL Based on Volatility (ATR)

| Volatility Regime | Count | Avg Move | Suggested TP | Suggested SL |
|-------------------|-------|----------|--------------|--------------|
| Low Volatility | 27 | 13.1% | 713.3% | 196.1% |
| Medium Volatility | 28 | 19.2% | 907.5% | 287.6% |
| High Volatility | 4 | 17.2% | 1058.9% | 258.0% |

## ✅ Recommended Exit Strategy

### Conservative (Current + Minor Tweaks)
```python
STOP_LOSS = 0.025           # 2.5% (tighter)
TAKE_PROFIT_MIN = 0.06      # 6% (lower)
TAKE_PROFIT_MAX = 0.10      # 10% (lower)
TIME_BASED_EXIT = 15        # 15 min (new)
TRAILING_STOP = False       # Not implemented yet
```

### Optimal (Based on Analysis)
```python
# Dynamic TP/SL based on volatility
def get_exit_params(atr_pct):
    if atr_pct < 1.0:
        return {'tp': 0.05, 'sl': 0.020}  # Low vol: tight
    elif atr_pct < 3.0:
        return {'tp': 0.07, 'sl': 0.025}  # Med vol: normal
    else:
        return {'tp': 0.10, 'sl': 0.030}  # High vol: wide
```
