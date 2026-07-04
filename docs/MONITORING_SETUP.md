# Webhook Monitoring System - Setup Guide

## Overview

Independent webhook-based monitoring system that:
- ✅ Monitors positions for missing TP/SL orders
- ✅ Detects new positions and exits
- ✅ Sends real-time alerts via Discord, Slack, IFTTT, or custom webhooks
- ✅ Runs independently (doesn't modify bot code)
- ✅ Zero additional dependencies (uses existing `httpx`)

## Architecture

```
┌─────────────────────────────┐
│   Trading Bot (main_loop)   │  ← Unchanged
└─────────────────────────────┘

┌─────────────────────────────┐
│  Monitoring Daemon          │  ← NEW (runs separately)
│  - Polls exchange every 30s │
│  - Checks TP/SL integrity   │
│  - Sends webhook alerts     │
└─────────────────────────────┘
           │
           ↓
  ┌────────────────────┐
  │ Webhook Endpoints  │
  ├────────────────────┤
  │ • Discord          │
  │ • Slack            │
  │ • IFTTT            │
  │ • Custom           │
  └────────────────────┘
```

## Quick Start (5 minutes)

### Step 1: Create Discord Webhook (Recommended)

1. Open Discord → Server Settings → Integrations → Webhooks
2. Click "New Webhook"
3. Name it "Binance Trading Bot"
4. Copy the Webhook URL

### Step 2: Set Environment Variable

**Local Testing:**
```bash
export WEBHOOK_DISCORD_CRITICAL="https://discord.com/api/webhooks/YOUR_WEBHOOK_URL"
```

**Railway (Production):**
```bash
railway variables set WEBHOOK_DISCORD_CRITICAL="https://discord.com/api/webhooks/YOUR_WEBHOOK_URL"
```

### Step 3: Test Webhooks

```bash
cd C:\Users\je2al\Desktop\binance-railway-bot
python src/test_webhooks.py
```

**Expected output:**
```
TEST 1: Health Check
  ✓ PASS: critical_https://discord.com/api/...

TEST 2: Position Entry Event (INFO)
  ✓ Event sent

TEST 3: TP/SL Integrity Event (CRITICAL)
  ✓ Event sent

✅ ALL TESTS COMPLETE
```

**Check Discord** - you should see 4 test messages!

### Step 4: Run Monitoring Daemon

**Local:**
```bash
python src/monitoring_daemon.py
```

**Railway (alongside bot):**
```bash
# Option A: Run in same container (background)
python src/monitoring_daemon.py &
python main_loop.py

# Option B: Separate Procfile entry (recommended)
# See "Railway Deployment" section below
```

## Environment Variables

### Required (at least one)

```bash
# Discord (recommended - easiest setup)
WEBHOOK_DISCORD_CRITICAL=https://discord.com/api/webhooks/...
WEBHOOK_DISCORD_WARNING=https://discord.com/api/webhooks/...
WEBHOOK_DISCORD_INFO=https://discord.com/api/webhooks/...

# OR Slack
WEBHOOK_SLACK_CRITICAL=https://hooks.slack.com/services/...
WEBHOOK_SLACK_WARNING=https://hooks.slack.com/services/...

# OR IFTTT (for mobile push notifications)
WEBHOOK_IFTTT_CRITICAL=https://maker.ifttt.com/trigger/bot_alert/with/key/...

# OR Custom endpoint
WEBHOOK_CUSTOM_CRITICAL=https://your-api.com/webhooks/trading
```

### Optional Configuration

```bash
# Webhook settings
WEBHOOK_TIMEOUT=10                    # Request timeout (seconds)
WEBHOOK_MAX_RETRIES=3                 # Max retry attempts
WEBHOOK_RETRY_BACKOFF=2.0             # Exponential backoff multiplier

# Monitoring settings
MONITORING_CHECK_INTERVAL=30          # Check positions every N seconds
MONITORING_TP_SL_CHECK_DELAY=5        # Wait N seconds after entry before checking TP/SL
MONITORING_LOSS_THRESHOLD=200.0       # Alert on losses > $200
MONITORING_WARNING_LOSS=50.0          # Warning on losses > $50
```

## Event Types

### Critical Events (Immediate Alert)

#### TP/SL Integrity Violation
Triggered when position is missing TP or SL orders.

**Example Discord Message:**
```
🚨 Tp Sl Integrity

Symbol: BTCUSDT
Direction: LONG
Entry Price: 65432.5000
Current Price: 65500.0000
Has Take Profit: ❌ No
Has Stop Loss: ✅ Yes
Time Without Protection Seconds: 45

binance-railway-bot | production
```

#### Catastrophic Loss
Triggered when loss exceeds threshold ($200 default).

**Example Discord Message:**
```
🚨 Catastrophic Loss

Symbol: ETHUSDT
Loss Amount: 245.5000
Loss Percentage: 12.3000
Trigger Threshold: 200.0000
Action Taken: stop_all_trading

binance-railway-bot | production
```

### Info Events

#### Position Entry
Triggered when new position is opened.

#### Position Exit
Triggered when position is closed.

## Platform-Specific Setup

### Discord

**Setup:**
1. Server Settings → Integrations → Webhooks → New Webhook
2. Copy URL
3. Set `WEBHOOK_DISCORD_CRITICAL=<url>`

**Features:**
- Rich embeds with colors
- Instant mobile notifications
- Free unlimited webhooks

**Example:**
```bash
WEBHOOK_DISCORD_CRITICAL=https://discord.com/api/webhooks/123456789/abcdefghijklmnop
```

### Slack

**Setup:**
1. Go to https://api.slack.com/apps
2. Create app → Incoming Webhooks → Activate
3. Add to channel
4. Copy URL

**Features:**
- Rich attachments
- Channel routing
- Free for small teams

**Example:**
```bash
WEBHOOK_SLACK_CRITICAL=https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
```

### IFTTT (Mobile Push Notifications)

**Setup:**
1. IFTTT.com → Create → Webhooks (Trigger)
2. Event name: `bot_alert`
3. Action: Notifications (send rich notification to mobile)
4. Copy webhook URL

**Features:**
- iOS/Android push notifications
- SMS fallback
- Google Sheets logging
- Free tier available

**Example:**
```bash
WEBHOOK_IFTTT_CRITICAL=https://maker.ifttt.com/trigger/bot_alert/with/key/YOUR_KEY
```

### Custom Webhook

**Setup:**
Create endpoint that receives POST requests with JSON body.

**Payload Format:**
```json
{
  "event_type": "tp_sl_integrity",
  "timestamp": "2026-07-04T12:34:56.789Z",
  "severity": "critical",
  "bot_id": "binance-railway-bot",
  "environment": "production",
  "data": {
    "symbol": "BTCUSDT",
    "direction": "LONG",
    "has_take_profit": false,
    "has_stop_loss": true,
    ...
  },
  "context": {
    "check_count": 42,
    "known_positions": 1
  }
}
```

**Example:**
```bash
WEBHOOK_CUSTOM_CRITICAL=https://your-api.com/webhooks/trading
```

## Railway Deployment

### Option 1: Procfile (Recommended)

Create `Procfile` in project root:
```
web: python src/monitoring_daemon.py & python main_loop.py
```

This runs both the monitoring daemon and trading bot in the same container.

### Option 2: Separate Service

Create two Railway services:
1. **Trading Bot**: Runs `main_loop.py`
2. **Monitor**: Runs `monitoring_daemon.py`

Both share the same environment variables.

### Option 3: Background Process

Modify `main_loop.py` startup (if you want them truly integrated):
```python
# At the top of main_loop.py
import subprocess
subprocess.Popen(["python", "src/monitoring_daemon.py"])
```

## Testing Locally

### Test 1: Webhook Connectivity
```bash
python src/test_webhooks.py
```

**Expected:** 4 test messages in Discord/Slack

### Test 2: Position Monitoring
```bash
# Terminal 1: Run monitoring
python src/monitoring_daemon.py

# Terminal 2: Open a position manually on Binance
# Or let the bot open a position

# Check Terminal 1 for alerts
```

**Expected output:**
```
🚨 NEW POSITION DETECTED!
  Symbol: BTCUSDT
  Direction: LONG
  Entry: 65432.50
  Amount: 0.015

  Waiting 5s before checking TP/SL...
  ✅ Both TP and SL orders present for BTCUSDT
```

**OR if missing orders:**
```
  ⚠️  WARNING: Missing TP/SL for BTCUSDT!
🚨 CRITICAL: BTCUSDT missing orders - TP: False, SL: True
```

## Monitoring Dashboard

### View Logs
```bash
# Local
tail -f src/monitor.log  # (if you redirect output)

# Railway
railway logs --follow | grep -E "(CRITICAL|WARNING|NEW POSITION)"
```

### Metrics

The daemon tracks metrics:
- Webhooks sent/failed
- Retries
- Events by severity

Access via:
```python
from monitoring_daemon import MonitoringDaemon
daemon = MonitoringDaemon()
metrics = daemon.notifier.get_metrics()
```

## Troubleshooting

### No webhooks configured
```
⚠️  WARNING: No webhooks configured!
```
**Solution:** Set at least one `WEBHOOK_*_CRITICAL` environment variable

### Webhook health check failed
```
⚠️  1 webhook(s) failed health check
```
**Solution:**
- Verify webhook URL is correct
- Check Discord/Slack webhook is not deleted
- Test URL with curl:
  ```bash
  curl -X POST "YOUR_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d '{"content":"Test"}'
  ```

### Monitoring not detecting positions
**Solution:**
- Verify bot has positions open: `python src/debug_orders.py`
- Check monitoring interval (default: 30s)
- Increase logging verbosity

### Railway deployment issues
**Solution:**
- Ensure `Procfile` is in root directory
- Check Railway logs: `railway logs`
- Verify environment variables are set: `railway variables`

## Advanced Configuration

### Multiple Webhooks Per Severity
```bash
# Send critical alerts to both Discord AND Slack
WEBHOOK_DISCORD_CRITICAL=https://discord.com/...
WEBHOOK_SLACK_CRITICAL=https://hooks.slack.com/...
```

### Send All Events to One Webhook
```bash
# This webhook receives ALL severities (critical, warning, info)
WEBHOOK_DISCORD_ALL=https://discord.com/...
```

### Custom Check Interval
```bash
# Check every 15 seconds instead of 30
MONITORING_CHECK_INTERVAL=15
```

### Adjust Loss Thresholds
```bash
# Alert on losses > $100 (default: $200)
MONITORING_LOSS_THRESHOLD=100.0

# Warn on losses > $25 (default: $50)
MONITORING_WARNING_LOSS=25.0
```

## Files Structure

```
binance-railway-bot/
├── src/
│   ├── notifications/
│   │   ├── __init__.py
│   │   ├── webhook_notifier.py      # Core webhook sender
│   │   ├── event_schemas.py         # Event definitions
│   │   └── formatters.py            # Discord/Slack formatters
│   ├── monitoring_daemon.py         # Main monitoring script
│   └── test_webhooks.py             # Test script
├── config/
│   └── webhook_config.py            # Config loader
└── docs/
    └── MONITORING_SETUP.md          # This file
```

## Next Steps

1. ✅ Set up Discord/Slack webhook
2. ✅ Test with `python src/test_webhooks.py`
3. ✅ Run monitoring locally to verify
4. ✅ Deploy to Railway with Procfile
5. ✅ Monitor for 24 hours
6. 🎯 Never miss a missing TP/SL order again!

## Support

- Check logs: `railway logs`
- Test webhooks: `python src/test_webhooks.py`
- Verify positions: `python src/debug_orders.py`
- Check metrics in monitoring_daemon output

---

**System Status:** ✅ Production Ready
**Dependencies:** 0 new (uses existing httpx)
**Setup Time:** ~5 minutes
**Maintenance:** Minimal
