"""
Multi-Position Signal Scanner - Main Loop
Flat sizing, unlimited simultaneous positions, no Martingale
"""
import asyncio
import time
import math
from typing import Optional, Callable, Any
from utils import log, save_state, load_state, format_usd, setup_signal_handlers
import config
from pair_scanner import PairScanner
from signal_scorer import SignalScorer
from position_manager import PositionManager
from order_executor import OrderExecutor
from safety_checks import SafetyChecker
import httpx
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
        log("Health check server started on port 8080")
        server.serve_forever()
    except Exception as e:
        log(f"Failed to start health server: {e}", "warning")


def retry_with_backoff(func: Callable, max_retries: int = 3, initial_delay: float = 10.0) -> Any:
    delay = initial_delay
    last_exception = None
    for attempt in range(max_retries):
        try:
            return func()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 418:
                wait_time = max(delay, 300.0)
                last_exception = e
                if attempt < max_retries - 1:
                    log(f"IP banned (418) - waiting {wait_time:.0f}s before retry ({attempt+1}/{max_retries})...", "warning")
                    time.sleep(wait_time)
                    delay *= 2
                else:
                    raise
            elif status == 429:
                wait_time = max(delay, 60.0)
                last_exception = e
                if attempt < max_retries - 1:
                    log(f"Rate limited (429) - waiting {wait_time:.0f}s before retry ({attempt+1}/{max_retries})...", "warning")
                    time.sleep(wait_time)
                    delay *= 2
                else:
                    raise
            else:
                raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout,
                OSError, ConnectionError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                log(f"Network error (attempt {attempt+1}/{max_retries}): {type(e).__name__}", "warning")
                time.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exception


def wait_until_next_candle(interval_secs: int = 150):
    now = time.time()
    next_candle = math.ceil(now / interval_secs) * interval_secs + 2
    sleep_time = next_candle - now
    if sleep_time > 0:
        log(f"Waiting {sleep_time/60:.1f} minutes until next candle...")
        time.sleep(sleep_time)


def sync_positions_with_exchange(executor: OrderExecutor, manager: PositionManager):
    """
    Reconcile bot state with Binance exchange reality.
    - Adopt untracked positions
    - Clear tracked positions that are gone
    Raises httpx errors for retry_with_backoff.
    """
    exchange_positions = executor.get_all_open_positions()
    exchange_symbols = {p['symbol'] for p in exchange_positions}
    tracked_symbols = set(manager.positions.keys())

    # Positions we track that exchange no longer has → closed externally (TP/SL hit)
    for sym in tracked_symbols - exchange_symbols:
        log(f"AUTO-RECOVERY: {sym} closed on exchange — determining outcome", "warning")
        pos = manager.positions[sym]
        executor.cancel_all_orders(sym)

        last_trade = executor.get_last_trade(sym)
        if last_trade:
            exit_price = float(last_trade['price'])
            if pos.direction == "LONG":
                was_win = exit_price > pos.entry_price
            else:
                was_win = exit_price < pos.entry_price

            if was_win:
                manager.close_win(sym, exit_price)
            else:
                manager.close_loss(sym, exit_price)
        else:
            log(f"AUTO-RECOVERY: No trade data for {sym}, removing position", "warning")
            manager.remove_position(sym)

        save_state(manager)

    # Positions on exchange that we don't track → adopt them
    for p in exchange_positions:
        sym = p['symbol']
        if sym not in tracked_symbols:
            log(f"AUTO-RECOVERY: Adopting untracked position {sym}", "warning")
            position = executor.get_position(sym)
            entry_price = float(position['entryPrice'])
            entry_qty = abs(float(position['positionAmt']))
            direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"

            manager.enter(sym, direction, entry_price, entry_qty, 0.0)

            # Place SL if missing
            executor.verify_and_place_missing_sl(
                symbol=sym, direction=direction,
                tp_price=manager.tp_price(sym),
                sl_price=manager.sl_price(sym),
                quantity=entry_qty,
            )
            save_state(manager)


def check_position_closed(executor: OrderExecutor, symbol: str, position: Optional[dict] = None) -> Optional[str]:
    """Check if position is closed. Returns "WIN", "LOSS", or None."""
    try:
        if position is None:
            position = executor.get_position(symbol)
        if position is None:
            return None
        if float(position["positionAmt"]) == 0:
            last_trade = executor.get_last_trade(symbol)
            if last_trade:
                return "WIN" if float(last_trade["realizedPnl"]) > 0 else "LOSS"
        return None
    except Exception as e:
        log(f"Error checking position {symbol}: {e}", "error")
        return None


async def main_loop():
    log("=" * 80)
    log("MULTI-POSITION SIGNAL SCANNER - STARTING")
    log("=" * 80)
    log(f"Base size: {config.BASE_SIZE_PCT*100:.1f}% of balance | Leverage: {config.LEVERAGE}x")
    log(f"TP: {config.TP_PCT*100:.2f}% | SL: {config.SL_PCT*100:.2f}%")
    log(f"Max positions: {'unlimited' if config.MAX_POSITIONS == 0 else config.MAX_POSITIONS}")
    log(f"Scan interval: {config.SCAN_INTERVAL_SECS}s | Timeout: {config.MAX_HOLD_CANDLES} candles ({config.MAX_HOLD_CANDLES * config.SCAN_INTERVAL_SECS / 3600:.1f}h)")

    # Start health server
    threading.Thread(target=start_health_server, daemon=True).start()

    # Init components
    scanner = PairScanner()
    scorer = SignalScorer()
    manager = PositionManager()
    executor = OrderExecutor()
    safety_checker = SafetyChecker()
    manager.set_executor(executor)
    setup_signal_handlers(manager)

    # Load saved state
    saved = load_state()
    if saved and "positions" in saved:
        manager.load_from_dict(saved)
        log(f"Restored {manager.num_open} positions from state file")
    elif saved:
        # Old single-position state format — skip, reconcile from exchange
        log("Old state format detected — will reconcile from exchange", "warning")

    # Initial reconciliation with exchange
    try:
        sync_positions_with_exchange(executor, manager)
    except Exception as e:
        log(f"Initial sync failed: {e}", "error")

    # Force re-place ALL SL orders at startup with current buffer settings
    # Old SLs may have stale 0.5% buffer — cancel and re-place with 3% buffer
    log(f"Re-placing SL orders for {manager.num_open} positions with {config.SL_LIMIT_BUFFER_PCT*100:.1f}% buffer...")
    for sym, pos in list(manager.positions.items()):
        try:
            # Cancel existing algo orders (old SLs)
            try:
                algo_orders = executor.get_algo_open_orders(sym)
                if algo_orders:
                    for order in algo_orders:
                        if order.get('algoType') == 'CONDITIONAL':
                            log(f"Cancelling old SL for {sym} (algoId: {order.get('algoId')})")
                    # Cancel all algo orders for this symbol
                    params = {"symbol": sym}
                    params = executor._sign_params(params)
                    executor.client.delete(
                        f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
                        params=params,
                        headers=executor._headers()
                    )
            except Exception as cancel_err:
                log(f"Error cancelling old SL for {sym}: {cancel_err}", "warning")

            # Place fresh SL with current buffer
            sl_ok = executor.verify_and_place_missing_sl(
                symbol=sym, direction=pos.direction,
                tp_price=manager.tp_price(sym),
                sl_price=manager.sl_price(sym),
                quantity=pos.entry_quantity,
            )
            if not sl_ok:
                log(f"CRITICAL: Cannot place SL for {sym} at startup — closing position", "error")
                executor.cancel_all_orders(sym)
                try:
                    close_order = executor.close_position_market(sym, pos.direction, pos.entry_quantity)
                    exit_price = float(close_order["avgPrice"])
                    manager.close_loss(sym, exit_price)
                    save_state(manager)
                except Exception as close_err:
                    log(f"CRITICAL: Cannot close unprotected {sym}: {close_err}", "error")
        except Exception as e:
            log(f"Error re-placing SL for {sym}: {e}", "error")

    try:
        while True:
            wait_until_next_candle(config.SCAN_INTERVAL_SECS)

            log("-" * 80)
            log(f"CYCLE START | Open positions: {manager.num_open}")

            # Sync time
            try:
                retry_with_backoff(lambda: executor._sync_server_time())
            except Exception as e:
                log(f"Time sync failed: {e}", "warning")

            # Reconcile state with exchange
            try:
                retry_with_backoff(lambda: sync_positions_with_exchange(executor, manager))
            except Exception as e:
                log(f"State sync failed after retries: {e}", "error")
                log("Skipping this cycle — will retry next candle", "warning")
                continue

            manager.clean_expired_blacklist()
            now = time.time()

            # ── Manage existing positions ────────────────────────────────
            for sym in list(manager.positions.keys()):
                pos = manager.positions.get(sym)
                if not pos:
                    continue

                candles = manager.candles_held(sym, now)

                # 1. Check timeout
                if manager.is_timed_out(sym, now):
                    log(f"TIMEOUT: {sym} held {candles} candles — closing at market")
                    executor.cancel_all_orders(sym)
                    try:
                        close_order = executor.close_position_market(sym, pos.direction, pos.entry_quantity)
                        exit_price = float(close_order["avgPrice"])

                        if pos.direction == "LONG":
                            profitable = exit_price > pos.entry_price
                        else:
                            profitable = exit_price < pos.entry_price

                        if profitable:
                            manager.close_win(sym, exit_price)
                        else:
                            manager.close_loss(sym, exit_price)
                        save_state(manager)
                    except Exception as e:
                        log(f"Error closing timed-out {sym}: {e}", "error")
                    continue

                # 2. Check if closed by TP/SL
                position = executor.get_position(sym)
                outcome = check_position_closed(executor, sym, position=position)

                if outcome:
                    executor.cancel_all_orders(sym)
                    last_trade = executor.get_last_trade(sym)
                    exit_price = float(last_trade["price"])

                    if outcome == "WIN":
                        manager.close_win(sym, exit_price)
                    else:
                        manager.close_loss(sym, exit_price)
                    save_state(manager)

                    stats = manager.stats()
                    log(f"STATS: {stats['total_trades']} trades | WR: {stats['win_rate']*100:.1f}% | "
                        f"PnL: {format_usd(stats['total_pnl'])} | Open: {stats['open_positions']}")
                    continue

                # 3. Still holding — log status and enforce SL
                if position:
                    unrealized_pnl = float(position["unRealizedProfit"])
                    mark_price = float(position["markPrice"])
                    drawdown = manager.update_mae(sym, mark_price, candles)

                    log(f"HOLDING: {sym} {pos.direction} | Candles: {candles} | "
                        f"PnL: {format_usd(unrealized_pnl)} | Drawdown: {drawdown:.2f}% | "
                        f"MAE: {pos.max_adverse_excursion_pct:.2f}%")

                    # EMERGENCY SL ENFORCEMENT: If price has blown past SL by 2x, force close at market
                    sl_price = manager.sl_price(sym)
                    sl_distance = abs(pos.entry_price - sl_price)
                    emergency_distance = sl_distance * config.SL_EMERGENCY_CLOSE_MULT

                    if pos.direction == "LONG":
                        adverse_move = pos.entry_price - mark_price
                    else:
                        adverse_move = mark_price - pos.entry_price

                    if adverse_move > emergency_distance:
                        adverse_pct = (adverse_move / pos.entry_price) * 100
                        log(f"EMERGENCY CLOSE: {sym} {pos.direction} | Price moved {adverse_pct:.1f}% against — "
                            f"past {config.SL_EMERGENCY_CLOSE_MULT:.0f}x SL distance. SL failed to execute!", "error")
                        executor.cancel_all_orders(sym)
                        try:
                            close_order = executor.close_position_market(sym, pos.direction, pos.entry_quantity)
                            exit_price = float(close_order["avgPrice"])
                            manager.close_loss(sym, exit_price)
                            save_state(manager)
                            log(f"EMERGENCY CLOSED: {sym} @ {exit_price}", "error")
                        except Exception as e:
                            log(f"CRITICAL: Emergency close FAILED for {sym}: {e}", "error")
                        continue

                    # SL verification EVERY cycle (not just every 5 candles)
                    sl_ok = executor.verify_and_place_missing_sl(
                        symbol=sym, direction=pos.direction,
                        tp_price=manager.tp_price(sym),
                        sl_price=manager.sl_price(sym),
                        quantity=pos.entry_quantity,
                    )
                    if not sl_ok:
                        log(f"CRITICAL: Cannot place SL for {sym} — closing position", "error")
                        executor.cancel_all_orders(sym)
                        try:
                            close_order = executor.close_position_market(sym, pos.direction, pos.entry_quantity)
                            exit_price = float(close_order["avgPrice"])
                            manager.close_loss(sym, exit_price)
                            save_state(manager)
                        except Exception as e:
                            log(f"CRITICAL: Cannot close unprotected {sym}: {e}", "error")
                        continue

                    # Break-even protection at 36 candles
                    if candles >= 36 and unrealized_pnl < 0:
                        log(f"BREAK-EVEN: {sym} negative after {candles} candles — closing", "warning")
                        executor.cancel_all_orders(sym)
                        try:
                            close_order = executor.close_position_market(sym, pos.direction, pos.entry_quantity)
                            exit_price = float(close_order["avgPrice"])
                            manager.close_loss(sym, exit_price)
                            save_state(manager)
                        except Exception as e:
                            log(f"Error closing break-even {sym}: {e}", "error")

            # ── Look for new entries ─────────────────────────────────────
            if not manager.can_enter():
                log(f"At max positions ({manager.num_open}), skipping scan")
                continue

            safety = safety_checker.run_all_checks(manager, executor)
            if not safety.can_trade:
                log(f"BLOCKED: {safety.reason}")
                continue

            # Update balance for sizing
            manager.update_balance()

            # Scan and score
            pair_data = await scanner.scan_all_pairs()
            blacklisted = manager.get_blacklisted_symbols()
            open_symbols = manager.get_open_symbols()
            signals = scorer.score_all_pairs(pair_data, blacklisted + open_symbols)

            if safety.block_longs:
                signals = [s for s in signals if s.direction != "LONG"]
            if safety.block_shorts:
                signals = [s for s in signals if s.direction != "SHORT"]

            if not signals:
                log("No signals above threshold")
                continue

            # Enter as many positions as slots allow
            slots_available = (config.MAX_POSITIONS - manager.num_open) if config.MAX_POSITIONS > 0 else len(signals)
            entries_this_cycle = 0

            for signal in signals[:slots_available]:
                if manager.has_position(signal.symbol):
                    continue

                log(f"SIGNAL: {signal.symbol} {signal.direction} | Score={signal.score:.2f} | "
                    f"RSI={signal.rsi:.1f} BB={signal.bb_pct_b:.2f} Z={signal.zscore:.2f}")

                try:
                    # Verify no existing position on exchange
                    existing = executor.get_position(signal.symbol)
                    if existing and float(existing.get("positionAmt", 0)) != 0:
                        log(f"SKIP: {signal.symbol} already has position on exchange", "warning")
                        continue

                    # Set leverage and margin
                    if not executor.set_leverage(signal.symbol, config.LEVERAGE):
                        continue
                    try:
                        executor.set_margin_type(signal.symbol, "CROSSED")
                    except Exception:
                        continue

                    size_usd = manager.position_size_usd()
                    if not executor.check_orderbook_depth(signal.symbol, size_usd):
                        continue

                    # Place entry
                    entry_order = executor.place_market_order(
                        symbol=signal.symbol,
                        side="BUY" if signal.direction == "LONG" else "SELL",
                        notional_usd=size_usd,
                    )
                    entry_price = float(entry_order["avgPrice"])
                    entry_qty = float(entry_order["executedQty"])

                    manager.enter(signal.symbol, signal.direction, entry_price, entry_qty, signal.score)

                    # Calculate SL (widen for low volume)
                    base_sl = manager.sl_price(signal.symbol)
                    if signal.volume_24h > 0 and signal.volume_24h < config.LOW_VOLUME_THRESHOLD:
                        sl_distance = abs(entry_price - base_sl)
                        if signal.direction == "LONG":
                            adjusted_sl = entry_price - sl_distance * 1.5
                        else:
                            adjusted_sl = entry_price + sl_distance * 1.5
                        log(f"LOW VOL: Widening SL 1.5x → {adjusted_sl:.6f}", "warning")
                    else:
                        adjusted_sl = base_sl

                    # Place TP/SL
                    try:
                        executor.place_tp_sl_orders(
                            symbol=signal.symbol, direction=signal.direction,
                            tp_price=manager.tp_price(signal.symbol),
                            sl_price=adjusted_sl, quantity=entry_qty,
                        )
                    except Exception as tp_sl_err:
                        log(f"CRITICAL: TP/SL failed for {signal.symbol}: {tp_sl_err}", "error")
                        sl_ok = executor.verify_and_place_missing_sl(
                            symbol=signal.symbol, direction=signal.direction,
                            tp_price=manager.tp_price(signal.symbol),
                            sl_price=adjusted_sl, quantity=entry_qty,
                        )
                        if not sl_ok:
                            log(f"CLOSING {signal.symbol} — no SL protection", "error")
                            try:
                                executor.close_position_market(signal.symbol, signal.direction, entry_qty)
                                manager.remove_position(signal.symbol)
                                save_state(manager)
                            except Exception as close_err:
                                log(f"CRITICAL: Cannot close unprotected {signal.symbol}: {close_err}", "error")
                            continue

                    # Final SL verification
                    executor.verify_and_place_missing_sl(
                        symbol=signal.symbol, direction=signal.direction,
                        tp_price=manager.tp_price(signal.symbol),
                        sl_price=adjusted_sl, quantity=entry_qty,
                    )

                    save_state(manager)
                    log(f"ENTERED: {signal.symbol} {signal.direction} @ {entry_price:.6f} | "
                        f"Size={format_usd(size_usd)} | TP={manager.tp_price(signal.symbol):.6f} | "
                        f"SL={adjusted_sl:.6f} | Open: {manager.num_open}")

                    entries_this_cycle += 1

                except Exception as e:
                    log(f"ENTRY FAILED {signal.symbol}: {e}", "error")
                    continue

            if entries_this_cycle > 0:
                log(f"Entered {entries_this_cycle} new position(s) this cycle | Total open: {manager.num_open}")

    except KeyboardInterrupt:
        log("Shutting down...")
    except Exception as e:
        log(f"FATAL ERROR: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        await scanner.close()
        executor.close()
        safety_checker.close()
        save_state(manager)
        log("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main_loop())
