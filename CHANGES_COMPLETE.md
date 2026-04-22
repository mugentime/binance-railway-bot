# Complete Change History - Binance Railway Bot

## Configuration Parameter Evolution

| Parameter | Initial | After c0bd336 | After 37b26c2 | After 8967c47 | Current |
|-----------|---------|---------------|---------------|---------------|---------|
| **TP_PCT** | 2.0% | 0.7% | 0.4% | 10.0% | **10.0%** |
| **SL_PCT** | 4.0% | 4.0% | 4.0% | 4.0% | **4.0%** |
| **SCAN_INTERVAL** | 300s (5m) | 150s (2.5m) | 150s | 150s | **150s** |
| **MARTINGALE_MULTIPLIER** | N/A | N/A | 1.5x | 1.5x | **1.5x** |
| **MAX_LEVEL** | 10 | 10 | 3 | 3 | **10** |

---

## Commit History (Newest to Oldest)

### 47f5ac9 + Current Changes (April 21, 2026)
**FIX: SL verification endpoint correction + MAX_LEVEL restore**

**Changes:**
1. Fixed algo orders endpoint in `src/order_executor.py`:
   - Added `get_algo_open_orders()` method
   - Endpoint: `/fapi/v1/openAlgoOrders` (was incorrectly `/fapi/v1/algoOpenOrders`)
   - Changed SL verification to check algo orders instead of regular orders
   - Fixed order type check: `algoType == 'CONDITIONAL'` instead of `'STOP_MARKET'`
   - Uses correct fields: `triggerPrice` and `algoId`

2. Restored MAX_LEVEL in `src/config.py`:
   - Changed from 3 back to 10

**Files Modified:**
- `src/order_executor.py`
- `src/config.py`

**Impact:**
- ✅ Stops false "MISSING SL DETECTED" warnings
- ✅ Prevents duplicate SL order placement
- ✅ Restores full martingale chain capability

---

### 8967c47 (22 hours ago)
**FIX: Restore algo orders for stop loss - fixes error -4120**

**Major Configuration Change:**
- **TP_PCT: 0.4% → 10.0%** (25x increase)

**Changes:**
- Restored algo order endpoint `/fapi/v1/algoOrder` for SL placement
- Changed from `STOP_MARKET` back to `algoType: CONDITIONAL`
- Added automatic SL verification every 5 candles in `src/main_loop.py`
- Added emergency position closure if SL cannot be placed
- Added 24 diagnostic/utility scripts for monitoring

**Files Modified:**
- `src/config.py` (TP_PCT 0.4% → 10.0%)
- `src/main_loop.py` (added SL verification)
- `src/order_executor.py` (restored algo orders)
- `src/utils.py`

**New Scripts Added:**
- `analyze_chain_pnl.py`, `analyze_recent_trades.py`
- `cancel_all_open_orders.py`, `cancel_all_orders.py`
- `cancel_basedusdt_orders.py`, `cancel_chz_order.py`
- `cancel_orphaned_sl_orders.py`, `check_algo_orders.py`
- `check_all_open_orders.py`, `check_all_orders_complete.py`
- `check_beatusdt_orders.py`, `check_biousdt.py`
- `check_conditional_orders.py`, `check_open_orders.py`
- `check_orders.py`, `check_sirenusdt_fills.py`
- `check_sirenusdt_orders.py`, `check_sirenusdt_pnl.py`
- `check_tradoorus_orders_detailed.py`, `diagnose_position_size.py`
- `find_all_open_orders.py`, `find_orphaned_orders.py`
- `get_chain_pnl.py`, `list_and_cancel_algo_orders.py`
- `place_missing_sl.py`

**Problem Solved:**
- Fixed Binance error -4120: "Order type not supported for this endpoint"
- Positions were opening without SL protection
- Certain pairs (TRADOORUSDT, MONUSDT) require algorithmic orders

---

### 37b26c2 (3 days ago)
**CRITICAL FIX: Stop loss not executing - prevent account blowouts**

**Major Configuration Changes:**
- **TP_PCT: 0.7% → 0.4%**
- **MAX_LEVEL: 10 → 3** (NOT APPROVED - reverted in current session)
- **Added MARTINGALE_MULTIPLIER: 1.5x**
- **Added MAX_POSITION_PCT: 0.25** (emergency brake)

**Changes:**
- Changed SL from `STOP_LIMIT` to `STOP_MARKET` (guaranteed execution)
- Removed limit price buffer for SL
- Added emergency position size cap at 25% of account
- Reduced max levels to prevent catastrophic position sizes

**Files Modified:**
- `src/config.py`
- `src/martingale_manager.py` (added emergency brake)
- `src/order_executor.py` (changed SL order type)

**Documentation Added:**
- `CRITICAL_STOP_LOSS_FIX.md`

**Problem Solved:**
- 80% account loss in single trade due to SL failures
- STOP_LIMIT orders not executing when price gaps
- Position sizes at high martingale levels were extreme:
  - Level 7: 1025% of account
  - Level 10: 3460% of account

**Impact:**
- Max position size: 202% (at level 3) vs 3460% before
- Worst case loss: 0.4% vs 80% before
- Stop losses guaranteed to execute

---

### c0bd336 (6 days ago)
**Update config: scan interval to 150sec and martingale multiplier to 3x**

**Configuration Changes:**
- **SCAN_INTERVAL: 300s → 150s** (5min → 2.5min)
- **TP_PCT: 2.0% → 0.7%**
- **MARTINGALE_MULTIPLIER: → 3x** (first introduction)

**Files Modified:**
- `src/config.py`
- `src/martingale_manager.py`

**Impact:**
- Faster scanning for trading opportunities
- Tighter TP target
- More aggressive position sizing on martingale levels

---

### c66ec38 (8 days ago)
**Resolve conflict**
- Merge conflict resolution

---

### cbfa825 (8 days ago)
**Update title to professional Edition**

**Files Modified:**
- `README.md`

---

### 7e04c1d (8 days ago)
**Update title to advanced edition**

**Files Modified:**
- `README.md`

---

### 43c7c58 (8 days ago)
**Merge branch 'feature/add-logging'**
- Merged logging features

---

### 5b17c3a (8 days ago)
**Add logging section to readme**

**Files Modified:**
- `README.md`

---

### b842563 (8 days ago)
**Add monitoring section to readme**

**Files Modified:**
- `README.md`

---

### 3a02aa5 (8 days ago)
**Initial commit: Binance Railway Bot v1.0**

**Initial Configuration:**
- TP_PCT: 2.0%
- SL_PCT: 4.0%
- SCAN_INTERVAL: 300s (5 minutes)
- MAX_LEVEL: 10
- LEVERAGE: 20x

**Files Added (35 total):**
- Core source files: `src/config.py`, `src/main_loop.py`, `src/martingale_manager.py`, `src/order_executor.py`, `src/pair_scanner.py`, `src/safety_checks.py`, `src/signal_scorer.py`, `src/utils.py`
- Documentation: Multiple strategy and analysis docs
- Deployment: `Procfile`, `railway.json`, `requirements.txt`, `runtime.txt`
- Configuration: `.gitignore`, `config/.env.example`
- Scripts: Various diagnostic and testing scripts

---

## Current Configuration (April 21, 2026)

```python
TP_PCT = 0.10                 # 10.0% take profit
SL_PCT = 0.04                 # 4.0% stop loss
SCAN_INTERVAL_SECS = 150      # 2.5 minutes
MARTINGALE_MULTIPLIER = 1.5   # 1.5x per level
MAX_LEVEL = 10                # Max 10 levels
LEVERAGE = 20                 # 20x leverage
BASE_SIZE_PCT = 0.03          # 3% per trade
MAX_POSITION_PCT = 0.25       # 25% emergency brake
```

---

## Key Takeaways

1. **TP_PCT Evolution:** Started at 2.0%, dropped to 0.4%, now at 10.0%
2. **SCAN_INTERVAL:** Reduced from 5min to 2.5min for faster signal detection
3. **MAX_LEVEL:** Started at 10, briefly changed to 3 (not approved), now back to 10
4. **SL Mechanism:** Changed from STOP_LIMIT → STOP_MARKET → algo CONDITIONAL orders
5. **Safety Features:** Added MAX_POSITION_PCT emergency brake, automatic SL verification
6. **Endpoint Fix:** Corrected SL verification to use `/fapi/v1/openAlgoOrders`
