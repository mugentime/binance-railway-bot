# REVERTED TO ORIGINAL PENALTY LOGIC

**Date:** 2026-04-06
**Status:** ✅ REVERTED - BOT STOPPED

---

## Changes Reverted

### ❌ REMOVED: Directional Penalty System
- **Removed:** Uptrend → favor LONGS, penalize SHORTS
- **Removed:** Downtrend → favor SHORTS, penalize LONGS
- **Removed:** Slope-based directional bias

### ✅ RESTORED: Original Ranging Penalty
- **Restored:** RANGING regime → LONG penalty only
- **Restored:** SHORT signals never penalized
- **Restored:** Inverted momentum logic intact

---

## Current Logic (After Revert)

### Regime Detection
```
ATR Threshold: 0.5% (KEPT - lowered from 1.5%)
Slope Threshold: 0.1% (KEPT - lowered from 0.3%)

IF ATR% > 0.5% AND |Slope%| > 0.1%:
    regime = "trending"
ELSE:
    regime = "ranging"
```

### Signal Penalties

**RANGING Regime:**
- LONG signals: **score *= 0.3** (70% penalty)
- SHORT signals: **no penalty** (full strength)

**TRENDING Regime:**
- LONG signals: **no penalty** (full strength)
- SHORT signals: **no penalty** (full strength)

### Inverted Momentum Logic (Intact)

**Mean-Reversion Strategy:**
- Oversold (RSI < 30, BB%B < 0, Z < -1.5) → **SHORT signal**
  - Rationale: Price too low → expect reversion down (inverted)

- Overbought (RSI > 70, BB%B > 1, Z > 1.5) → **LONG signal**
  - Rationale: Price too high → expect reversion up (inverted)

**This is the ORIGINAL "inverted" logic - meant for mean-reversion.**

---

## Current BTC Status

**Regime:** RANGING (ATR=0.65%, Slope=-0.0064%)

**Penalty Application:**
- LONG signals: 70% penalty active
- SHORT signals: No penalty
- **Result:** Bot will favor SHORTS

---

## Verification

Run test:
```bash
python scripts/verify_revert.py
```

Expected output:
```
[RANGING REGIME]
  - LONG signals:  70% PENALTY (score *= 0.3)
  - SHORT signals: NO PENALTY (full strength)
```

---

## Files Modified

1. **`src/signal_scorer.py`**
   - Line 226-243: Reverted to simple regime check
   - Line 283-287: Restored original LONG penalty (ranging only)
   - Line 327-330: Removed SHORT penalty
   - Line 369-376: Updated logging

2. **`src/main_loop.py`**
   - Line 18-100: Simplified regime detection
   - Removed directional bias
   - Kept lowered thresholds (0.5% ATR, 0.1% slope)

---

## What's KEPT vs REVERTED

### ✅ KEPT (Improvements)
- Lowered ATR threshold: 0.5% (more sensitive)
- Lowered Slope threshold: 0.1% (more sensitive)
- Insufficient balance auto-reset feature

### ❌ REVERTED (Removed)
- Directional penalties based on slope
- Uptrend → favor LONGS logic
- Downtrend → favor SHORTS logic
- Short penalties in uptrends

---

## Current Behavior

**In RANGING markets (most of the time):**
- Bot penalizes LONG signals by 70%
- Bot favors SHORT signals (full strength)
- Uses inverted momentum: oversold → SHORT, overbought → LONG

**In TRENDING markets (ATR > 0.5%, |Slope| > 0.1%):**
- No penalties for either direction
- Best signal wins
- Still uses inverted momentum logic

---

## Why This Reverted Logic May Still Lose

**The original penalty logic has a fundamental problem:**

1. **Inverted momentum in ranging markets:**
   - Oversold → SHORT (bet it goes lower)
   - This is COUNTER to mean-reversion theory
   - Mean-reversion says: oversold → bounce back up → LONG

2. **LONG penalty in ranging markets:**
   - Penalizes the correct mean-reversion direction
   - Example: If truly oversold, we SHOULD go LONG
   - But bot penalizes LONG by 70% and goes SHORT instead

**This explains the 100% loss rate we saw:**
- Bot is using inverted logic (oversold → SHORT)
- In ranging markets, this is backwards
- Should be: oversold → LONG (mean-reversion)

---

## Recommendation

**The original logic is fundamentally flawed.**

Two options:
1. **Keep inverted logic, remove penalties** - Let it trade both directions
2. **Fix the inversion** - Make oversold → LONG (true mean-reversion)

**DO NOT resume trading with current logic** - It will continue losing.

---

## Bot Status

- ✅ Bot stopped (no process running)
- ⚠️ Position open: LITUSDT LONG @ 1.0430 (Level 6)
- ✅ Original penalty logic restored
- ⚠️ Logic still fundamentally flawed

**Awaiting user confirmation before restarting**

---

## Summary

✅ **Revert complete** - Original RANGING penalty restored
✅ **Thresholds kept** - 0.5% ATR, 0.1% slope
❌ **Logic still broken** - Inverted momentum + LONG penalty = losses
🛑 **Bot stopped** - Waiting for user decision

**DO NOT RESTART until logic is fixed properly.**
