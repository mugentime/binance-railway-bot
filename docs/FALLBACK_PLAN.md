# FALLBACK PLAN — Revert to Martingale Single-Position Bot
# Last known profitable config: +15.9% over 4 days (Apr 28–May 1, 2026)
# $12.56 → $14.56 | Net +$2.00 | 60% WR | Profit factor 3.11
# Avg win $0.85 vs avg loss $0.27 | 3 winning days, 2 losing days

## What changed in the new deployment
- Removed Martingale escalation → flat sizing every trade
- Single position → unlimited simultaneous positions
- MAX_HOLD_CANDLES: 54 (2.25h) → 144 (6h)
- 418/429 retry fix in verify_and_sync_state

## To revert EVERYTHING (nuclear option)
```bash
cd C:\Users\je2al\Desktop\binance-railway-bot
git log --oneline -5
# Find the commit hash BEFORE "refactor: multi-position flat sizing"
# It will be the "fix: extend MAX_HOLD_CANDLES" commit
git revert HEAD --no-edit
git push
```

## To revert ONLY multi-position (keep timeout + 418 fix)
```bash
cd C:\Users\je2al\Desktop\binance-railway-bot
git revert HEAD --no-edit
git push
```
This reverts the multi-position commit but keeps:
- MAX_HOLD_CANDLES = 144 (6h timeout)
- 418/429 retry propagation fix

## To revert to EXACT last profitable state
```bash
cd C:\Users\je2al\Desktop\binance-railway-bot
# List recent commits to find the right hash
git log --oneline -10
# Reset to the commit BEFORE the 418 fix (the exact deployed code that made 8.1%)
git checkout <COMMIT_HASH> -- src/main_loop.py src/config.py src/safety_checks.py src/utils.py
git checkout <COMMIT_HASH> -- src/martingale_manager.py
# Remove the new file
git rm src/position_manager.py
git commit -m "revert: fallback to last profitable Martingale config"
git push
```

## Key parameters from profitable run
```
TP_PCT = 0.10           # 10%
SL_PCT = 0.04           # 4%
MAX_HOLD_CANDLES = 54   # 2.25h (was timeout-closing winners at ~1% profit)
MARTINGALE_MULTIPLIER = 1.5
MAX_LEVEL = 10
BASE_SIZE_PCT = 0.03
LEVERAGE = 20
SCAN_INTERVAL_SECS = 150
ENTRY_THRESHOLD = 20
```

## IMPORTANT: Before reverting, close all open positions
The new bot may have multiple positions open. Reverting code while positions
are open will cause state mismatch. Steps:
1. Check Binance for all open positions
2. Close them manually or let the bot close them
3. THEN revert code and push

## Decision tree
- New bot losing money fast → revert multi-position commit (option 2)
- New bot stable but worse than before → give it 48h, then revert if still worse
- New bot crashing → check if it's the old 418 bug or new bug, fix accordingly
- Want to test with limits first → change MAX_POSITIONS from 0 to 2 or 3 in config.py
