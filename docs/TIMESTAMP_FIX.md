# Timestamp Synchronization Fix

## Issue Analysis

The bot crashed with a 400 Bad Request error from Binance API during state verification:

```
2026-05-11 00:00:02,732 [INFO] Time synced with Binance server (offset: -258ms)
2026-05-11 00:00:07,810 [ERROR] Error getting all positions: Client error '400 Bad Request'
```

### Root Cause

1. **Missing `recvWindow` parameter**: Binance API requires timestamps to be within a specific window (default 5000ms)
2. **Time drift during execution**: 5 seconds elapsed between time sync and the API request
3. **Large time offset**: -258ms offset combined with execution delay pushed the timestamp outside acceptable range

### Binance Timestamp Errors

- **Error -1021**: "Timestamp for this request is outside of the recvWindow"
- **Error -1022**: "Invalid signature" (can be caused by time drift)

## Fixes Implemented

### 1. Added `recvWindow` Parameter (src/order_executor.py:41-61)

```python
def _sign_params(self, params: dict) -> dict:
    # ... existing code ...

    # Add recvWindow for tolerance (20 seconds to handle network delays)
    # Binance default is 5000ms, we increase to 20000ms for reliability
    if "recvWindow" not in params:
        params["recvWindow"] = 20000
```

**Impact**: Increases timestamp tolerance from 5 seconds to 20 seconds, preventing timestamp errors during network delays.

### 2. Automatic Retry with Time Resync

Added retry logic for timestamp errors in:
- `get_all_open_positions()`
- `get_position()`

```python
except httpx.HTTPStatusError as e:
    if e.response.status_code == 400:
        error_data = e.response.json()
        error_code = error_data.get('code')

        if error_code in [-1021, -1022] and attempt < max_retries - 1:
            log(f"Timestamp error: Resyncing time and retrying...", "warning")
            self._sync_server_time()  # Force time resync
            time.sleep(0.5)  # Brief delay before retry
            continue
```

**Impact**: Automatically recovers from timestamp errors by resyncing with Binance servers and retrying the request.

## Testing Recommendations

1. **Monitor logs** for timestamp warnings during operation
2. **Check Railway logs** for improved error recovery
3. **Verify** that 400 errors with code -1021/-1022 now trigger automatic recovery

## Expected Behavior After Fix

- ✅ Timestamp errors automatically trigger time resync
- ✅ Requests retry after resync with fresh timestamp
- ✅ 20-second tolerance window prevents errors during network delays
- ✅ Bot continues running instead of crashing on timestamp issues

## If Issues Persist

If timestamp errors continue:
1. Check system clock synchronization on Railway server
2. Verify network latency to Binance API (should be <1s)
3. Consider increasing `recvWindow` further (max 60000ms)
4. Check Railway logs for repeated timestamp warnings
