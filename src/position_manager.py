"""
Position Manager - Multi-Position Flat Sizing
Tracks multiple simultaneous positions with fixed position sizing.
No Martingale escalation — flat size on every trade.
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
    margin_usd: float
    notional_usd: float
    pnl_usd: float
    outcome: str  # "WIN" or "LOSS"
    score: float


@dataclass
class OpenPosition:
    symbol: str
    direction: str
    entry_price: float
    entry_quantity: float
    size_usd: float
    score: float
    entry_candle_time: float
    max_adverse_excursion_pct: float = 0.0
    mae_candle: int = 0


class PositionManager:
    def __init__(self):
        # Active positions: {symbol: OpenPosition}
        self.positions: Dict[str, OpenPosition] = {}

        # History
        self.history: List[TradeRecord] = []

        # Cooldown blacklist - {symbol: cooldown_expiry_timestamp}
        self.cooldown_blacklist: Dict[str, float] = {}

        # Balance cache
        self.cached_balance: float = 0.0
        self.executor: Optional['OrderExecutor'] = None

    def set_executor(self, executor: 'OrderExecutor'):
        self.executor = executor

    def update_balance(self):
        """Fetch and cache account balance"""
        if self.executor is None:
            log("ERROR: Executor not set, cannot fetch balance", "error")
            return
        try:
            self.cached_balance = self.executor.get_account_balance()
            log(f"BALANCE: ${self.cached_balance:.2f}")
        except Exception as e:
            log(f"ERROR: Failed to fetch account balance: {e}", "error")
            raise

    def position_size_usd(self) -> float:
        """
        Flat position size: BASE_SIZE_PCT of balance × leverage, minimum $10 notional.
        Emergency brake caps at MAX_POSITION_PCT of balance.
        """
        base = max(self.cached_balance * config.BASE_SIZE_PCT, 10.0 / config.LEVERAGE)
        notional = base * config.LEVERAGE

        max_allowed = self.cached_balance * config.MAX_POSITION_PCT * config.LEVERAGE
        if notional > max_allowed and max_allowed > 0:
            log(f"EMERGENCY BRAKE: ${notional:.2f} > ${max_allowed:.2f} — capping", "warning")
            return max_allowed

        return notional

    def margin_required(self) -> float:
        """Margin for one position"""
        return self.position_size_usd() / config.LEVERAGE

    # ── Position lifecycle ───────────────────────────────────────────────

    @property
    def num_open(self) -> int:
        return len(self.positions)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def can_enter(self) -> bool:
        """Check if we can open another position"""
        if config.MAX_POSITIONS > 0 and self.num_open >= config.MAX_POSITIONS:
            return False
        return True

    def enter(self, symbol: str, direction: str, entry_price: float,
              entry_quantity: float, score: float):
        pos = OpenPosition(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            entry_quantity=entry_quantity,
            size_usd=self.position_size_usd(),
            score=score,
            entry_candle_time=time.time(),
        )
        self.positions[symbol] = pos

        log(f"ENTERED: {symbol} {direction} @ {entry_price:.6f} | "
            f"Size={format_usd(pos.size_usd)} | Qty={entry_quantity} | "
            f"Score={score:.2f} | Open positions: {self.num_open}")

    def close_win(self, symbol: str, exit_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            log(f"close_win called but {symbol} not in positions", "warning")
            return

        pnl_pct = abs(exit_price - pos.entry_price) / pos.entry_price
        pnl_usd = pos.size_usd * pnl_pct
        net_pnl = pnl_usd - (pos.size_usd * (config.TAKER_FEE + config.MAKER_FEE))
        candles = self.candles_held(symbol, time.time())

        self.history.append(TradeRecord(
            timestamp=time.time(), symbol=symbol, direction=pos.direction,
            entry_price=pos.entry_price, exit_price=exit_price,
            quantity=pos.entry_quantity, margin_usd=pos.size_usd / config.LEVERAGE,
            notional_usd=pos.size_usd, pnl_usd=net_pnl, outcome="WIN", score=pos.score,
        ))

        log(f"WIN: {symbol} {pos.direction} @ {exit_price:.6f} | PnL={format_usd(net_pnl)}")
        log(f"MAE: {pos.max_adverse_excursion_pct:.2f}% (candle {pos.mae_candle} of {candles})")

        del self.positions[symbol]

    def close_loss(self, symbol: str, exit_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            log(f"close_loss called but {symbol} not in positions", "warning")
            return

        pnl_pct = abs(exit_price - pos.entry_price) / pos.entry_price
        pnl_usd = pos.size_usd * pnl_pct
        net_pnl = -(pnl_usd + (pos.size_usd * (config.TAKER_FEE + config.TAKER_FEE)))
        candles = self.candles_held(symbol, time.time())

        self.history.append(TradeRecord(
            timestamp=time.time(), symbol=symbol, direction=pos.direction,
            entry_price=pos.entry_price, exit_price=exit_price,
            quantity=pos.entry_quantity, margin_usd=pos.size_usd / config.LEVERAGE,
            notional_usd=pos.size_usd, pnl_usd=net_pnl, outcome="LOSS", score=pos.score,
        ))

        # Add to cooldown blacklist
        self.cooldown_blacklist[symbol] = time.time() + config.COOLDOWN_DURATION_SECS
        log(f"LOSS: {symbol} {pos.direction} @ {exit_price:.6f} | PnL={format_usd(net_pnl)}")
        log(f"MAE: {pos.max_adverse_excursion_pct:.2f}% (candle {pos.mae_candle} of {candles})")
        log(f"BLACKLIST: {symbol} cooldown {config.COOLDOWN_DURATION_SECS/60:.0f}min", "warning")

        del self.positions[symbol]

    def remove_position(self, symbol: str):
        """Remove position without recording trade (emergency cleanup)"""
        if symbol in self.positions:
            del self.positions[symbol]

    # ── Helpers ───────────────────────────────────────────────────────────

    def tp_price(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        if pos.direction == "LONG":
            return pos.entry_price * (1 + config.TP_PCT)
        return pos.entry_price * (1 - config.TP_PCT)

    def sl_price(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        if pos.direction == "LONG":
            return pos.entry_price * (1 - config.SL_PCT)
        return pos.entry_price * (1 + config.SL_PCT)

    def is_timed_out(self, symbol: str, current_time: float) -> bool:
        pos = self.positions.get(symbol)
        if not pos:
            return False
        max_seconds = config.MAX_HOLD_CANDLES * config.SCAN_INTERVAL_SECS
        return (current_time - pos.entry_candle_time) > max_seconds

    def candles_held(self, symbol: str, current_time: float) -> int:
        pos = self.positions.get(symbol)
        if not pos:
            return 0
        return int((current_time - pos.entry_candle_time) / config.SCAN_INTERVAL_SECS)

    def update_mae(self, symbol: str, current_price: float, current_candle: int) -> float:
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0

        if pos.direction == "LONG":
            drawdown = (current_price - pos.entry_price) / pos.entry_price * 100
        else:
            drawdown = (pos.entry_price - current_price) / pos.entry_price * 100

        if drawdown < pos.max_adverse_excursion_pct:
            pos.max_adverse_excursion_pct = drawdown
            pos.mae_candle = current_candle

        return drawdown

    def clean_expired_blacklist(self):
        now = time.time()
        expired = [s for s, exp in self.cooldown_blacklist.items() if exp <= now]
        for s in expired:
            del self.cooldown_blacklist[s]
            log(f"BLACKLIST EXPIRED: {s}")

    def get_blacklisted_symbols(self) -> List[str]:
        return list(self.cooldown_blacklist.keys())

    def get_open_symbols(self) -> List[str]:
        """Symbols with active positions — used to exclude from new entries"""
        return list(self.positions.keys())

    def stats(self) -> dict:
        if not self.history:
            return {"total_trades": 0, "wins": 0, "losses": 0,
                    "win_rate": 0.0, "total_pnl": 0.0, "open_positions": self.num_open}

        wins = [t for t in self.history if t.outcome == "WIN"]
        losses = [t for t in self.history if t.outcome == "LOSS"]
        return {
            "total_trades": len(self.history),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(self.history),
            "total_pnl": sum(t.pnl_usd for t in self.history),
            "open_positions": self.num_open,
        }

    def daily_pnl(self) -> float:
        cutoff = time.time() - 86400
        return sum(t.pnl_usd for t in self.history if t.timestamp > cutoff)

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize state for save_state"""
        positions_data = {}
        for sym, pos in self.positions.items():
            positions_data[sym] = {
                "symbol": pos.symbol,
                "direction": pos.direction,
                "entry_price": pos.entry_price,
                "entry_quantity": pos.entry_quantity,
                "size_usd": pos.size_usd,
                "score": pos.score,
                "entry_candle_time": pos.entry_candle_time,
                "max_adverse_excursion_pct": pos.max_adverse_excursion_pct,
                "mae_candle": pos.mae_candle,
            }
        return {
            "positions": positions_data,
            "cooldown_blacklist": self.cooldown_blacklist,
            "cached_balance": self.cached_balance,
        }

    def load_from_dict(self, data: dict):
        """Restore state from loaded dict"""
        self.cooldown_blacklist = data.get("cooldown_blacklist", {})
        self.cached_balance = data.get("cached_balance", 0.0)

        for sym, pdata in data.get("positions", {}).items():
            self.positions[sym] = OpenPosition(
                symbol=pdata["symbol"],
                direction=pdata["direction"],
                entry_price=pdata["entry_price"],
                entry_quantity=pdata["entry_quantity"],
                size_usd=pdata["size_usd"],
                score=pdata["score"],
                entry_candle_time=pdata["entry_candle_time"],
                max_adverse_excursion_pct=pdata.get("max_adverse_excursion_pct", 0.0),
                mae_candle=pdata.get("mae_candle", 0),
            )

        log(f"State restored: {self.num_open} open positions, "
            f"{len(self.cooldown_blacklist)} blacklisted")
