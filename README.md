# Binance Trading Bot - Advanced Edition

Complete automated trading bot for Binance Futures with martingale position sizing, time-based exits, and intelligent signal scoring.

## 🚀 Quick Deploy to Railway

1. **Create Railway Project:**
   ```bash
   railway login
   railway init
   ```

2. **Configure Environment Variables in Railway Dashboard:**
   ```
   BINANCE_API_KEY=your_key_here
   BINANCE_API_SECRET=your_secret_here
   ```

3. **Deploy:**
   ```bash
   railway up
   ```

## ✨ Strategy Features

### Time-Based Exit System
- **Break-Even Protection:** Closes at market after 12 candles (1 hour) if PnL is negative
- **Timeout:** Force closes at market after 54 candles (4.5 hours)
- **No percentage stop loss** - `SL_PCT = 1` (100%, disabled)

### Take Profit
- **2% TP** via LIMIT order (maker fee optimization)

### Martingale Position Sizing
- **Base size:** $0.50 per trade at 20x leverage
- **Multiplier:** 1.5x per level
- **Max levels:** 10
- **Cooldown:** 4 candles after loss (blacklist)

### Signal Scoring
Composite score from 6 indicators:
- RSI (30%)
- Bollinger Bands (20%)
- Z-Score (15%)
- Volume (15%)
- Spread (15%)
- Funding Rate (5%)

### Additional Features
- **Regime Detection:** Auto-switches between inverted/normal signals based on BTC volatility
- **MAE Tracking:** Maximum Adverse Excursion monitoring
- **Multi-Layer Filtering:** ATR, spread, slippage checks
- **State Persistence:** Crash recovery with JSON state file
- **Startup Verification:** Checks exchange positions on startup

## 📋 Configuration

### Default Parameters
```python
BASE_SIZE_USD = 0.5           # $0.50 margin per trade
LEVERAGE = 20                 # 20x leverage
MAX_LEVEL = 10                # 10 martingale levels
TP_PCT = 0.020                # 2% take profit
SL_PCT = 1                    # 100% (disabled)
MAX_HOLD_CANDLES = 54         # 4.5 hours timeout
SCAN_INTERVAL_SECS = 300      # 5 minute candles
MIN_24H_VOLUME_USD = 10_000_000  # $10M+ volume filter
```

### Override via Environment
```
BASE_SIZE_USD=0.5
MAX_LEVEL=10
LEVERAGE=20
TP_PCT=0.020
SL_PCT=1
MAX_HOLD_CANDLES=54
SCAN_INTERVAL_SECS=300
```

## 🛡️ Safety Features

- **BTC Correlation Filter:** Pauses longs/shorts based on BTC 4h movement
- **Daily Loss Limit:** $1000 (effectively disabled by default)
- **Leverage Restrictions:** Skips pairs with unsupported leverage
- **Spread Filter:** Max 0.05% spread
- **Slippage Check:** Max 0.1% estimated slippage
- **Volume Filter:** Min $10M 24h volume

## 📊 Structure

```
binance-railway-bot/
├── src/
│   ├── main_loop.py          # Main orchestrator
│   ├── config.py             # Configuration
│   ├── martingale_manager.py # State machine
│   ├── order_executor.py     # Binance API
│   ├── pair_scanner.py       # Market scanning
│   ├── signal_scorer.py      # Signal scoring
│   ├── safety_checks.py      # Safety filters
│   └── utils.py              # Utilities
├── Procfile                   # Railway worker
├── railway.json               # Railway config
├── requirements.txt           # Dependencies
├── runtime.txt               # Python 3.11.9
└── .env                      # Local credentials
```

## 🔧 Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run bot
python src/main_loop.py
```

## 📈 Monitoring

### Railway Dashboard
- Real-time logs
- CPU/Memory usage
- Restart events

### Bot Logs
- Candle wait times
- Signal detection
- Position entries/exits
- MAE tracking
- Win/loss records
- Statistics summaries

## ⚠️ Important Notes

### API Key Permissions
**Required:**
- ✅ Enable Futures Trading
- ✅ Enable Reading

**DO NOT Enable:**
- ❌ Withdrawals
- ❌ Spot Trading (unless needed)

### Railway Persistent Volume
State file requires persistent storage:
- Mount volume at `/data`
- State saved to `/data/state.json`
- Survives restarts

### Graceful Shutdown
Bot handles SIGTERM/SIGINT:
- Saves current state
- Preserves position data
- Safe for Railway restarts

## 🐛 Troubleshooting

### Bot Not Starting
Check Railway logs for errors:
- API credentials correct?
- Binance API accessible?
- Dependencies installed?

### Position State Mismatch
Bot verifies on startup:
- Compares local state with exchange
- Adopts exchange position if mismatch
- Logs warnings for manual review

### Timeout Errors
- Time synchronization issues
- Usually auto-resolves
- Check Railway service status

## 📚 Documentation

- **Strategy Details:** See `docs/STRATEGY.md`
- **Deployment Guide:** Railway setup instructions
- **API Reference:** Binance Futures API docs

## ⚠️ Disclaimer

**Cryptocurrency trading carries significant risk. This software is provided as-is for educational purposes. Use at your own risk. Never trade with money you cannot afford to lose.**

## 🔐 Security

- Never commit `.env` file
- Use API key restrictions (futures only)
- Enable IP whitelist if possible
- Monitor for unauthorized access

--- ## Logging
  Comprehensive logging system for tracking all bot activities.

**Version:** 1.0.0 (Complete Migration)
**Last Updated:** March 26, 2026
**Railway Optimized** ✅


  ## Monitoring
  Bot includes real-time monitoring capabilities.
