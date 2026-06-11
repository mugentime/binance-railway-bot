# 🎯 Quick Reference: 12 Precursor Patterns

**TL;DR for busy traders - Data from 59 movers with 10%+ moves**

---

## 🔴 Tier 1: VERY COMMON (>70%)

### #1. Low Volume Setup (88%)
**Signal**: `volume_ratio < 0.8`
**Meaning**: Below-average volume = easier to move price
**Action**: ✅ DON'T avoid low volume pairs!

### #2. Extreme Z-Score (76%)
**Signal**: `abs(zscore) > 2.0`
**Meaning**: Price 2σ from mean = stretched
**Action**: ✅ Bot uses 1.5, could test 1.0-1.2

---

## 🟡 Tier 2: COMMON (30-50%)

### #3. Squeeze On (41%)
**Signal**: `squeeze_ratio < 1.0` (BB inside KC)
**Meaning**: Volatility compression → breakout coming
**Action**: 🆕 ADD to signal scorer

### #4. RSI Oversold (32%)
**Signal**: `rsi < 30`
**Meaning**: Oversold, bounce likely
**Action**: ✅ Bot uses 25 (good)

### #5. BB Below Lower Band (32%)
**Signal**: `bb_pct_b < 0.0`
**Meaning**: Price below 2σ = extreme oversold
**Action**: ✅ Bot uses 0.2 (good)

### #6. Volume Surge (31%) 🎯 **TRIGGER SIGNAL**
**Signal**: `latest_vol > avg_prev_5_vol * 2.0`
**Meaning**: Smart money entering NOW
**Action**: 🚨 **CRITICAL - ADD THIS!**

---

## 🟢 Tier 3: LESS COMMON (15-25%)

### #7. Expanding Volatility (22%)
**Signal**: `squeeze_ratio > 2.5` (BB expanding)
**Meaning**: Breakout in progress
**Action**: Add as confirmation filter

### #8. RSI Overbought (17%)
**Signal**: `rsi > 70`
**Meaning**: Overbought, drop likely
**Action**: ✅ Bot uses 75 (good)

### #9. BB Above Upper Band (17%)
**Signal**: `bb_pct_b > 1.0`
**Meaning**: Price above 2σ = extreme overbought
**Action**: ✅ Bot uses 0.8 (good)

---

## 🔵 Tier 4: RARE (<10%)

### #10. Extreme Volatility (3%)
**Signal**: `atr_pct > 4.0`
**Meaning**: Pair already hot
**Action**: ⚠️ Not required for big moves

### #11. Volatility Compression (0%)
**Signal**: Declining ATR before move
**Meaning**: Classic "coiling spring"
**Action**: ❌ NOT found - don't wait for it

### #12. Divergence (0%)
**Signal**: Price/RSI opposite directions
**Meaning**: Traditional reversal signal
**Action**: ❌ NOT reliable for 10%+ moves

---

## 📊 Symbol Types (What Moves?)

| Type | % | Action |
|------|---|--------|
| **Mid/Small Cap** | 86% | ✅ Focus here |
| **AI/Tech** | 7% | ⚠️ Hype-driven |
| **Gaming** | 3% | ⚠️ Event-driven |
| **Meme** | 3% | ⚠️ Social sentiment |
| **Large Cap** | 0% | ❌ Don't scan BTC/ETH |

---

## ⏰ Time Patterns (When?)

| Time (UTC) | % | Action |
|------------|---|--------|
| **14:00-17:00** | 73% | 🔥 Scan every 60s |
| **12:00-20:00** | 83% | ✅ Active scanning |
| **08:00-12:00** | 7% | ⚠️ Slower scans |
| **00:00-08:00** | 8% | ❌ Minimal activity |
| **20:00-24:00** | 2% | ❌ Consider pausing |

**Peak Hour**: 16:00 UTC (14 moves, 24%)

---

## 🌊 Movement Patterns (How?)

### Clustering
- **79%** of moves occur within **15 min** of another move
- **Average wave size**: 9.2 moves per wave
- **Largest wave**: 43 moves (73% of all moves!)

### Directional
- **7 consecutive DOWN moves** (longest run)
- **Strong clustering** = moves follow market momentum
- **If 2-3 same direction**: Boost that direction +15%

---

## 🚨 TOP 3 IMPLEMENTATION PRIORITIES

### #1. Volume Surge Detection (31% frequency)
```python
if current_volume > avg_last_5_candles * 2.0:
    signal_score += 20  # Strong entry signal
```
**Impact**: Catch the EXACT trigger moment

### #2. Wave Detection Mode (79% in waves)
```python
# After detecting a move:
aggressive_scan = True
for 30_minutes:
    scan_every_60_seconds()
```
**Impact**: Catch 8-10 more moves in the wave

### #3. Directional Momentum (7 consecutive runs)
```python
if last_2_moves == 'DOWN':
    short_signals *= 1.15
    long_signals *= 0.85
```
**Impact**: Align with market momentum

---

## ❌ What DOESN'T Matter (Surprisingly)

1. **High Volume**: 88% have LOW volume (< 0.8× avg)
2. **Volatility Compression**: 0% showed this pattern
3. **Divergence**: 0% showed this pattern
4. **Large Caps**: 0% moved 10%+ (too much liquidity)
5. **Random Timing**: 83% during 12:00-20:00 UTC only

---

## 📈 Expected Improvement

| Metric | Current | With Enhancements | Improvement |
|--------|---------|-------------------|-------------|
| **Coverage** | 34% | 45-50% | +32% |
| **Win Rate** | 45.5% | 52-55% | +15% |
| **Signals/Day** | 12-15 | 20-25 | +60% |

---

## 🎯 Quick Implementation Checklist

**Week 1: High Impact**
- [ ] Add volume surge detection (2× spike)
- [ ] Implement wave mode (30 min aggressive scan)
- [ ] Add directional momentum tracking

**Week 2: Medium Impact**
- [ ] Add squeeze indicator (< 1.0 = +10 points)
- [ ] Time-based scan frequency (peak hours faster)
- [ ] Test lower RSI thresholds (70/30 vs 75/25)

**Week 3: Validation**
- [ ] Paper trade for 2 weeks
- [ ] Compare to current strategy
- [ ] Deploy if +10% win rate improvement

---

## 💡 One-Sentence Takeaways

1. **Low volume = good** (easier to move price)
2. **Volume surge = trigger** (2× spike in final candle)
3. **Moves cluster in waves** (9 moves per wave)
4. **Direction follows momentum** (7 consecutive runs)
5. **Peak hours matter** (73% during 14-17 UTC)
6. **Mid/small caps only** (86% of all moves)

---

**Print this card and keep it handy when implementing enhancements!**

**Version**: 1.0 | **Date**: June 2, 2026 | **Dataset**: 59 movers
