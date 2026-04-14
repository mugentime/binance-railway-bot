"""
Martingale Signal Scanner - Main Loop
Orchestrator - the main entry point
"""
import asyncio
import time
import math
from typing import Optional
from utils import log, save_state, load_state, format_usd, setup_signal_handlers
import config
from pair_scanner import PairScanner
from signal_scorer import SignalScorer
from martingale_manager import MartingaleManager
from order_executor import OrderExecutor
from safety_checks import SafetyChecker
import numpy as np

def detect_market_regime(executor) -> dict:
    """
    Detect market regime based on BTC's last 24 hours
    Returns: dict with 'regime' ('trending' or 'ranging'), 'slope_pct', 'atr_pct'
    """
    try:
        # Fetch 24 1h candles for BTCUSDT
        import httpx
        resp = httpx.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "limit": 24
            },
            timeout=10.0
        )
        resp.raise_for_status()
        candles = resp.json()

        # Extract closes and highs/lows
        closes = np.array([float(c[4]) for c in candles])  # Close prices
        highs = np.array([float(c[2]) for c in candles])   # High prices
        lows = np.array([float(c[3]) for c in candles])    # Low prices

        # Calculate ATR (Average True Range)
        high_low = highs - lows
        high_close = np.abs(highs[1:] - closes[:-1])
        low_close = np.abs(lows[1:] - closes[:-1])
        true_ranges = np.maximum(high_low[1:], np.maximum(high_close, low_close))
        atr = np.mean(true_ranges)
        current_price = closes[-1]
        atr_pct = (atr / current_price) * 100

        # Calculate SMA slope
        sma = np.mean(closes)
        # Linear regression slope over 24 periods
        x = np.arange(len(closes))
        slope, _ = np.polyfit(x, closes, 1)
        slope_pct = (slope / current_price) * 100  # Slope as % per candle

        # UPDATED THRESHOLDS - adjusted for current market volatility
        ATR_THRESHOLD = 0.65  # Adjusted from 0.5% to 0.65%
        SLOPE_THRESHOLD = 0.08  # Adjusted from 0.1% to 0.08%

        # Regime detection (original logic - no directional bias)
        if atr_pct > ATR_THRESHOLD and abs(slope_pct) > SLOPE_THRESHOLD:
            regime = "trending"
            reason = f"TRENDING (ATR={atr_pct:.2f}% > {ATR_THRESHOLD}%, |Slope|={abs(slope_pct):.4f}% > {SLOPE_THRESHOLD}%)"
        else:
            regime = "ranging"
            reason = f"RANGING (ATR={atr_pct:.2f}%, |Slope|={abs(slope_pct):.4f}%)"

        log(f"REGIME DETECTED: {regime.upper()} - {reason}")

        return {
            'regime': regime,
            'slope_pct': slope_pct,
            'atr_pct': atr_pct
        }

    except Exception as e:
        log(f"Error detecting regime: {e} - defaulting to 'ranging'", "warning")
        return {
            'regime': 'ranging',
            'slope_pct': 0.0,
            'atr_pct': 0.0
        }

def wait_until_next_candle(interval_secs: int = 300):
    """Wait until next candle boundary (5m by default)"""
    now = time.time()
    next_candle = math.ceil(now / interval_secs) * interval_secs + 2  # +2s buffer
    sleep_time = next_candle - now

    if sleep_time > 0:
        minutes = sleep_time / 60
        log(f"Waiting {minutes:.1f} minutes until next candle...")
        time.sleep(sleep_time)

def verify_and_sync_state(executor: OrderExecutor, manager: MartingaleManager) -> bool:
    """
    Verify bot state matches Binance reality and auto-correct discrepancies
    Returns: True if state is synchronized, False if critical error
    """
    try:
        all_open = executor.get_all_open_positions()

        # Case 1: Bot thinks position open, but exchange says closed
        if manager.in_position and not all_open:
            log(f"AUTO-RECOVERY: Bot state says in position ({manager.current_symbol}), "
                f"but no positions on exchange - clearing state", "warning")
            manager._clear_position()
            save_state(manager)
            return True

        # Case 2: Bot thinks no position, but exchange has position(s)
        elif not manager.in_position and all_open:
            if len(all_open) > 1:
                symbols = [f"{p['symbol']} ({p['positionAmt']})" for p in all_open]
                log(f"CRITICAL: Multiple positions detected: {', '.join(symbols)}", "error")
                log(f"Please manually close all but one position before restarting", "error")
                return False

            log(f"AUTO-RECOVERY: Bot state says no position, but {all_open[0]['symbol']} "
                f"is open on exchange - adopting position", "warning")
            position = executor.get_position(all_open[0]['symbol'])
            manager.in_position = True
            manager.current_symbol = all_open[0]['symbol']
            manager.entry_price = float(position['entryPrice'])
            manager.entry_quantity = abs(float(position['positionAmt']))
            manager.current_direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
            manager.entry_candle_time = time.time()  # Approximate
            manager.current_size_usd = abs(float(position['positionAmt'])) * float(position['entryPrice'])
            save_state(manager)
            log(f"Adopted position: {manager.current_symbol} {manager.current_direction} @ "
                f"{manager.entry_price:.6f} | Qty: {manager.entry_quantity}", "warning")
            return True

        # Case 3: Both think position open - verify it's the SAME position
        elif manager.in_position and all_open:
            if len(all_open) > 1:
                symbols = [f"{p['symbol']} ({p['positionAmt']})" for p in all_open]
                log(f"CRITICAL: Multiple positions detected: {', '.join(symbols)}", "error")
                log(f"Please manually close all but one position before restarting", "error")
                return False

            exchange_symbol = all_open[0]['symbol']
            if manager.current_symbol != exchange_symbol:
                log(f"AUTO-RECOVERY: State mismatch - bot tracks {manager.current_symbol}, "
                    f"but exchange shows {exchange_symbol} - adopting exchange", "warning")
                position = executor.get_position(exchange_symbol)
                manager.current_symbol = exchange_symbol
                manager.entry_price = float(position['entryPrice'])
                manager.entry_quantity = abs(float(position['positionAmt']))
                manager.current_direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
                manager.current_size_usd = abs(float(position['positionAmt'])) * float(position['entryPrice'])
                save_state(manager)
                log(f"Corrected position tracking: {manager.current_symbol} {manager.current_direction} @ "
                    f"{manager.entry_price:.6f}", "warning")

        # Case 4: Both agree - no sync needed
        return True

    except Exception as e:
        log(f"Error during state verification: {e}", "error")
        return False

def check_position_closed(executor: OrderExecutor, manager: MartingaleManager) -> Optional[str]:
    """
    Check if position is closed and determine outcome
    Returns: "WIN", "LOSS", or None if still open
    """
    try:
        position = executor.get_position(manager.current_symbol)

        if position is None:
            log(f"WARNING: Could not fetch position for {manager.current_symbol}", "warning")
            return None

        if float(position["positionAmt"]) == 0:
            # Position closed - check last trade
            last_trade = executor.get_last_trade(manager.current_symbol)

            if last_trade:
                realized_pnl = float(last_trade["realizedPnl"])

                if realized_pnl > 0:
                    return "WIN"
                else:
                    return "LOSS"

        return None

    except Exception as e:
        log(f"Error checking position: {e}", "error")
        return None

async def main_loop():
    """Main trading loop"""
    log("="*80)
    log("MARTINGALE SIGNAL SCANNER - STARTING")
    log("="*80)
    log(f"Base size: {config.BASE_SIZE_PCT*100:.1f}% of balance | Leverage: {config.LEVERAGE}x | Max level: {config.MAX_LEVEL}")
    log(f"TP: {config.TP_PCT*100:.2f}% | SL: {config.SL_PCT*100:.2f}%")
    log(f"Scan interval: {config.SCAN_INTERVAL_SECS}s | Entry threshold: {config.ENTRY_THRESHOLD}")

    # Initialize components
    scanner = PairScanner()
    scorer = SignalScorer()
    manager = MartingaleManager()
    executor = OrderExecutor()
    safety_checker = SafetyChecker()

    # Set executor reference for dynamic balance fetching
    manager.set_executor(executor)

    # Setup graceful shutdown handlers
    setup_signal_handlers(manager)

    # Load existing state (crash recovery)
    saved_state = load_state()
    if saved_state:
        manager.level = saved_state.get("level", 0)
        manager.in_position = saved_state.get("in_position", False)
        manager.current_symbol = saved_state.get("current_symbol")
        manager.current_direction = saved_state.get("current_direction")
        manager.entry_price = saved_state.get("entry_price")
        manager.entry_quantity = saved_state.get("entry_quantity")
        manager.current_size_usd = saved_state.get("current_size_usd", 0.0)
        manager.entry_candle_time = saved_state.get("entry_candle_time")
        manager.last_max_loss_time = saved_state.get("last_max_loss_time", 0)
        manager.cooldown_blacklist = saved_state.get("cooldown_blacklist", {})
        manager.max_adverse_excursion_pct = saved_state.get("max_adverse_excursion_pct", 0.0)
        manager.mae_candle = saved_state.get("mae_candle", 0)

        log(f"State restored: level={manager.level}, in_position={manager.in_position}")

        if manager.cooldown_blacklist:
            log(f"Blacklist restored: {len(manager.cooldown_blacklist)} symbols on cooldown")

        # STARTUP VERIFICATION: Check all open positions on exchange
        all_open = executor.get_all_open_positions()
        if all_open:
            log(f"STARTUP: Found {len(all_open)} open position(s) on exchange:")
            for p in all_open:
                symbol = p['symbol']
                qty = float(p['positionAmt'])
                direction = "LONG" if qty > 0 else "SHORT"
                entry = float(p['entryPrice'])
                pnl = float(p['unRealizedProfit'])
                log(f"  - {symbol} {direction} | Qty: {abs(qty)} | Entry: {entry:.6f} | PNL: ${pnl:.2f}")

            if len(all_open) > 1:
                log(f"ERROR: Multiple positions detected! Bot only supports 1 position at a time.", "error")
                log(f"Please manually close all but one position on Binance before restarting.", "error")
                return  # Exit bot

            # Check if position matches bot state
            exchange_symbol = all_open[0]['symbol']
            if manager.in_position:
                if manager.current_symbol != exchange_symbol:
                    log(f"WARNING: State mismatch - Bot thinks position is {manager.current_symbol}, "
                        f"but exchange shows {exchange_symbol}", "warning")
                    log(f"Adopting exchange position: {exchange_symbol}", "warning")
                    # Update bot state to match reality
                    position = executor.get_position(exchange_symbol)
                    manager.current_symbol = exchange_symbol
                    manager.entry_price = float(position['entryPrice'])
                    manager.entry_quantity = abs(float(position['positionAmt']))
                    manager.current_direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
            else:
                log(f"WARNING: Bot thinks no position, but {exchange_symbol} is open on exchange", "warning")
                log(f"Adopting exchange position: {exchange_symbol}", "warning")
                manager.in_position = True
                position = executor.get_position(exchange_symbol)
                manager.current_symbol = exchange_symbol
                manager.entry_price = float(position['entryPrice'])
                manager.entry_quantity = abs(float(position['positionAmt']))
                manager.current_direction = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
                manager.entry_candle_time = time.time()  # Approximate

        # If in position, check if it's still open
        if manager.in_position:
            try:
                position = executor.get_position(manager.current_symbol)

                if position is None:
                    log(f"ERROR: Failed to fetch position for {manager.current_symbol} on startup - RETRYING", "error")
                    time.sleep(5)  # Wait 5 seconds
                    position = executor.get_position(manager.current_symbol)

                    if position is None:
                        log(f"CRITICAL: Still cannot fetch position after retry - EXITING to prevent multiple positions", "error")
                        log(f"Please manually check your position for {manager.current_symbol} on Binance before restarting", "error")
                        return  # Exit the bot safely
                elif float(position["positionAmt"]) == 0:
                    log(f"Position {manager.current_symbol} was closed while offline - checking outcome...")
                    outcome = check_position_closed(executor, manager)

                    # Get actual exit price from last trade
                    last_trade = executor.get_last_trade(manager.current_symbol)
                    exit_price = float(last_trade["price"]) if last_trade else float(position.get("entryPrice", 0))

                    if outcome == "WIN":
                        manager.close_win(exit_price)
                    else:
                        manager.close_loss(exit_price)
                    save_state(manager)
            except Exception as e:
                log(f"Error checking position on startup: {e}", "error")

    try:
        while True:
            # Wait for next candle
            wait_until_next_candle(config.SCAN_INTERVAL_SECS)

            log("-"*80)
            log(f"CYCLE START | Level={manager.level} | In position={manager.in_position}")

            # CRITICAL: Verify state is synchronized with exchange
            if not verify_and_sync_state(executor, manager):
                log("State verification failed - stopping bot for safety", "error")
                return

            # Clean expired blacklist entries
            manager.clean_expired_blacklist()

            # If in position, check for timeout first
            if manager.in_position:
                # Check timeout before checking TP/SL
                if manager.is_timed_out(time.time()):
                    log(f"TIMEOUT — position held > {config.MAX_HOLD_CANDLES} candles, closing at market")

                    # Cancel all pending orders
                    executor.cancel_all_orders(manager.current_symbol)

                    # Close position at market
                    try:
                        close_order = executor.close_position_market(
                            manager.current_symbol,
                            manager.current_direction,
                            manager.entry_quantity
                        )
                        exit_price = float(close_order["avgPrice"])

                        # Check if position was already closed (e.g., by SL)
                        if close_order.get("alreadyClosed"):
                            log(f"ALREADY CLOSED: {manager.current_symbol} @ {exit_price:.6f} (SL algo order likely triggered)")
                        else:
                            log(f"TIMEOUT CLOSE: {manager.current_symbol} @ {exit_price:.6f}")

                        # Record as loss (timeout = failed trade)
                        manager.close_loss(exit_price)
                        save_state(manager)

                    except Exception as e:
                        log(f"Error closing timed-out position: {e}", "error")
                        import traceback
                        traceback.print_exc()

                    # Continue to next cycle to look for new entry
                    continue

                # Check if position closed normally (TP/SL hit)
                outcome = check_position_closed(executor, manager)

                if outcome:
                    # Position closed
                    executor.cancel_all_orders(manager.current_symbol)

                    last_trade = executor.get_last_trade(manager.current_symbol)
                    exit_price = float(last_trade["price"])

                    if outcome == "WIN":
                        manager.close_win(exit_price)
                    else:
                        manager.close_loss(exit_price)

                    save_state(manager)

                    # Print stats
                    stats = manager.stats()
                    log(f"STATS: {stats['total_trades']} trades | "
                        f"WR: {stats['win_rate']*100:.1f}% | "
                        f"PnL: {format_usd(stats['total_pnl'])} | "
                        f"Level: {stats['current_level']}")

                else:
                    # Still in position
                    position = executor.get_position(manager.current_symbol)

                    if position is None:
                        log(f"ERROR: Failed to fetch position for {manager.current_symbol}, skipping cycle", "error")
                        continue

                    unrealized_pnl = float(position["unRealizedProfit"])
                    mark_price = float(position["markPrice"])
                    candles_held = manager.candles_held(time.time())

                    # Update MAE tracking
                    current_drawdown_pct = manager.update_mae(mark_price, candles_held)

                    # Log current position status with drawdown
                    log(f"HOLDING: {manager.current_symbol} {manager.current_direction} | "
                        f"Candles: {candles_held} | Unrealized PnL: {format_usd(unrealized_pnl)} | "
                        f"Drawdown: {current_drawdown_pct:.2f}% | MAE: {manager.max_adverse_excursion_pct:.2f}% @ candle {manager.mae_candle}")

                    # Break-even protection: after 12 candles, close if negative
                    if candles_held >= 12 and unrealized_pnl < 0:
                        log(f"BREAK-EVEN PROTECTION: {candles_held} candles held, PnL negative "
                            f"({format_usd(unrealized_pnl)}) → closing at market", "warning")

                        # Cancel all pending orders
                        executor.cancel_all_orders(manager.current_symbol)

                        # Close position at market
                        try:
                            close_order = executor.close_position_market(
                                manager.current_symbol,
                                manager.current_direction,
                                manager.entry_quantity
                            )
                            exit_price = float(close_order["avgPrice"])

                            # Check if position was already closed (e.g., by SL)
                            if close_order.get("alreadyClosed"):
                                log(f"ALREADY CLOSED: {manager.current_symbol} @ {exit_price:.6f} (SL algo order likely triggered)")

                            # Record as loss
                            manager.close_loss(exit_price)
                            save_state(manager)

                            log(f"BREAK-EVEN CLOSE: {manager.current_symbol} @ {exit_price:.6f} | "
                                f"PnL: {format_usd(unrealized_pnl)}")

                            # Print stats
                            stats = manager.stats()
                            log(f"STATS: {stats['total_trades']} trades | "
                                f"WR: {stats['win_rate']*100:.1f}% | "
                                f"PnL: {format_usd(stats['total_pnl'])} | "
                                f"Level: {stats['current_level']}")

                        except Exception as e:
                            log(f"Error closing break-even position: {e}", "error")
                            import traceback
                            traceback.print_exc()

                        continue

                    continue

            # Check if we can enter new position
            if not manager.can_enter():
                log("Cannot enter: level > max or other constraint")
                continue

            # Run safety checks
            safety = safety_checker.run_all_checks(manager, executor)

            if not safety.can_trade:
                log(f"BLOCKED: {safety.reason}")
                continue

            # Detect market regime
            regime_data = detect_market_regime(executor)

            # Scan and score pairs
            log("Scanning pairs...")
            pair_data = await scanner.scan_all_pairs()

            log("Scoring signals...")
            blacklisted = manager.get_blacklisted_symbols()
            signals = scorer.score_all_pairs(pair_data, blacklisted, regime_data)

            # Filter by safety blocks
            if safety.block_longs:
                signals = [s for s in signals if s.direction != "LONG"]
            if safety.block_shorts:
                signals = [s for s in signals if s.direction != "SHORT"]

            if not signals:
                log("No signals above threshold")
                continue

            # Get best signal
            best = signals[0]
            log(f"BEST SIGNAL: {best.symbol} {best.direction} | Score={best.score:.2f} | "
                f"RSI={best.rsi:.1f} BB={best.bb_pct_b:.2f} Z={best.zscore:.2f}")

            # Update balance for dynamic position sizing (cache for full Martingale chain)
            manager.update_chain_start_balance()

            # Enter position
            try:
                # FINAL SAFETY CHECK: Verify NO positions exist before entering
                # (State sync should have caught this, but double-check)
                all_open = executor.get_all_open_positions()
                if all_open:
                    symbols = [f"{p['symbol']} ({p['positionAmt']})" for p in all_open]
                    log(f"BLOCKED: Cannot enter {best.symbol} - {len(all_open)} position(s) already open: {', '.join(symbols)}", "error")
                    log(f"This should have been caught by state verification - skipping entry this cycle", "warning")
                    # Continue to next cycle instead of stopping bot
                    continue

                # Set leverage and margin type
                leverage_ok = executor.set_leverage(best.symbol, config.LEVERAGE)
                if not leverage_ok:
                    log(f"Skipping {best.symbol}: Leverage {config.LEVERAGE}x not supported", "warning")
                    continue

                try:
                    executor.set_margin_type(best.symbol, "CROSSED")
                except Exception as margin_error:
                    log(f"Skipping {best.symbol}: Failed to set margin type - {margin_error}", "warning")
                    continue

                # ORDERBOOK DEPTH CHECK: Verify sufficient liquidity before entry
                size_usd = manager.position_size_usd()
                if not executor.check_orderbook_depth(best.symbol, size_usd):
                    log(f"Skipping {best.symbol}: Insufficient orderbook depth", "warning")
                    continue

                # Place market entry
                entry_order = executor.place_market_order(
                    symbol=best.symbol,
                    side="BUY" if best.direction == "LONG" else "SELL",
                    notional_usd=size_usd,
                )

                entry_price = float(entry_order["avgPrice"])
                entry_qty = float(entry_order["executedQty"])

                # Update manager
                manager.enter(best.symbol, best.direction, entry_price, entry_qty, best.score)

                # Calculate adjusted SL for low-volume pairs (widen by 1.5x)
                base_sl_price = manager.sl_price()

                if best.volume_24h > 0 and best.volume_24h < config.LOW_VOLUME_THRESHOLD:
                    # Low volume pair - widen SL by 1.5x
                    sl_distance = abs(entry_price - base_sl_price)
                    widened_distance = sl_distance * 1.5

                    if best.direction == "LONG":
                        adjusted_sl_price = entry_price - widened_distance
                    else:  # SHORT
                        adjusted_sl_price = entry_price + widened_distance

                    log(f"LOW VOLUME PAIR ({format_usd(best.volume_24h)} < {format_usd(config.LOW_VOLUME_THRESHOLD)}): "
                        f"Widening SL by 1.5x: {base_sl_price:.6f} → {adjusted_sl_price:.6f}", "warning")
                else:
                    adjusted_sl_price = base_sl_price

                # Place TP/SL
                executor.place_tp_sl_orders(
                    symbol=best.symbol,
                    direction=best.direction,
                    tp_price=manager.tp_price(),
                    sl_price=adjusted_sl_price,
                    quantity=entry_qty,
                )

                # Save state
                save_state(manager)

                log(f"ENTERED: {best.symbol} {best.direction} @ {entry_price:.6f} | "
                    f"Level={manager.level} | Size={format_usd(size_usd)} | "
                    f"TP={manager.tp_price():.6f} | SL={adjusted_sl_price:.6f}")

            except Exception as e:
                log(f"ENTRY FAILED: {e}", "error")
                import traceback
                traceback.print_exc()
                continue

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
        log("Shutdown complete")

if __name__ == "__main__":
    asyncio.run(main_loop())
