"""
Safety Checks
BTC correlation guard, daily limits, balance check
"""
from dataclasses import dataclass
import httpx
import config
from utils import log, save_state
from position_manager import PositionManager

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
        self.client.close()

    def check_btc_correlation(self) -> tuple[bool, bool]:
        try:
            resp = self.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/klines",
                params={"symbol": "BTCUSDT", "interval": "4h", "limit": 1}
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

    def check_daily_loss_limit(self, manager: PositionManager) -> bool:
        daily_pnl = manager.daily_pnl()
        if daily_pnl < -config.DAILY_LOSS_LIMIT_USD:
            log(f"Daily loss limit hit: ${daily_pnl:.2f} < -${config.DAILY_LOSS_LIMIT_USD} → blocking all", "warning")
            return False
        return True

    def check_balance(self, manager: PositionManager, executor) -> bool:
        try:
            available = executor.get_account_balance()
            required = manager.margin_required() * 1.5
            if available < required:
                log(f"Insufficient balance: ${available:.2f} < ${required:.2f} required", "warning")
                return False
            return True
        except Exception as e:
            log(f"Balance check failed: {e}", "error")
            return False

    def run_all_checks(self, manager: PositionManager, executor) -> SafetyResult:
        if not self.check_daily_loss_limit(manager):
            return SafetyResult(can_trade=False, block_longs=True, block_shorts=True,
                                reason="Daily loss limit exceeded")

        if not self.check_balance(manager, executor):
            return SafetyResult(can_trade=False, block_longs=True, block_shorts=True,
                                reason="Insufficient balance")

        block_longs, block_shorts = self.check_btc_correlation()
        if block_longs and block_shorts:
            return SafetyResult(can_trade=False, block_longs=True, block_shorts=True,
                                reason="BTC volatility - both directions blocked")

        return SafetyResult(
            can_trade=True, block_longs=block_longs, block_shorts=block_shorts,
            reason="All checks passed" if not (block_longs or block_shorts) else "BTC correlation filter active"
        )
