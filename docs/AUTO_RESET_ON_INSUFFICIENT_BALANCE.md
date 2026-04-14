# Auto-Reset on Insufficient Balance

**Date:** 2026-04-06
**Status:** ✅ IMPLEMENTED AND TESTED

## Feature Overview

The bot now **automatically resets to Level 0** when it detects insufficient balance to continue the martingale sequence.

## Problem Solved

**Before:**
```
Bot reaches Level 8
Required margin: $61.37
Available balance: $53.21
Result: Bot gets STUCK - can't trade, can't reset
User must manually reset state.json
```

**After:**
```
Bot reaches Level 8
Required margin: $61.37
Available balance: $53.21
Result: Bot AUTO-RESETS to Level 0
Next cycle starts fresh with smaller position size
```

## How It Works

### 1. Balance Check (Every Cycle)

Before attempting to enter a new position:
```python
available_balance = get_account_balance()
required_margin = position_size * 1.5  # 1.5x buffer

if available_balance < required_margin:
    # Trigger auto-reset
```

### 2. Auto-Reset Logic

When insufficient balance detected:
```python
if manager.level > 0:
    manager.reset_to_level_zero(
        reason="Insufficient balance ($53.21 < $61.37)"
    )
    save_state(manager)
```

### 3. State Reset

The reset clears:
- ✅ Level → 0
- ✅ Position state (if any)
- ✅ Balance cache
- ✅ MAE tracking

The reset preserves:
- ✅ Trade history
- ✅ Cooldown blacklist

## Example Scenario

### Scenario: Level 8 Blowout

1. **Starting State:**
   - Level: 8
   - Balance: $53.21
   - Required for Level 8: $61.37

2. **Balance Check:**
   ```
   [WARNING] Insufficient balance: $53.21 < $61.37 required
   [WARNING] RESET TO LEVEL 0: Insufficient balance ($53.21 < $61.37)
   [WARNING]   Previous level: 8
   [WARNING]   Clearing position state and balance cache
   [INFO]     Trade history preserved (12 trades)
   [INFO]     Cooldown blacklist preserved (3 symbols)
   [WARNING] State reset to level 0 and saved
   ```

3. **Next Cycle:**
   - Level: 0 (fresh start)
   - Position size: $1.60 (3% of balance)
   - Required margin: $2.40
   - Available: $53.21 ✅
   - Can trade: YES

## Benefits

### 1. No Manual Intervention
- Bot handles insufficient balance automatically
- No need to SSH in and edit state.json
- Reduces downtime

### 2. Graceful Recovery
- Preserves trade history for analysis
- Keeps cooldown blacklist (avoids bad pairs)
- Clean restart at Level 0

### 3. Prevents Stuck States
- Bot can't get permanently blocked
- Always recovers to tradeable state
- Continues operating after balance issues

## Edge Cases Handled

### Case 1: Already at Level 0
```python
if manager.level > 0:
    reset_to_level_zero()
else:
    log("Already at level 0, cannot trade with current balance")
    # Blocks trading but doesn't reset (nothing to reset)
```

### Case 2: Position Currently Open
- Auto-reset only triggers when **no position is open**
- If position is open, waits for TP/SL to close first
- Then checks balance before next entry

### Case 3: Balance Check Fails
```python
except Exception as e:
    log(f"Balance check failed: {e}")
    return False  # Block trading, don't reset (safety)
```

## Testing

Run the test script:
```bash
python scripts/test_insufficient_balance_reset.py
```

Expected output:
```
[TEST CONDITION MET] Balance IS insufficient for level 8
  Expected: Bot will auto-reset to level 0

[SUCCESS] Auto-reset worked correctly!
  - Manager level reset to 0
  - State saved to disk
  - Next bot cycle will start at level 0
```

## Logs to Watch For

### Normal Operation (Sufficient Balance)
```
[INFO] Balance check passed: $100.50 available, $61.37 required
```

### Auto-Reset Triggered
```
[WARNING] Insufficient balance: $53.21 < $61.37 required
[WARNING] RESET TO LEVEL 0: Insufficient balance ($53.21 < $61.37)
[WARNING] State reset to level 0 and saved
```

### Next Cycle After Reset
```
[INFO] CYCLE START | Level=0 | In position=False
[INFO] BALANCE: $53.21 → Base size = $1.60 (3.0%)
```

## Files Modified

1. **`src/martingale_manager.py`**
   - Added `reset_to_level_zero()` method (lines 247-260)

2. **`src/safety_checks.py`**
   - Import `save_state` (line 8)
   - Updated `check_balance()` with auto-reset logic (lines 84-104)

3. **`scripts/test_insufficient_balance_reset.py`**
   - Test script to verify auto-reset functionality

4. **`docs/AUTO_RESET_ON_INSUFFICIENT_BALANCE.md`**
   - This documentation

## Configuration

No configuration needed. Auto-reset is always enabled when:
- Balance check runs (every cycle before entry)
- Insufficient balance detected
- Manager level > 0

## Summary

✅ **Feature:** Auto-reset to Level 0 on insufficient balance
✅ **Trigger:** Balance check fails before trade entry
✅ **Action:** Reset level, clear state, save to disk
✅ **Result:** Bot recovers gracefully and continues operating
✅ **Status:** Implemented, tested, production-ready

---

**No more manual state.json editing when you run out of balance!**
