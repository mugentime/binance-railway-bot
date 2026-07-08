"""
Independent monitoring daemon for Binance trading bot
Runs separately, doesn't modify bot code
Monitors positions and sends webhook notifications
"""
import sys
import asyncio
import time
from datetime import datetime
from typing import Set, Dict, Optional
import traceback

sys.path.insert(0, '.')

from order_executor import OrderExecutor
from utils import log
import config
from notifications import (
    WebhookNotifier,
    PositionEntryEvent,
    PositionExitEvent,
    TPSLIntegrityEvent,
    CatastrophicLossEvent,
    BotStartupEvent,
    BotShutdownEvent
)
from config.webhook_config import load_webhook_config, get_notifier_settings, get_monitoring_settings


class MonitoringDaemon:
    """Independent monitoring daemon"""

    def __init__(self):
        self.executor = OrderExecutor()
        self.webhook_config = load_webhook_config()
        self.notifier_settings = get_notifier_settings()
        self.monitoring_settings = get_monitoring_settings()

        self.notifier: Optional[WebhookNotifier] = None
        self.known_positions: Set[str] = set()
        self.position_entry_times: Dict[str, float] = {}
        self.running = False
        self.check_count = 0

    async def initialize(self):
        """Initialize notifier and send startup event"""
        # Check if any webhooks configured
        total_webhooks = sum(len(urls) for urls in self.webhook_config.values())
        if total_webhooks == 0:
            log("⚠️  WARNING: No webhooks configured! Set WEBHOOK_DISCORD_CRITICAL or similar env vars", "warning")
            log("Monitoring will run but no notifications will be sent", "warning")
        else:
            log(f"✓ Configured {total_webhooks} webhook(s)")
            for severity, urls in self.webhook_config.items():
                if urls:
                    log(f"  {severity}: {len(urls)} webhook(s)")

        self.notifier = WebhookNotifier(self.webhook_config, **self.notifier_settings)

        # Test webhooks
        log("\nTesting webhook connectivity...")
        health = await self.notifier.health_check()
        failures = sum(1 for ok in health.values() if not ok)
        if failures > 0:
            log(f"⚠️  {failures} webhook(s) failed health check", "warning")
        else:
            log("✓ All webhooks passed health check")

        # Send startup event
        startup_event = BotStartupEvent(
            data={
                "started_at": datetime.now().isoformat(),
                "check_interval_seconds": self.monitoring_settings["check_interval"],
                "webhooks_configured": total_webhooks
            }
        )
        await self.notifier.send_event(startup_event)

    async def check_tp_sl_integrity(self, symbol: str, position_data: dict) -> bool:
        """
        Check if position has both TP and SL orders
        Returns: True if both present, False otherwise
        """
        amt = float(position_data.get('positionAmt', 0))
        entry = float(position_data.get('entryPrice', 0))
        direction = "LONG" if amt > 0 else "SHORT"
        quantity = abs(amt)

        # Check TP (regular LIMIT order with reduceOnly)
        has_tp = False
        tp_price = None
        try:
            orders = self.executor.get_open_orders(symbol)
            for order in orders:
                if order.get('reduceOnly') and order.get('type') == 'LIMIT':
                    has_tp = True
                    tp_price = float(order.get('price', 0))
                    break
        except Exception as e:
            log(f"Error checking TP orders for {symbol}: {e}", "error")

        # Check SL (regular STOP_MARKET reduceOnly order)
        has_sl = False
        sl_price = None
        try:
            orders = self.executor.get_open_orders(symbol)
            for order in orders:
                if order.get('type') == 'STOP_MARKET' and order.get('reduceOnly'):
                    has_sl = True
                    sl_price = float(order.get('stopPrice', 0))
                    break
        except Exception as e:
            log(f"Error checking SL orders for {symbol}: {e}", "error")

        # If either is missing, send critical alert
        if not has_tp or not has_sl:
            log(f"🚨 CRITICAL: {symbol} missing orders - TP: {has_tp}, SL: {has_sl}", "error")

            # Calculate unrealized PnL
            mark_price = float(position_data.get('markPrice', entry))
            if direction == "LONG":
                pnl_pct = ((mark_price - entry) / entry) * 100
            else:
                pnl_pct = ((entry - mark_price) / entry) * 100
            pnl_usd = abs(amt) * (mark_price - entry) if direction == "LONG" else abs(amt) * (entry - mark_price)

            integrity_event = TPSLIntegrityEvent(
                data={
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry,
                    "current_price": mark_price,
                    "quantity": quantity,
                    "position_value_usd": abs(amt) * mark_price,
                    "unrealized_pnl_usd": pnl_usd,
                    "unrealized_pnl_pct": pnl_pct,
                    "has_take_profit": has_tp,
                    "has_stop_loss": has_sl,
                    "tp_price": tp_price if has_tp else None,
                    "sl_price": sl_price if has_sl else None,
                    "time_without_protection_seconds": int(time.time() - self.position_entry_times.get(symbol, time.time()))
                },
                context={
                    "check_count": self.check_count,
                    "known_positions": len(self.known_positions)
                }
            )
            await self.notifier.send_event(integrity_event)
            return False

        return True

    async def monitor_loop(self):
        """Main monitoring loop"""
        log("=" * 80)
        log("MONITORING DAEMON - Starting...")
        log("=" * 80)
        log(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log(f"Check interval: {self.monitoring_settings['check_interval']} seconds")
        log(f"TP/SL check delay: {self.monitoring_settings['tp_sl_check_delay']} seconds after entry")
        log(f"Press Ctrl+C to stop\n")

        self.running = True

        try:
            # Initialize known positions
            try:
                positions = self.executor.get_all_open_positions()
                for pos in positions:
                    symbol = pos.get('symbol')
                    self.known_positions.add(symbol)
                    self.position_entry_times[symbol] = time.time()
                    log(f"Initial position tracked: {symbol}")
            except Exception as e:
                log(f"Error initializing positions: {e}", "error")

            log(f"\nMonitoring started. Known positions: {len(self.known_positions)}")
            log("-" * 80)

            while self.running:
                self.check_count += 1
                current_time = datetime.now().strftime('%H:%M:%S')

                try:
                    # Get current positions
                    positions = self.executor.get_all_open_positions()
                    current_symbols = {pos.get('symbol') for pos in positions}

                    # Check for NEW positions
                    new_symbols = current_symbols - self.known_positions

                    if new_symbols:
                        log(f"\n🚨 NEW POSITION DETECTED!")
                        for symbol in new_symbols:
                            # Find the position data
                            pos_data = next((p for p in positions if p.get('symbol') == symbol), None)
                            if pos_data:
                                amt = float(pos_data.get('positionAmt', 0))
                                entry = float(pos_data.get('entryPrice', 0))
                                direction = "LONG" if amt > 0 else "SHORT"

                                log(f"  Symbol: {symbol}")
                                log(f"  Direction: {direction}")
                                log(f"  Entry: {entry}")
                                log(f"  Amount: {amt}")

                                # Send position entry event
                                entry_event = PositionEntryEvent(
                                    data={
                                        "symbol": symbol,
                                        "direction": direction,
                                        "entry_price": entry,
                                        "quantity": abs(amt),
                                        "position_value_usd": abs(amt) * entry,
                                        "entry_time": datetime.now().isoformat()
                                    }
                                )
                                await self.notifier.send_event(entry_event)

                                # Track entry time
                                self.position_entry_times[symbol] = time.time()
                                self.known_positions.add(symbol)

                                # Wait before checking TP/SL (give bot time to place orders)
                                log(f"\n  Waiting {self.monitoring_settings['tp_sl_check_delay']}s before checking TP/SL...")
                                await asyncio.sleep(self.monitoring_settings['tp_sl_check_delay'])

                                # Check TP/SL integrity
                                has_both = await self.check_tp_sl_integrity(symbol, pos_data)
                                if has_both:
                                    log(f"  ✅ Both TP and SL orders present for {symbol}")
                                else:
                                    log(f"  ⚠️  WARNING: Missing TP/SL for {symbol}!")

                    # Check for CLOSED positions
                    closed_symbols = self.known_positions - current_symbols
                    if closed_symbols:
                        for symbol in closed_symbols:
                            log(f"\n📉 Position closed: {symbol}")

                            # Send position exit event
                            exit_event = PositionExitEvent(
                                data={
                                    "symbol": symbol,
                                    "exit_time": datetime.now().isoformat(),
                                    "hold_duration_seconds": int(time.time() - self.position_entry_times.get(symbol, time.time()))
                                }
                            )
                            await self.notifier.send_event(exit_event)

                            self.known_positions.discard(symbol)
                            self.position_entry_times.pop(symbol, None)

                    # Periodic status update every 10 checks
                    if self.check_count % 10 == 0:
                        log(f"[{current_time}] Monitoring... ({self.check_count} checks, {len(self.known_positions)} positions)")

                        # Show metrics
                        metrics = self.notifier.get_metrics()
                        if metrics["sent"] > 0 or metrics["failed"] > 0:
                            log(f"  Webhooks: {metrics['sent']} sent, {metrics['failed']} failed, {metrics['retries']} retries")

                except Exception as e:
                    log(f"Error in monitoring loop: {e}", "error")
                    traceback.print_exc()

                # Wait before next check
                await asyncio.sleep(self.monitoring_settings["check_interval"])

        except KeyboardInterrupt:
            log(f"\n\nMonitoring stopped by user")
        except Exception as e:
            log(f"Fatal error: {e}", "error")
            traceback.print_exc()
        finally:
            # Send shutdown event
            if self.notifier:
                shutdown_event = BotShutdownEvent(
                    data={
                        "stopped_at": datetime.now().isoformat(),
                        "total_checks": self.check_count,
                        "webhooks_sent": self.notifier.get_metrics()["sent"]
                    }
                )
                await self.notifier.send_event(shutdown_event)
                await self.notifier.close()

            self.executor.close()
            log(f"\nMonitor closed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


async def main():
    """Main entry point"""
    daemon = MonitoringDaemon()
    await daemon.initialize()
    await daemon.monitor_loop()


if __name__ == "__main__":
    asyncio.run(main())
