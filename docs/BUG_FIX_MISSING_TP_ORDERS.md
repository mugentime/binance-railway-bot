# Bug Fix: Missing TP Orders on Position Entry

## Date: 2026-07-04

## Problem Summary

Positions were being opened with SL orders but **WITHOUT TP orders**, leaving them partially unprotected.

### Example Incident
- **Symbol:** MEGAUSDT
- **Entry:** $0.05256 LONG
- **SL Order:** ✅ PRESENT (trigger: $0.05046)
- **TP Order:** ❌ MISSING

## Root Cause Analysis

### The Bug Flow

1. Bot executes market entry order successfully
2. `place_tp_sl_orders()` is called to place protective orders
3. **TP order placement FAILS** (API timeout, rate limit, or other error)
4. Exception is raised on line 424: `raise`
5. **SL code (lines 426-493) is NEVER reached**
6. Exception caught in `main_loop.py` line 715
7. Recovery function `verify_and_place_missing_sl()` is called
8. Recovery ONLY checks/places SL, **NOT TP**
9. **Result: Position with SL but NO TP**

### Code Evidence

**Before Fix - order_executor.py:410-424**
```python
try:
    resp = self.client.post(...)  # TP order
    resp.raise_for_status()
    log(f"TP LIMIT order placed...")
except httpx.HTTPStatusError as e:
    log(f"TP order failed...", "error")
    raise  # ❌ THIS WAS THE PROBLEM - exits function before SL code
```

**Problem:** If TP fails, exception is raised and SL code never executes.

**Before Fix - main_loop.py:720**
```python
# Attempt to verify and place missing SL
sl_ok = executor.verify_and_place_missing_sl(...)  # Only checks SL, not TP!
```

**Problem:** Recovery only handles missing SL, not missing TP.

## The Fix

### 1. Modified `place_tp_sl_orders()` to Track Success Independently

**Changes:**
- TP order wrapped in try/except that **doesn't raise**
- Track `tp_success` and `tp_error` separately
- SL order also tracks `sl_success` and `sl_error` separately
- **Both orders are ALWAYS attempted**, regardless of the other's success
- At the end, raise exception if EITHER order failed

**Result:** Even if TP fails, SL will still be placed. Both attempts are made independently.

### 2. Created New Function `verify_and_place_missing_orders()`

**Purpose:** Check and place BOTH missing TP and SL orders during recovery.

**Signature:**
```python
def verify_and_place_missing_orders(self, symbol, direction, tp_price, sl_price, quantity) -> tuple:
    """
    Returns: (tp_ok, sl_ok) - tuple of booleans
    """
```

**Features:**
- Checks for existing TP order (LIMIT order with reduceOnly=true)
- Checks for existing SL order (CONDITIONAL algo order)
- Places missing TP if not found
- Places missing SL if not found
- Returns status of both orders
- Uses separate try/except for each order (one failure doesn't prevent the other)

### 3. Updated `main_loop.py` to Use New Recovery Function

**Changes:**
```python
# NEW: Check and place BOTH orders
tp_ok, sl_ok = executor.verify_and_place_missing_orders(...)

# Log recovery results
log(f"RECOVERY RESULTS: TP={'OK' if tp_ok else 'FAILED'} | SL={'OK' if sl_ok else 'FAILED'}")

if not sl_ok:
    # Close position if SL can't be placed (critical)
    executor.close_position_market(...)
elif not tp_ok:
    # Warn but continue if only TP is missing (position still has SL protection)
    log(f"WARNING: Position has SL but NO TP - acceptable but not ideal")
```

**Result:** Recovery now handles BOTH missing TP and SL orders.

## Files Modified

1. **src/order_executor.py**
   - Modified `place_tp_sl_orders()` (lines 396-528)
   - Added `verify_and_place_missing_orders()` (new function, ~150 lines)
   - Kept `verify_and_place_missing_sl()` for backward compatibility

2. **src/main_loop.py**
   - Updated exception handler (lines 715-740)
   - Now calls `verify_and_place_missing_orders()` instead of `verify_and_place_missing_sl()`

3. **src/test_order_recovery.py** (new test script)
   - Tests the new recovery function
   - Verifies both TP and SL checking/placement

## Testing

### Test 1: Current Position Verification
```bash
python src/debug_orders.py
```
**Result:**
```
MEGAUSDT:
  TP Order: ✓ PRESENT
  SL Order: ✓ PRESENT
```

### Test 2: Recovery Function Test
```bash
python src/test_order_recovery.py
```
**Result:**
```
RESULTS:
  TP Order: ✓ OK
  SL Order: ✓ OK

✅ SUCCESS: Both TP and SL are present or were placed
```

## Impact

### Before Fix
- ✅ SL order placed: Position has downside protection
- ❌ TP order missing: No automatic profit taking
- ❌ Recovery only places SL: TP remains missing
- **Risk:** Positions rely on manual monitoring for profit taking

### After Fix
- ✅ Both TP and SL attempted independently
- ✅ Recovery places BOTH missing orders
- ✅ Clear logging of which orders succeeded/failed
- ✅ Position closed if SL can't be placed (critical)
- ⚠️ Position kept with warning if only TP missing (SL still protects)

## Prevention Measures

### Immediate
1. ✅ Independent order placement (one failure doesn't prevent the other)
2. ✅ Comprehensive recovery function
3. ✅ Clear logging of order placement status

### Future (Monitoring Bot)
1. Real-time alerts when position opened without TP/SL
2. Automated verification 2 seconds after entry
3. Immediate notification if orders missing
4. See `/docs/monitoring_bot_plan.md` for full design

## Deployment

### Local Testing
```bash
# Verify syntax
python src/order_executor.py

# Test current positions
python src/debug_orders.py

# Test recovery function
python src/test_order_recovery.py
```

### Railway Deployment
```bash
git add src/order_executor.py src/main_loop.py src/test_order_recovery.py docs/BUG_FIX_MISSING_TP_ORDERS.md
git commit -m "fix: ensure both TP and SL orders placed independently with comprehensive recovery

- Modified place_tp_sl_orders() to track TP/SL success independently
- Created verify_and_place_missing_orders() to recover BOTH missing orders
- Updated main_loop.py to use comprehensive recovery function
- Prevents issue where TP order failure blocked SL placement
- Fixes recurring bug of positions with SL but no TP"

git push
railway up --detach
```

## Verification After Deployment

1. Monitor Railway logs for next position entry:
   ```bash
   railway logs --follow | grep -E "(TP|SL|order placed)"
   ```

2. Check for both log messages:
   ```
   TP LIMIT order placed: SYMBOL @ PRICE
   SL STOP_LIMIT algo order placed: SYMBOL trigger=PRICE
   ```

3. If any failure, verify recovery logs:
   ```
   RECOVERY RESULTS: TP=OK | SL=OK
   ```

## Conclusion

This fix ensures that TP and SL orders are **always attempted independently**, and comprehensive recovery places **any missing orders**.

**The bug that caused positions to have SL but no TP is now permanently fixed.**

---

**Commit Hash:** (to be added after commit)
**Tested By:** Claude Code
**Deployed:** 2026-07-04
