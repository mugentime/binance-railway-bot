# 🚨 Webhook Monitoring System

## Quick Start (2 Minutes)

### 1. Create Discord Webhook
- Discord → Server Settings → Integrations → Webhooks → New Webhook
- Copy URL

### 2. Set Environment Variable
```bash
# Railway
railway variables set WEBHOOK_DISCORD_CRITICAL="https://discord.com/api/webhooks/YOUR_URL"

# Local
export WEBHOOK_DISCORD_CRITICAL="https://discord.com/api/webhooks/YOUR_URL"
```

### 3. Test It
```bash
python src/test_webhooks.py
```

You should see 4 test messages in Discord! ✅

### 4. Run Monitor
```bash
# Run monitoring daemon
python src/monitoring_daemon.py

# Or run alongside bot (Railway Procfile)
web: python src/monitoring_daemon.py & python main_loop.py
```

## What It Does

✅ **Detects missing TP/SL** - Alerts in 5 seconds if position lacks protection
✅ **New position alerts** - Notified when bot opens position
✅ **Position exit alerts** - Notified when position closes
✅ **Catastrophic loss alerts** - Warns on large losses (>$200)
✅ **Works with Discord, Slack, IFTTT** - Send to multiple channels
✅ **Zero bot code changes** - Runs independently

## Alert Example

When position is missing TP:

```
🚨 TP/SL Integrity Violation

Symbol: BTCUSDT
Direction: LONG
Entry Price: $65,432.50
Has Take Profit: ❌ No
Has Stop Loss: ✅ Yes
Time Without Protection: 45 seconds

binance-railway-bot | production
```

## Files

```
src/
├── notifications/
│   ├── webhook_notifier.py    # Core webhook sender
│   ├── event_schemas.py       # Event types
│   └── formatters.py          # Discord/Slack formatting
├── monitoring_daemon.py       # Main monitor (runs separately)
└── test_webhooks.py           # Test script

config/
└── webhook_config.py          # Config loader

docs/
└── MONITORING_SETUP.md        # Full documentation
```

## Configuration

### Required (pick one)
```bash
WEBHOOK_DISCORD_CRITICAL=https://discord.com/api/webhooks/...
# OR
WEBHOOK_SLACK_CRITICAL=https://hooks.slack.com/services/...
# OR
WEBHOOK_IFTTT_CRITICAL=https://maker.ifttt.com/trigger/...
# OR
WEBHOOK_CUSTOM_CRITICAL=https://your-api.com/webhooks
```

### Optional
```bash
MONITORING_CHECK_INTERVAL=30              # Check every 30 seconds
MONITORING_TP_SL_CHECK_DELAY=5            # Wait 5s after entry
MONITORING_LOSS_THRESHOLD=200.0           # Alert on >$200 loss
WEBHOOK_MAX_RETRIES=3                     # Retry failed webhooks 3x
```

## Deployment

### Railway (Recommended)

**Create `Procfile` in root:**
```
web: python src/monitoring_daemon.py & python main_loop.py
```

**Set webhook:**
```bash
railway variables set WEBHOOK_DISCORD_CRITICAL="..."
```

**Deploy:**
```bash
git add .
git commit -m "Add monitoring system"
git push
```

Railway auto-deploys. Monitor runs alongside bot.

### Local Development

**Terminal 1:**
```bash
python src/monitoring_daemon.py
```

**Terminal 2:**
```bash
python main_loop.py
```

Both run independently.

## Event Types

| Event | Severity | When |
|-------|----------|------|
| TP/SL Integrity | 🔴 CRITICAL | Position missing TP or SL |
| Catastrophic Loss | 🔴 CRITICAL | Loss >$200 USD |
| Position Entry | ℹ️ INFO | New position opened |
| Position Exit | ℹ️ INFO | Position closed |
| Bot Startup | ℹ️ INFO | Monitor started |
| Bot Shutdown | ℹ️ INFO | Monitor stopped |

## Platform Setup

### Discord (Easiest)
1. Server Settings → Integrations → Webhooks
2. New Webhook → Copy URL
3. Set `WEBHOOK_DISCORD_CRITICAL`

### Slack
1. https://api.slack.com/apps → Create App
2. Incoming Webhooks → Activate → Add to channel
3. Copy URL → Set `WEBHOOK_SLACK_CRITICAL`

### IFTTT (Mobile Push)
1. IFTTT → Create → Webhooks trigger
2. Event: `bot_alert`
3. Action: Send notification (mobile)
4. Copy URL → Set `WEBHOOK_IFTTT_CRITICAL`

## Testing

```bash
# Test webhooks
python src/test_webhooks.py

# Check current positions
python src/debug_orders.py

# Run monitor locally
python src/monitoring_daemon.py
```

## Troubleshooting

### No webhooks configured
**Fix:** Set at least one `WEBHOOK_*_CRITICAL` variable

### Health check failed
**Fix:**
- Verify webhook URL is correct
- Test with curl:
  ```bash
  curl -X POST "YOUR_URL" -H "Content-Type: application/json" -d '{"content":"test"}'
  ```

### Not detecting positions
**Fix:**
- Verify bot has open positions: `python src/debug_orders.py`
- Check logs: `railway logs`

## Full Documentation

See [docs/MONITORING_SETUP.md](docs/MONITORING_SETUP.md) for complete guide.

---

**Status:** ✅ Production Ready
**Dependencies:** 0 new (uses existing httpx)
**Setup Time:** 2-5 minutes
**Bot Code Changes:** 0 (runs independently)
