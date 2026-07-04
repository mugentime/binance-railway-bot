"""
Test webhook notifications
"""
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, '.')

from notifications import (
    WebhookNotifier,
    PositionEntryEvent,
    TPSLIntegrityEvent,
    CatastrophicLossEvent
)
from config.webhook_config import load_webhook_config, get_notifier_settings
from utils import log


async def test_webhooks():
    """Test all webhook event types"""
    log("=" * 80)
    log("TESTING WEBHOOK NOTIFICATIONS")
    log("=" * 80)

    # Load config
    webhook_config = load_webhook_config()
    notifier_settings = get_notifier_settings()

    total_webhooks = sum(len(urls) for urls in webhook_config.values())
    if total_webhooks == 0:
        log("\n❌ ERROR: No webhooks configured!")
        log("\nSet environment variables like:")
        log("  WEBHOOK_DISCORD_CRITICAL=https://discord.com/api/webhooks/...")
        log("  WEBHOOK_SLACK_WARNING=https://hooks.slack.com/...")
        return

    log(f"\nFound {total_webhooks} configured webhook(s):")
    for severity, urls in webhook_config.items():
        if urls:
            log(f"  {severity.upper()}: {len(urls)} webhook(s)")

    # Initialize notifier
    notifier = WebhookNotifier(webhook_config, **notifier_settings)

    try:
        # Test 1: Health Check
        log("\n" + "=" * 80)
        log("TEST 1: Health Check")
        log("=" * 80)
        health = await notifier.health_check()
        for webhook_key, status in health.items():
            status_str = "✓ PASS" if status else "✗ FAIL"
            log(f"  {status_str}: {webhook_key}")

        # Test 2: Position Entry Event (INFO)
        log("\n" + "=" * 80)
        log("TEST 2: Position Entry Event (INFO)")
        log("=" * 80)
        entry_event = PositionEntryEvent(
            data={
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry_price": 65432.50,
                "quantity": 0.015,
                "position_value_usd": 981.49,
                "entry_time": datetime.now().isoformat()
            },
            context={
                "test_mode": True,
                "test_number": 2
            }
        )
        await notifier.send_event(entry_event)
        log("  ✓ Event sent")
        await asyncio.sleep(1)

        # Test 3: TP/SL Integrity Event (CRITICAL)
        log("\n" + "=" * 80)
        log("TEST 3: TP/SL Integrity Event (CRITICAL)")
        log("=" * 80)
        integrity_event = TPSLIntegrityEvent(
            data={
                "symbol": "ETHUSDT",
                "direction": "LONG",
                "entry_price": 3250.00,
                "current_price": 3275.00,
                "quantity": 0.5,
                "position_value_usd": 1637.50,
                "unrealized_pnl_usd": 12.50,
                "unrealized_pnl_pct": 0.77,
                "has_take_profit": False,  # ❌ MISSING
                "has_stop_loss": True,
                "tp_price": None,
                "sl_price": 3120.00,
                "time_without_protection_seconds": 45
            },
            context={
                "test_mode": True,
                "test_number": 3
            }
        )
        await notifier.send_event(integrity_event)
        log("  ✓ Event sent")
        await asyncio.sleep(1)

        # Test 4: Catastrophic Loss Event (CRITICAL)
        log("\n" + "=" * 80)
        log("TEST 4: Catastrophic Loss Event (CRITICAL)")
        log("=" * 80)
        loss_event = CatastrophicLossEvent(
            data={
                "symbol": "SOLUSDT",
                "loss_amount": 245.50,
                "loss_percentage": 12.3,
                "trigger_threshold": 200.0,
                "account_balance_before": 1995.67,
                "account_balance_after": 1750.17,
                "action_taken": "ALERT_ONLY (test mode)"
            },
            context={
                "test_mode": True,
                "test_number": 4
            }
        )
        await notifier.send_event(loss_event)
        log("  ✓ Event sent")

        # Show metrics
        log("\n" + "=" * 80)
        log("WEBHOOK METRICS")
        log("=" * 80)
        metrics = notifier.get_metrics()
        log(f"  Total sent: {metrics['sent']}")
        log(f"  Total failed: {metrics['failed']}")
        log(f"  Total retries: {metrics['retries']}")
        log(f"  By severity:")
        for severity, count in metrics['by_severity'].items():
            log(f"    {severity}: {count}")

        log("\n" + "=" * 80)
        log("✅ ALL TESTS COMPLETE")
        log("=" * 80)
        log("\nCheck your Discord/Slack/IFTTT to verify you received the test notifications!")

    except Exception as e:
        log(f"\n❌ ERROR: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(test_webhooks())
