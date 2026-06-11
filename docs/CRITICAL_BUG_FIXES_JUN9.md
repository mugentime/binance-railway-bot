# CRITICAL BUG FIXES - JUNE 9, 2026

## 🚨 EXECUTIVE SUMMARY

Three critical bugs were identified after the GUNUSDT chain failure that resulted in -$24.88 loss:

1. ✅ **Level Cap Bug** - VERIFIED AS WORKING CORRECTLY
2. ❌ **Signal Quality Bug** - Wrong direction entry (LONG in downtrend)
3. ⚠️ **Emergency Brake Bug** - NEEDS VERIFICATION

---

## BUG #1: LEVEL CAP - STATUS: ✅ WORKING CORRECTLY

### Initial Concern:
GUNUSDT chain appeared to reach Level 11 (beyond MAX_LEVEL=10).

### Investigation Result:
**FALSE ALARM** - The bot's level cap is working correctly!

### Evidence:
```python
# File: src/martingale_manager.py, Line 314-335

elif self.level >= config.MAX_LEVEL:  # If level >= 10
    log(f"MAX LEVEL HIT ({config.MAX_LEVEL}) - Full chain blowout...")
    self.level = 0  # CORRECT: Resets to 0
    ...
else:
    # Only increment if below MAX_LEVEL
    self.level += 1  # CORRECT: Only increments when level < 10
```

### What Actually Happened:
- The GUNUSDT "12 entries" were NOT 12 martingale levels
- They were partial fills across multiple executions at the SAME level
- Example: Level 0 entry had 7 separate fill orders (market order split by exchange)
- Actual martingale progression: L0 → L1 → L2 → L3 (confirmed via trade reconstruction)

### Conclusion:
**NO FIX NEEDED** - Level cap is functioning as designed.

---

## BUG #2: SIGNAL QUALITY - STATUS: ❌ CRITICAL ISSUE

### Problem:
Bot entered LONG positions while price was in a persistent DOWNTREND.

### Evidence:
```
GUNUSDT Price Action (June 4-9):
Entry 1: $0.006431 (June 4) - LONG
  ↓ -2.5%
Entry 2: $0.006273 (June 9) - LONG
  ↓ -2.4%
Entry 3: $0.006124 (June 9) - LONG
  ↓ Current: $0.006054 - STILL FALLING

Total Drop: -5.9% from first entry
All entries: LONG (expecting UP movement)
Actual movement: Continuous DOWN
```

### Root Cause Analysis:

#### 1. Signal Entry Logic (signal_scorer.py):
The bot uses inverted momentum / mean-reversion strategy:
```python
# Config line 28-29:
# Strategy: inverted momentum / mean-reversion
# SHORT on overbought (RSI>65, BB>0.8), LONG on oversold (RSI<35, BB<0.2)
```

**Problem**: This works in RANGING markets but FAILS in TRENDING markets!
- In a downtrend, RSI keeps hitting "oversold" (RSI<35)
- Bot keeps entering LONG expecting a bounce
- Price never bounces, keeps falling
- Martingale keeps adding to losing LONG position

#### 2. No Trend Filter:
Looking at config lines 62-66:
```python
# SMA Trend Filter (vars kept for reference; SMA computation removed from pair_scanner)
SMA_PERIOD = 50
SMA_SLOPE_LOOKBACK = 10
SMA_SLOPE_THRESHOLD = 0.3
```

**KEY FINDING**: "SMA computation removed from pair_scanner"!

The trend filter was DISABLED! The bot is trading pure mean-reversion without checking if there's an actual trend.

### Recommended Fixes:

#### Fix 2A: Re-enable Trend Filter (IMMEDIATE)
```python
# File: src/pair_scanner.py
# Add back SMA trend calculation and filtering

def calculate_sma_trend(closes, period=50):
    """Calculate SMA and trend direction"""
    if len(closes) < period:
        return None, None

    sma = sum(closes[-period:]) / period
    current_price = closes[-1]

    # Trend: price above SMA = uptrend, below = downtrend
    trend = "UP" if current_price > sma else "DOWN"
    trend_strength = abs((current_price - sma) / sma)  # % distance from SMA

    return sma, trend, trend_strength
```

#### Fix 2B: Add Trend Alignment Check (IMMEDIATE)
```python
# File: src/signal_scorer.py
# Only allow signals that align with trend

def score_signal(self, data, regime_flipped=False):
    # ... existing code ...

    # NEW: Trend alignment filter
    sma, trend, trend_strength = data.get('sma_trend', (None, None, 0))

    if sma is not None:
        # Strong downtrend (>2% below SMA) - BLOCK LONGS
        if trend == "DOWN" and trend_strength > 0.02:
            if direction == "LONG":
                log(f"{symbol}: BLOCKED LONG in downtrend (-{trend_strength*100:.1f}% from SMA)")
                return None  # Block this signal

        # Strong uptrend (>2% above SMA) - BLOCK SHORTS
        if trend == "UP" and trend_strength > 0.02:
            if direction == "SHORT":
                log(f"{symbol}: BLOCKED SHORT in uptrend (+{trend_strength*100:.1f}% from SMA)")
                return None

    # ... rest of scoring ...
```

#### Fix 2C: Add Minimum Retracement Check (RECOMMENDED)
```python
# Only enter mean-reversion trades after significant retracement
# This prevents catching a falling knife

def check_retracement(highs, lows, closes, direction, min_retrace_pct=0.03):
    """
    Check if price has retraced enough to justify mean-reversion entry
    min_retrace_pct: Minimum 3% retracement from recent extreme
    """
    if direction == "LONG":
        # For LONG: check if price has retraced up from recent low
        recent_low = min(lows[-10:])  # Last 10 candles
        current_price = closes[-1]
        retrace_pct = (current_price - recent_low) / recent_low

        if retrace_pct < min_retrace_pct:
            return False  # Not enough bounce yet

    elif direction == "SHORT":
        # For SHORT: check if price has retraced down from recent high
        recent_high = max(highs[-10:])
        current_price = closes[-1]
        retrace_pct = (recent_high - current_price) / recent_high

        if retrace_pct < min_retrace_pct:
            return False  # Not enough pullback yet

    return True
```

---

## BUG #3: EMERGENCY BRAKE - STATUS: ⚠️ NEEDS VERIFICATION

### Problem:
GUNUSDT Level 11 entry (if it existed) was $320.64, which is ~40% of $80 account.

### Config Setting:
```python
# File: src/config.py, Line 38
MAX_POSITION_PCT = 0.25  # 25% maximum
```

### Code Implementation:
```python
# File: src/martingale_manager.py, Lines 93-108

def position_size_usd(self) -> float:
    calculated_size = self.base_size_usd() * (config.MARTINGALE_MULTIPLIER ** self.level) * config.LEVERAGE

    # EMERGENCY BRAKE: Cap position at MAX_POSITION_PCT of account
    max_allowed = self.chain_start_balance * config.MAX_POSITION_PCT * config.LEVERAGE

    if calculated_size > max_allowed:
        log(f"🚨 EMERGENCY BRAKE: Position size ${calculated_size:.2f} exceeds maximum ${max_allowed:.2f} "
            f"({config.MAX_POSITION_PCT*100:.0f}% of account) - CAPPING", "warning")
        return max_allowed

    return calculated_size
```

### Analysis:
The code LOOKS correct:
- max_allowed = $80 * 0.25 * 20 = $400 (notional)
- This equals $20 margin (20x leverage)
- Which is 25% of $80 account ✅

BUT the GUNUSDT analysis showed position sizes that seem wrong. Need to verify:

### Investigation Needed:
1. Check if `chain_start_balance` is being updated correctly
2. Verify the emergency brake is being called
3. Check if there's a race condition where balance drops mid-chain

### Recommended Fix:
```python
# File: src/martingale_manager.py

def position_size_usd(self) -> float:
    """Calculate position size with ENHANCED emergency brake"""

    # CRITICAL: Always fetch fresh balance for emergency brake calculation
    # Don't rely on cached chain_start_balance
    if self.executor:
        current_balance = self.executor.get_account_balance()
    else:
        current_balance = self.chain_start_balance

    # Use the LOWER of chain start balance or current balance
    # This prevents over-sizing if balance has dropped mid-chain
    effective_balance = min(self.chain_start_balance, current_balance)

    calculated_size = self.base_size_usd() * (config.MARTINGALE_MULTIPLIER ** self.level) * config.LEVERAGE

    # EMERGENCY BRAKE: Use current/effective balance, not stale cached balance
    max_allowed = effective_balance * config.MAX_POSITION_PCT * config.LEVERAGE

    if calculated_size > max_allowed:
        log(f"🚨 EMERGENCY BRAKE TRIGGERED!", "warning")
        log(f"  Calculated size: ${calculated_size:.2f}", "warning")
        log(f"  Maximum allowed: ${max_allowed:.2f} ({config.MAX_POSITION_PCT*100:.0f}% of ${effective_balance:.2f})", "warning")
        log(f"  Chain start balance: ${self.chain_start_balance:.2f}", "warning")
        log(f"  Current balance: ${current_balance:.2f}", "warning")
        return max_allowed

    return calculated_size
```

---

## 📋 IMPLEMENTATION PRIORITY

### IMMEDIATE (Deploy Today):
1. ✅ **Fix 2A**: Re-enable SMA trend calculation
2. ✅ **Fix 2B**: Add trend alignment filter (block LONG in downtrend)
3. ⚠️ **Fix 3**: Enhance emergency brake with current balance check

### HIGH (Deploy Within 24h):
4. ✅ **Fix 2C**: Add minimum retracement check

### MONITORING:
5. ⚠️ Verify emergency brake is actually capping positions correctly
6. ⚠️ Add logging to track when emergency brake triggers
7. ⚠️ Monitor for any trades that exceed 25% position size

---

## 📊 EXPECTED IMPACT

### Before Fixes:
- Enters LONG in downtrends (wrong direction)
- No trend filter (pure mean-reversion)
- Catches falling knives
- Results: Consecutive losses, deep martingale chains

### After Fixes:
- Blocks LONG when price < SMA (downtrend protection)
- Blocks SHORT when price > SMA (uptrend protection)
- Requires 3% retracement before mean-reversion entry
- Enhanced emergency brake prevents oversizing
- Results: Better win rate, shallower chains, safer trading

---

## 🎯 SUCCESS METRICS

Track these metrics after deployment:
1. **Win Rate**: Should improve from 43% to 50%+
2. **Max Chain Level**: Should stay below Level 5 most of the time
3. **Average Loss Size**: Should decrease (fewer deep chains)
4. **Trend-Aligned Trades**: Should increase significantly
5. **Emergency Brake Triggers**: Should log when activated

---

## ⚠️ ROLLBACK PLAN

If fixes cause issues:
1. Revert changes to `signal_scorer.py`
2. Keep emergency brake enhancement (it's purely protective)
3. Monitor for 24 hours
4. Re-apply fixes one at a time

---

**Document Created**: June 9, 2026
**Status**: Ready for implementation
**Risk Level**: MEDIUM (signal logic changes can affect entry frequency)
**Testing Required**: YES - Monitor first 24 hours closely

