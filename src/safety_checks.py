"""
Martingale Signal Scanner - Safety Checks
BTC correlation guard, daily limits, cooldowns, balance check
"""
from dataclasses import dataclass
import httpx
import config
from utils import log, save_state
from martingale_manager import MartingaleManager

@dataclass
class SafetyResult:
    can_trade: bool
    block_longs: bool
    block_shorts: bool
    reason: str

class SafetyChecker:
    def __init__(self):
        self.client = httpx.Client(timeout=30.0)

    def close(self):
        """Close HTTP client"""
        self.client.close()

    def check_btc_correlation(self) -> tuple[bool, bool]:
        """
        Check BTC 4h candle movement
        Returns: (block_longs, block_shorts)
        """
        try:
            resp = self.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "4h",
                    "limit": 1
                }
            )
            resp.raise_for_status()
            candle = resp.json()[0]

            open_price = float(candle[1])
            close_price = float(candle[4])
            btc_change = (close_price - open_price) / open_price

            block_longs = btc_change < config.BTC_DUMP_THRESHOLD_4H
            block_shorts = btc_change > config.BTC_PUMP_THRESHOLD_4H

            if block_longs:
                log(f"BTC dumping {btc_change*100:.2f}% in 4h → blocking LONGS", "warning")
            if block_shorts:
                log(f"BTC pumping {btc_change*100:.2f}% in 4h → blocking SHORTS", "warning")

            return block_longs, block_shorts

        except Exception as e:
            log(f"BTC correlation check failed: {e}", "error")
            return False, False

    def check_daily_loss_limit(self, manager: MartingaleManager) -> bool:
        """Check if daily loss limit exceeded"""
        daily_pnl = manager.daily_pnl()

        if daily_pnl < -config.DAILY_LOSS_LIMIT_USD:
            log(f"Daily loss limit hit: ${daily_pnl:.2f} < -${config.DAILY_LOSS_LIMIT_USD} → blocking all", "warning")
            return False

        return True

    def check_cooldown(self, manager: MartingaleManager) -> bool:
        """Check if in cooldown after max loss"""
        if manager.last_max_loss_time > 0:
            import time
            elapsed = time.time() - manager.last_max_loss_time
            remaining = config.COOLDOWN_AFTER_MAX_LOSS - elapsed

            if remaining > 0:
                log(f"In cooldown: {remaining:.0f}s remaining → blocking all", "warning")
                return False

        return True

    def check_balance(self, manager: MartingaleManager, executor) -> bool:
        """Check if sufficient balance for next trade"""
        try:
            available = executor.get_account_balance()
            required = manager.margin_required() * 1.5  # 1.5x buffer

            if available < required:
                log(f"Insufficient balance: ${available:.2f} < ${required:.2f} required", "warning")

                # AUTO-RESET: Reset to level 0 when balance is insufficient
                if manager.level > 0:
                    manager.reset_to_level_zero(
                        reason=f"Insufficient balance (${available:.2f} < ${required:.2f})"
                    )
                    save_state(manager)
                    log(f"State reset to level 0 and saved", "warning")
                else:
                    log(f"Already at level 0, cannot trade with current balance", "warning")

                return False

            return True

        except Exception as e:
            log(f"Balance check failed: {e}", "error")
            return False

    def run_all_checks(self, manager: MartingaleManager, executor) -> SafetyResult:
        """Run all safety checks"""

        # Check cooldown
        if not self.check_cooldown(manager):
            return SafetyResult(
                can_trade=False,
                block_longs=True,
                block_shorts=True,
                reason="In cooldown after max loss"
            )

        # Check daily loss limit
        if not self.check_daily_loss_limit(manager):
            return SafetyResult(
                can_trade=False,
                block_longs=True,
                block_shorts=True,
                reason="Daily loss limit exceeded"
            )

        # Check balance
        if not self.check_balance(manager, executor):
            return SafetyResult(
                can_trade=False,
                block_longs=True,
                block_shorts=True,
                reason="Insufficient balance"
            )

        # Check BTC correlation
        block_longs, block_shorts = self.check_btc_correlation()

        if block_longs and block_shorts:
            return SafetyResult(
                can_trade=False,
                block_longs=True,
                block_shorts=True,
                reason="BTC volatility - both directions blocked"
            )

        return SafetyResult(
            can_trade=True,
            block_longs=block_longs,
            block_shorts=block_shorts,
            reason="All checks passed" if not (block_longs or block_shorts) else "BTC correlation filter active"
        )

# Test
if __name__ == "__main__":
    from order_executor import OrderExecutor

    print(f"\n{'='*80}")
    print(f"SAFETY CHECKS TEST")
    print(f"{'='*80}")

    checker = SafetyChecker()
    executor = OrderExecutor()
    manager = MartingaleManager()

    try:
        # Test BTC correlation
        print(f"\n1. BTC Correlation Check:")
        block_longs, block_shorts = checker.check_btc_correlation()
        print(f"   Block longs: {block_longs}")
        print(f"   Block shorts: {block_shorts}")

        # Test daily loss limit
        print(f"\n2. Daily Loss Limit Check:")
        can_trade = checker.check_daily_loss_limit(manager)
        print(f"   Can trade: {can_trade}")
        print(f"   Daily PnL: ${manager.daily_pnl():.2f}")

        # Test cooldown
        print(f"\n3. Cooldown Check:")
        can_trade = checker.check_cooldown(manager)
        print(f"   Can trade: {can_trade}")

        # Test balance
        print(f"\n4. Balance Check:")
        can_trade = checker.check_balance(manager, executor)
        print(f"   Can trade: {can_trade}")
        balance = executor.get_account_balance()
        required = manager.margin_required() * 1.5
        print(f"   Available: ${balance:.2f}")
        print(f"   Required: ${required:.2f}")

        # Run all checks
        print(f"\n5. All Checks:")
        result = checker.run_all_checks(manager, executor)
        print(f"   Can trade: {result.can_trade}")
        print(f"   Block longs: {result.block_longs}")
        print(f"   Block shorts: {result.block_shorts}")
        print(f"   Reason: {result.reason}")

    finally:
        checker.close()
        executor.close()
