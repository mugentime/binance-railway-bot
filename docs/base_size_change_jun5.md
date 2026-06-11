# BASE_SIZE_PCT Increase Implementation - June 5, 2026

## ✅ Change Implemented

**Date:** June 5, 2026
**Commit:** 6b08277
**Status:** DEPLOYED to Railway

---

## 📝 Configuration Change

```python
# File: src/config.py, Line 32

# BEFORE:
BASE_SIZE_PCT = 0.03  # 3% of account balance per trade

# AFTER:
BASE_SIZE_PCT = 0.05  # 5% of account balance per trade
```

**Change:** +67% increase (from 3% to 5%)

---

## 📊 Expected Impact

### Position Sizes

| Level | Before (3%) | After (5%) | Change |
|-------|-------------|------------|--------|
| **L0** | $1.42 | **$2.36** | +$0.94 (+67%) |
| **L1** | $1.77 | **$2.95** | +$1.18 (+67%) |
| **L2** | $2.22 | **$3.69** | +$1.47 (+67%) |
| **L3** | $2.77 | **$4.62** | +$1.85 (+67%) |
| **L4** | $3.46 | **$5.77** | +$2.31 (+67%) |
| **L5** | $4.33 | **$7.21** | +$2.88 (+67%) |
| **L6** | $5.41 | **$9.02** | +$3.61 (+67%) |
| **L7** | $6.76 | **$11.27** | +$4.51 (+67%) |
| **L8** | $8.45 | **$11.82** | +$3.37 (+40%) [CAPPED] |
| **L9** | $10.57 | **$11.82** | +$1.25 (+12%) [CAPPED] |
| **L10** | $11.82 | **$11.82** | $0.00 (0%) [CAPPED] |

**Note:** Emergency brake (25% cap) now triggers at **Level 8** instead of Level 10

### Performance Metrics

| Metric | Before (3%) | After (5%) | Improvement |
|--------|-------------|------------|-------------|
| **Daily P&L** | $5.35 | **$8.91** | +$3.56 (+66%) |
| **4-Day ROI** | 43.5% | **72.6%** | +29.1 pts (+67%) |
| **Annualized** | 4,128% | **6,879%** | +2,751 pts (+67%) |
| **P&L per Trade** | $0.35 | **$0.59** | +$0.24 (+67%) |

### Risk Metrics

| Metric | Before (3%) | After (5%) | Change |
|--------|-------------|------------|--------|
| **Chain Risk** | 5.0% | **7.0%** | +2.0 pts (+40%) |
| **Max Drawdown** | ~5% | **~7%** | +2 pts |
| **Emergency Brake** | L10 | **L8** | -2 levels |
| **Risk/Reward** | 8.72 | **10.41** | +1.69 (+19%) |

---

## 🎯 Monitoring Plan (Next 48 Hours)

### Critical Metrics to Watch:

#### ✅ Position Size Verification
- [ ] L0 positions opening at **~$2.36** (not $1.42)
- [ ] Current active positions reflect new sizing
- [ ] Emergency brake triggers correctly at L8

#### ✅ Performance Tracking
- [ ] Daily P&L trending toward **$8-9** (vs previous $5-6)
- [ ] Win rate maintains **40%+**
- [ ] Profit factor stays **>1.3**

#### ✅ Risk Monitoring
- [ ] Max drawdown stays **<10%** of account
- [ ] Chains don't frequently hit **L7-L8**
- [ ] No chains reaching **L9-L10** (emergency brake working)

#### ✅ Chain Behavior
- [ ] Chain escalation frequency (should be similar)
- [ ] Chain duration (should remain <48h)
- [ ] Chain recovery speed (should be similar or better)

### What to Look For in Logs:

```bash
# Check new base size is being used:
railway logs | grep "Base size"

# Expected output:
# "BALANCE: $47.27 → Base size = $2.36 (5.0%)"
# (Previously: "Base size = $1.42 (3.0%)")

# Monitor position entries:
railway logs | grep "ENTERED"

# Watch for emergency brake:
railway logs | grep "EMERGENCY BRAKE"
```

---

## 🚨 Rollback Plan (If Needed)

### Conditions for Rollback:

**Immediately rollback to 3% if:**
1. Chains frequently hitting **L8-L9**
2. Max drawdown exceeds **15%** of account
3. Win rate drops below **35%**
4. Multiple emergency brake triggers in 24 hours

**Consider reducing to 4% if:**
1. Chains regularly hitting **L7**
2. Max drawdown consistently **>10%**
3. Uncomfortable with position sizes
4. Win rate drops to **35-38%**

### Rollback Procedure:

```bash
# 1. Edit config
# src/config.py line 32:
BASE_SIZE_PCT = 0.03  # Reverted from 0.05

# 2. Commit and deploy
git add src/config.py
git commit -m "revert: reduce BASE_SIZE_PCT back to 3%"
railway up --detach

# 3. Monitor deployment
railway logs
```

---

## 📈 Expected Timeline to Goals

### Time to $100 Account:

**Before (3% base):**
- Daily gain: ~$5.35
- Days to $100: ~10 days
- Date: June 15, 2026

**After (5% base):**
- Daily gain: ~$8.91
- Days to $100: **~6 days**
- Date: **June 11, 2026**

**Savings:** 4 days faster to $100 milestone

### Compounding Impact:

```
Day 1:  $47.27 → $56.18 (+$8.91, +18.8%)
Day 2:  $56.18 → $66.65 (+$10.47, +18.6%)
Day 3:  $66.65 → $79.05 (+$12.40, +18.6%)
Day 4:  $79.05 → $93.76 (+$14.71, +18.6%)
Day 5:  $93.76 → $111.20 (+$17.44, +18.6%)
Day 6:  $111.20 → $131.88 (+$20.68, +18.6%)

Compounding factor: ~18.6% per day vs 11.7% previously
```

---

## ✅ Success Criteria (48-Hour Review)

### Target Metrics:

| Metric | Target | Pass/Fail |
|--------|--------|-----------|
| Daily P&L | $8-10 | ___ |
| Win Rate | >40% | ___ |
| Profit Factor | >1.3 | ___ |
| Max Drawdown | <10% | ___ |
| Chains at L7+ | <30% | ___ |
| Emergency Brake | 0 triggers | ___ |

### Decision Tree:

```
After 48 hours:

IF all targets met:
  → KEEP 5% base size ✅
  → Continue monitoring
  → Consider 6% when account hits $75

ELSE IF 4-5 targets met:
  → KEEP 5% base size ⚠️
  → Monitor closely for another 48h
  → Adjust if deteriorates

ELSE IF <4 targets met:
  → REDUCE to 4% 🔄
  → Monitor for 48h
  → Re-evaluate based on performance

ELSE IF major issues (drawdown >15%, emergency brake triggered):
  → REVERT to 3% immediately 🚨
  → Focus on improving signal quality first
```

---

## 📋 Next Review Checkpoints

### 24-Hour Check (June 6, 2026):
- [ ] Quick performance review
- [ ] Verify position sizes correct
- [ ] Check for any issues

### 48-Hour Check (June 7, 2026):
- [ ] Full performance analysis
- [ ] Compare vs 3% baseline
- [ ] Decide: keep 5%, reduce to 4%, or revert to 3%

### 1-Week Check (June 12, 2026):
- [ ] Comprehensive performance review
- [ ] Assess capital efficiency improvement
- [ ] Consider next optimization (6% or signal quality)

---

## 🎯 Optimization Path Forward

### Current State:
- BASE_SIZE_PCT: **5%** (implemented)
- Win Rate: 43.1%
- Profit Factor: 1.36
- Capital Efficiency Score: ~62.7

### Next Optimizations (in order):

**1. Improve Win Rate (Priority 1)**
- Target: 50%+ win rate
- Impact: +10% win rate = +$2 daily P&L
- Method: Signal quality tuning

**2. Increase Profit Factor (Priority 2)**
- Target: 2.0+ profit factor
- Impact: +50% profit factor = +$3 daily P&L
- Method: Better TP/SL ratios

**3. Consider 6% Base Size (Priority 3)**
- After: Win rate >50% AND profit factor >2.0
- Impact: +20% additional returns
- Risk: Emergency brake at L7

**4. Optimize Entry Timing (Priority 4)**
- Target: Reduce idle time, increase position frequency
- Impact: +15-20% more trades
- Method: Signal threshold tuning

---

## 💡 Key Insights

### Why This Works:
1. **Small account optimization:** $47 account needs faster growth
2. **Manageable risk:** 7% total chain risk is acceptable
3. **Better capital efficiency:** +67% returns for +40% risk = good trade-off
4. **Compound growth:** Larger base → faster compounding → exponential growth

### What Could Go Wrong:
1. **Faster escalation:** Chains hit emergency brake 2 levels earlier (L8 vs L10)
2. **Larger losses:** Individual losses 67% bigger ($0.15 vs $0.09)
3. **Emotional impact:** Bigger swings can cause stress
4. **Drawdown risk:** Max drawdown increases to 7% (was 5%)

### Risk Mitigation:
- ✅ Emergency brake still active at 25% cap
- ✅ All safety mechanisms operational (cooldowns, chain duration limits)
- ✅ Can rollback immediately if issues arise
- ✅ Monitoring plan in place

---

## 📊 Historical Context

### Previous Configuration Changes:

| Date | Change | Reason | Result |
|------|--------|--------|--------|
| May 9 | Restored Martingale | Recovery from losses | Profitable |
| May 12 | Added regime switching | Adaptive to losses | Mixed |
| May 13 | Added LONG penalty | Block LONGs | Fixed |
| May 31 | Emergency safety fixes | Stop bleeding | Reverted |
| Jun 1 | Re-enabled safety fixes | Proper implementation | **Working** |
| **Jun 5** | **Increased base to 5%** | **Faster growth** | **Testing** |

---

## ✅ Implementation Summary

**What Changed:**
- Single line in `src/config.py`: `BASE_SIZE_PCT = 0.03 → 0.05`

**Expected Impact:**
- +67% daily P&L ($5.35 → $8.91)
- +2% total chain risk (5% → 7%)
- Emergency brake: L10 → L8
- Time to $100: 10 days → 6 days

**Risk Level:**
- Before: LOW
- After: MODERATE (still safe)

**Monitoring:**
- Next 48 hours critical
- Can rollback immediately if needed
- Review checkpoints at 24h, 48h, 1 week

**Status:** ✅ **DEPLOYED AND ACTIVE**

---

**Implementation Date:** June 5, 2026
**Deployed By:** Claude Code Analysis
**Next Review:** June 7, 2026 (48-hour checkpoint)
