"""
Martingale Signal Scanner - Martingale Manager
Tracks state machine, position sizing, chain tracking
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, TYPE_CHECKING
import time
import config
from utils import log, format_usd, format_pct

if TYPE_CHECKING:
    from order_executor import OrderExecutor

@dataclass
class TradeRecord:
    timestamp: float
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    level: int
    margin_usd: float
    notional_usd: float
    pnl_usd: float
    outcome: str  # "WIN" or "LOSS"
    score: float

class MartingaleManager:
    def __init__(self):
        # Current state
        self.level: int = 0
        self.in_position: bool = False
        self.current_symbol: Optional[str] = None
        self.current_direction: Optional[str] = None
        self.entry_price: Optional[float] = None
        self.entry_quantity: Optional[float] = None  # CRITICAL: needed for LIMIT TP
        self.current_size_usd: float = 0.0
        self.current_score: float = 0.0
        self.entry_candle_time: Optional[float] = None  # Timestamp when position was opened

        # MAE (Maximum Adverse Excursion) tracking
        self.max_adverse_excursion_pct: float = 0.0  # Worst drawdown % from entry
        self.mae_candle: int = 0  # Candle number when MAE occurred

        # History
        self.history: List[TradeRecord] = []
        self.last_max_loss_time: float = 0

        # Cooldown blacklist - {symbol: cooldown_expiry_timestamp}
        self.cooldown_blacklist: Dict[str, float] = {}

        # Consecutive loss tracking for regime switching
        self.consecutive_losses: int = 0
        self.regime_flipped: bool = False  # True when regime is inverted

        # Chain PnL tracking - cumulative profit/loss across current chain
        self.chain_pnl_history: List[float] = []  # List of net PnL for each trade in current chain

        # Dynamic sizing - balance at chain start
        self.chain_start_balance: float = 0.0
        self.executor: Optional['OrderExecutor'] = None

    def set_executor(self, executor: 'OrderExecutor'):
        """Set executor reference for balance fetching"""
        self.executor = executor

    def update_chain_start_balance(self):
        """Fetch and cache account balance at chain start"""
        if self.executor is None:
            log("ERROR: Executor not set, cannot fetch balance", "error")
            return

        try:
            balance = self.executor.get_account_balance()
            self.chain_start_balance = balance
            base_size = balance * config.BASE_SIZE_PCT
            log(f"BALANCE: ${balance:.2f} → Base size = ${base_size:.2f} ({config.BASE_SIZE_PCT*100:.1f}%)")
        except Exception as e:
            log(f"ERROR: Failed to fetch account balance: {e}", "error")
            raise

    def base_size_usd(self) -> float:
        """Calculate base size from cached balance"""
        return self.chain_start_balance * config.BASE_SIZE_PCT

    def position_size_usd(self) -> float:
        """
        Calculate notional position size for current level with EMERGENCY BRAKE
        Uses configurable multiplier and enforces maximum position size cap
        """
        calculated_size = self.base_size_usd() * (config.MARTINGALE_MULTIPLIER ** self.level) * config.LEVERAGE

        # EMERGENCY BRAKE: Cap position at MAX_POSITION_PCT of account
        max_allowed = self.chain_start_balance * config.MAX_POSITION_PCT * config.LEVERAGE

        if calculated_size > max_allowed:
            log(f"🚨 EMERGENCY BRAKE: Position size ${calculated_size:.2f} exceeds maximum ${max_allowed:.2f} "
                f"({config.MAX_POSITION_PCT*100:.0f}% of account) - CAPPING", "warning")
            return max_allowed

        return calculated_size

    def margin_required(self) -> float:
        """Calculate margin required for current level"""
        return self.base_size_usd() * (config.MARTINGALE_MULTIPLIER ** self.level)

    def total_chain_margin(self) -> float:
        """Calculate total margin for full Martingale chain"""
        # Geometric series: sum = a * (r^n - 1) / (r - 1)
        # From level 0 to MAX_LEVEL using configured multiplier
        multiplier = config.MARTINGALE_MULTIPLIER
        base = self.base_size_usd()
        if multiplier == 1.0:
            # Special case: no growth
            return base * (config.MAX_LEVEL + 1)
        return base * ((multiplier ** (config.MAX_LEVEL + 1)) - 1) / (multiplier - 1)

    def can_enter(self) -> bool:
        """Check if we can enter a new position"""
        if self.in_position:
            return False

        if self.level > config.MAX_LEVEL:
            return False

        # Check cooldown after max loss
        if self.last_max_loss_time > 0:
            elapsed = time.time() - self.last_max_loss_time
            if elapsed < config.COOLDOWN_AFTER_MAX_LOSS:
                return False

        return True

    def enter(self, symbol: str, direction: str, entry_price: float,
             entry_quantity: float, score: float):
        """Enter a new position"""
        self.in_position = True
        self.current_symbol = symbol
        self.current_direction = direction
        self.entry_price = entry_price
        self.entry_quantity = entry_quantity  # MUST store for LIMIT TP
        self.current_size_usd = self.position_size_usd()
        self.current_score = score
        self.entry_candle_time = time.time()  # Record entry timestamp for timeout tracking

        # Reset MAE tracking for new position
        self.max_adverse_excursion_pct = 0.0
        self.mae_candle = 0

        log(f"ENTERED: {symbol} {direction} @ {entry_price:.4f} | "
            f"Level={self.level} | Size={format_usd(self.current_size_usd)} | "
            f"Qty={entry_quantity:.4f} | Score={score:.2f}")

    def tp_price(self) -> float:
        """Calculate take profit price"""
        if not self.entry_price:
            return 0.0

        if self.current_direction == "LONG":
            return self.entry_price * (1 + config.TP_PCT)
        else:  # SHORT
            return self.entry_price * (1 - config.TP_PCT)

    def sl_price(self) -> float:
        """Calculate stop loss price"""
        if not self.entry_price:
            return 0.0

        if self.current_direction == "LONG":
            return self.entry_price * (1 - config.SL_PCT)
        else:  # SHORT
            return self.entry_price * (1 + config.SL_PCT)

    def close_win(self, exit_price: float):
        """Close winning position"""
        pnl_pct = abs(exit_price - self.entry_price) / self.entry_price
        pnl_usd = self.current_size_usd * pnl_pct
        net_pnl = pnl_usd - (self.current_size_usd * (config.TAKER_FEE + config.MAKER_FEE))

        trade = TradeRecord(
            timestamp=time.time(),
            symbol=self.current_symbol,
            direction=self.current_direction,
            entry_price=self.entry_price,
            exit_price=exit_price,
            quantity=self.entry_quantity,
            level=self.level,
            margin_usd=self.margin_required(),
            notional_usd=self.current_size_usd,
            pnl_usd=net_pnl,
            outcome="WIN",
            score=self.current_score,
        )
        self.history.append(trade)

        # Reset consecutive loss counter on win
        self.consecutive_losses = 0

        # Add this trade's PnL to chain history
        self.chain_pnl_history.append(net_pnl)

        # Calculate cumulative PnL across entire chain
        cumulative_pnl = sum(self.chain_pnl_history)

        # Calculate total candles held
        total_candles = self.candles_held(time.time())

        log(f"WIN: {self.current_symbol} {self.current_direction} @ {exit_price:.4f} | "
            f"PnL={format_usd(net_pnl)} | Cumulative chain PnL={format_usd(cumulative_pnl)}")
        log(f"MAE: {self.max_adverse_excursion_pct:.2f}% (candle {self.mae_candle} of {total_candles})")

        # Only reset to level 0 if ENTIRE CHAIN is profitable
        if cumulative_pnl > 0:
            log(f"CHAIN PROFITABLE: {format_usd(cumulative_pnl)} | Level={self.level} → 0")
            self.level = 0
            self.chain_start_balance = 0.0
            self.chain_pnl_history = []  # Clear chain history
        else:
            # Chain still negative - increment level to increase position size
            log(f"CHAIN STILL NEGATIVE: {format_usd(cumulative_pnl)} | Level={self.level} → {self.level + 1}", "warning")
            self.level += 1

            # Check if max level exceeded even after a win
            if self.level > config.MAX_LEVEL:
                log(f"MAX LEVEL HIT ({config.MAX_LEVEL}) after WIN - Chain still unprofitable | "
                    f"Cumulative chain PnL={format_usd(cumulative_pnl)} | "
                    f"Entering {config.COOLDOWN_AFTER_MAX_LOSS}s cooldown", "warning")
                self.last_max_loss_time = time.time()
                self.level = 0
                self.chain_start_balance = 0.0
                self.chain_pnl_history = []  # Reset chain on MAX_LEVEL

        self._clear_position()

    def close_loss(self, exit_price: float):
        """Close losing position"""
        pnl_pct = abs(exit_price - self.entry_price) / self.entry_price
        pnl_usd = self.current_size_usd * pnl_pct
        net_pnl = -(pnl_usd + (self.current_size_usd * (config.TAKER_FEE + config.TAKER_FEE)))

        trade = TradeRecord(
            timestamp=time.time(),
            symbol=self.current_symbol,
            direction=self.current_direction,
            entry_price=self.entry_price,
            exit_price=exit_price,
            quantity=self.entry_quantity,
            level=self.level,
            margin_usd=self.margin_required(),
            notional_usd=self.current_size_usd,
            pnl_usd=net_pnl,
            outcome="LOSS",
            score=self.current_score,
        )
        self.history.append(trade)

        # Add this trade's PnL to chain history
        self.chain_pnl_history.append(net_pnl)

        # Calculate cumulative PnL across entire chain
        cumulative_pnl = sum(self.chain_pnl_history)

        # Add symbol to cooldown blacklist
        cooldown_expiry = time.time() + config.COOLDOWN_DURATION_SECS
        self.cooldown_blacklist[self.current_symbol] = cooldown_expiry

        # Calculate total candles held
        total_candles = self.candles_held(time.time())

        log(f"LOSS: {self.current_symbol} {self.current_direction} @ {exit_price:.4f} | "
            f"PnL={format_usd(net_pnl)} | Cumulative chain PnL={format_usd(cumulative_pnl)} | "
            f"Level={self.level} → {self.level + 1}")
        log(f"MAE: {self.max_adverse_excursion_pct:.2f}% (candle {self.mae_candle} of {total_candles})")
        log(f"BLACKLIST: {self.current_symbol} added to cooldown for {config.COOLDOWN_CANDLES} candles "
            f"({config.COOLDOWN_DURATION_SECS/60:.0f} minutes)", "warning")

        # Increment level
        self.level += 1

        # Track consecutive losses (informational only)
        self.consecutive_losses += 1
        log(f"Consecutive losses: {self.consecutive_losses}")

        # Check if max level exceeded
        if self.level > config.MAX_LEVEL:
            log(f"MAX LEVEL HIT ({config.MAX_LEVEL}) - Full chain blowout | "
                f"Cumulative chain PnL={format_usd(sum(self.chain_pnl_history))} | "
                f"Entering {config.COOLDOWN_AFTER_MAX_LOSS}s cooldown", "warning")
            self.last_max_loss_time = time.time()
            self.level = 0
            self.chain_start_balance = 0.0  # Clear cached balance for next cycle
            self.chain_pnl_history = []  # Clear chain history on MAX_LEVEL reset

        self._clear_position()

    def _clear_position(self):
        """Clear position state"""
        self.in_position = False
        self.current_symbol = None
        self.current_direction = None
        self.entry_price = None
        self.entry_quantity = None
        self.current_size_usd = 0.0
        self.current_score = 0.0
        self.entry_candle_time = None
        self.max_adverse_excursion_pct = 0.0
        self.mae_candle = 0

    def reset_to_level_zero(self, reason: str = "Manual reset"):
        """
        Reset martingale level to 0 and clear all state
        Used when insufficient balance or manual reset needed
        """
        log(f"RESET TO LEVEL 0: {reason}", "warning")
        log(f"  Previous level: {self.level}")
        log(f"  Clearing position state and balance cache")

        self.level = 0
        self.chain_start_balance = 0.0
        self.chain_pnl_history = []  # Clear chain PnL history
        self.last_max_loss_time = 0
        self._clear_position()

        # Keep trade history and cooldown blacklist
        log(f"  Trade history preserved ({len(self.history)} trades)")
        if self.cooldown_blacklist:
            log(f"  Cooldown blacklist preserved ({len(self.cooldown_blacklist)} symbols)")

    def stats(self) -> dict:
        """Get trading statistics"""
        if not self.history:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "max_level_reached": 0,
                "current_level": self.level,
                "in_cooldown": time.time() - self.last_max_loss_time < config.COOLDOWN_AFTER_MAX_LOSS if self.last_max_loss_time > 0 else False,
            }

        wins = [t for t in self.history if t.outcome == "WIN"]
        losses = [t for t in self.history if t.outcome == "LOSS"]
        total_pnl = sum(t.pnl_usd for t in self.history)
        max_level = max(t.level for t in self.history)

        return {
            "total_trades": len(self.history),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(self.history) if self.history else 0.0,
            "total_pnl": total_pnl,
            "max_level_reached": max_level,
            "current_level": self.level,
            "in_cooldown": time.time() - self.last_max_loss_time < config.COOLDOWN_AFTER_MAX_LOSS if self.last_max_loss_time > 0 else False,
        }

    def daily_pnl(self) -> float:
        """Calculate PnL from last 24 hours"""
        cutoff = time.time() - 86400
        recent_trades = [t for t in self.history if t.timestamp > cutoff]
        return sum(t.pnl_usd for t in recent_trades)

    def clean_expired_blacklist(self) -> None:
        """Remove expired entries from cooldown blacklist"""
        current_time = time.time()
        expired_symbols = [symbol for symbol, expiry in self.cooldown_blacklist.items()
                          if expiry <= current_time]

        for symbol in expired_symbols:
            del self.cooldown_blacklist[symbol]
            log(f"BLACKLIST EXPIRED: {symbol} removed from cooldown")

    def get_blacklisted_symbols(self) -> List[str]:
        """Get currently blacklisted symbols"""
        return list(self.cooldown_blacklist.keys())

    def is_timed_out(self, current_time: float) -> bool:
        """Check if position has exceeded max hold time"""
        if self.entry_candle_time is None:
            return False
        max_seconds = config.MAX_HOLD_CANDLES * config.SCAN_INTERVAL_SECS
        elapsed = current_time - self.entry_candle_time
        return elapsed > max_seconds

    def candles_held(self, current_time: float) -> int:
        """Calculate how many candles have passed since position entry"""
        if self.entry_candle_time is None:
            return 0
        elapsed = current_time - self.entry_candle_time
        return int(elapsed / config.SCAN_INTERVAL_SECS)

    def update_mae(self, current_price: float, current_candle: int) -> float:
        """
        Update Maximum Adverse Excursion tracking
        Returns: current drawdown %
        """
        if self.entry_price is None or self.current_direction is None:
            return 0.0

        # Calculate current drawdown
        if self.current_direction == "LONG":
            drawdown_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:  # SHORT
            drawdown_pct = (self.entry_price - current_price) / self.entry_price * 100

        # Update MAE if this is worse
        if drawdown_pct < self.max_adverse_excursion_pct:
            self.max_adverse_excursion_pct = drawdown_pct
            self.mae_candle = current_candle

        return drawdown_pct

# Unit test
if __name__ == "__main__":
    print(f"\n{'='*80}")
    print(f"MARTINGALE MANAGER TEST")
    print(f"{'='*80}")

    manager = MartingaleManager()

    # Mock balance for testing ($100 account)
    manager.chain_start_balance = 100.0

    print(f"\nInitial state:")
    print(f"  Level: {manager.level}")
    print(f"  Balance: {format_usd(manager.chain_start_balance)}")
    print(f"  Base size: {format_usd(manager.base_size_usd())} ({config.BASE_SIZE_PCT*100:.1f}% of balance)")
    print(f"  Can enter: {manager.can_enter()}")
    print(f"  Position size: {format_usd(manager.position_size_usd())}")
    print(f"  Margin required: {format_usd(manager.margin_required())}")
    print(f"  Total chain margin: {format_usd(manager.total_chain_margin())}")

    print(f"\nSimulating Martingale chain:")

    # Level 0 - LOSS
    manager.enter("BTCUSDT", "LONG", 50000.0, 0.0004, 75.5)
    print(f"  Level {manager.level}: Entered LONG @ 50000.0, size={format_usd(manager.position_size_usd())}")
    manager.close_loss(49650.0)

    # Level 1 - LOSS
    manager.enter("ETHUSDT", "SHORT", 3000.0, 0.0133, 68.2)
    print(f"  Level {manager.level}: Entered SHORT @ 3000.0, size={format_usd(manager.position_size_usd())}")
    manager.close_loss(3021.0)

    # Level 2 - WIN
    manager.enter("SOLUSDT", "LONG", 100.0, 0.8, 82.1)
    print(f"  Level {manager.level}: Entered LONG @ 100.0, size={format_usd(manager.position_size_usd())}")
    manager.close_win(100.87)

    print(f"\nFinal stats:")
    stats = manager.stats()
    for key, value in stats.items():
        if isinstance(value, float):
            if key == "win_rate":
                print(f"  {key}: {value*100:.2f}%")
            elif key == "total_pnl":
                print(f"  {key}: {format_usd(value)}")
            else:
                print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")

    print(f"\nTrade history:")
    for i, trade in enumerate(manager.history, 1):
        print(f"  {i}. {trade.symbol} {trade.direction} L{trade.level} @ {trade.entry_price:.4f} → "
              f"{trade.exit_price:.4f} | {trade.outcome} | PnL={format_usd(trade.pnl_usd)}")
