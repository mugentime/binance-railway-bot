# State Synchronization Bug - Fix Documentation

## Problem

The bot's internal state (`state.json`) can become out of sync with actual Binance positions, leading to:
1. Attempts to open multiple positions (violates single-position rule)
2. Lost tracking of open positions
3. Incorrect risk management

## Root Cause

**Race condition between:**
- `manager.enter()` - Updates in-memory state
- `save_state()` - Persists to disk

**If bot crashes/fails between these calls, state is corrupted.**

## Solution: Multi-Layer Protection

### Layer 1: Atomic State Updates

**Current (unsafe):**
```python
manager.enter(symbol, direction, price, qty, score)
save_state(manager)  # ← Can fail, leaving state corrupted
```

**Fixed (atomic):**
```python
# Save state BEFORE entering (pessimistic locking)
manager.enter(symbol, direction, price, qty, score)
try:
    save_state(manager)
except Exception as e:
    # Rollback in-memory state if save fails
    manager._clear_position()
    manager.level -= 1
    raise Exception(f"Failed to save state after entry: {e}")
```

### Layer 2: Before-Entry Safety Check Enhancement

**Add state verification before allowing entry:**
```python
# Before entering new position, verify state is clean
if not manager.in_position:
    # State says no position - verify with exchange
    all_open = executor.get_all_open_positions()
    if all_open:
        # MISMATCH: State says no position, but exchange has positions
        log("STATE MISMATCH: Syncing with exchange before entry", "warning")

        # Adopt the open position instead of entering new one
        exchange_symbol = all_open[0]['symbol']
        position = executor.get_position(exchange_symbol)
        manager.in_position = True
        manager.current_symbol = exchange_symbol
        manager.entry_price = float(position['entryPrice'])
        manager.entry_quantity = abs(float(position['positionAmt']))
        manager.current_direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
        save_state(manager)

        # Skip entry this cycle
        continue
```

### Layer 3: Automatic State Recovery

**Run verification on every cycle start:**
```python
def verify_and_sync_state(manager, executor):
    """
    Verify bot state matches Binance reality
    Auto-correct any discrepancies
    """
    all_open = executor.get_all_open_positions()

    if manager.in_position and not all_open:
        # Bot thinks position open, but exchange says closed
        log("AUTO-RECOVERY: Position closed on exchange, updating state", "warning")
        manager._clear_position()
        save_state(manager)

    elif not manager.in_position and all_open:
        # Bot thinks no position, but exchange has position
        log("AUTO-RECOVERY: Adopting orphaned position from exchange", "warning")
        position = executor.get_position(all_open[0]['symbol'])
        manager.in_position = True
        manager.current_symbol = all_open[0]['symbol']
        manager.entry_price = float(position['entryPrice'])
        manager.entry_quantity = abs(float(position['positionAmt']))
        manager.current_direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
        manager.entry_candle_time = time.time()  # Approximate
        save_state(manager)

    elif manager.in_position and all_open:
        # Both think position open - verify it's the SAME position
        if manager.current_symbol != all_open[0]['symbol']:
            log(f"AUTO-RECOVERY: State mismatch - bot tracks {manager.current_symbol}, "
                f"but exchange shows {all_open[0]['symbol']}", "error")
            # Adopt exchange reality
            position = executor.get_position(all_open[0]['symbol'])
            manager.current_symbol = all_open[0]['symbol']
            manager.entry_price = float(position['entryPrice'])
            manager.entry_quantity = abs(float(position['positionAmt']))
            manager.current_direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
            save_state(manager)
```

### Layer 4: State Backup and Rollback

**Implement state versioning:**
```python
def save_state_with_backup(manager, filepath="state.json"):
    """Save state with backup and atomic write"""
    import shutil
    import tempfile

    # Create backup of current state
    if os.path.exists(filepath):
        shutil.copy2(filepath, f"{filepath}.backup")

    # Write to temp file first
    temp_fd, temp_path = tempfile.mkstemp(suffix=".json")
    try:
        state = {...}  # Same as before
        with os.fdopen(temp_fd, 'w') as f:
            json.dump(state, f, indent=2)

        # Atomic move (overwrites target)
        shutil.move(temp_path, filepath)
        log(f"State saved: level={manager.level}, in_position={manager.in_position}")
    except Exception as e:
        os.unlink(temp_path)
        raise Exception(f"Failed to save state: {e}")
```

## Implementation Priority

1. **Immediate (Critical)**: Implement Layer 3 (Auto-recovery on every cycle)
2. **High**: Enhance Layer 2 (Pre-entry verification)
3. **Medium**: Implement Layer 4 (State backup)
4. **Low**: Refactor Layer 1 (Atomic updates)

## Testing

1. **Manual desync test**: Manually edit `state.json` to mismatch reality
2. **Crash recovery test**: Kill bot between `manager.enter()` and `save_state()`
3. **Network failure test**: Disconnect network after entry, verify recovery

## Monitoring

Add metrics to track:
- `state_sync_errors` - Count of mismatches detected
- `auto_recoveries` - Count of automatic state corrections
- `state_save_failures` - Failed save_state() calls
