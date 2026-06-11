#!/usr/bin/env python3
"""
Realistic Exit Simulation with Proper Timing

Simulates actual entry → exit path for each trade:
1. Detects entry signal from precursor indicators
2. Tracks price movement for 30 minutes after entry
3. Checks TP/SL/time-based exits with actual timing
4. Calculates realistic P&L with proper win/loss counts

No more bullshit assumptions about instant TP hits.
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timezone

# Windows console encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Exit parameters
STOP_LOSS = 0.025  # 2.5%
TAKE_PROFIT_LONG = 0.10  # 10% for UP
TAKE_PROFIT_SHORT = 0.08  # 8% for DOWN
TIME_EXIT_PROFITABLE = 15 * 60 * 1000  # 15 min if >3% profit (ms)
TIME_EXIT_HARD_CAP = 30 * 60 * 1000  # 30 min hard cap (ms)
PROFIT_THRESHOLD = 0.03  # 3% for early time exit

# Entry thresholds (ideal settings from research)
RSI_SHORT = 55
RSI_LONG = 45
BB_SHORT = 0.6
BB_LONG = 0.3
Z_SHORT = 0.5
Z_LONG = -0.5

BINANCE_BASE = "https://fapi.binance.com"


def get_klines(symbol, interval="1m", start_time=None, end_time=None, limit=1000):
    """Fetch klines from Binance"""
    try:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        r = requests.get(f"{BINANCE_BASE}/fapi/v1/klines", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  Error fetching klines: {e}")
        return None


def check_entry_signal(candle):
    """Check if candle meets entry signal criteria"""
    rsi = candle.get('rsi')
    bb_pct_b = candle.get('bb_pct_b')
    zscore = candle.get('zscore')

    if rsi is None or bb_pct_b is None or zscore is None:
        return None

    # SHORT signal
    if rsi > RSI_SHORT and bb_pct_b > BB_SHORT and zscore > Z_SHORT:
        return 'SHORT'

    # LONG signal
    if rsi < RSI_LONG and bb_pct_b < BB_LONG and zscore < Z_LONG:
        return 'LONG'

    return None


def simulate_trade(symbol, entry_time, entry_price, direction):
    """
    Simulate trade from entry to exit with 1-minute klines

    Args:
        symbol: Trading symbol
        entry_time: Entry timestamp (ms)
        entry_price: Entry price
        direction: 'LONG' or 'SHORT'

    Returns:
        Dict with exit details
    """
    # Fetch 1-min klines for 30 minutes after entry
    end_time = entry_time + TIME_EXIT_HARD_CAP
    klines = get_klines(symbol, "1m", entry_time, end_time, limit=30)

    if not klines or len(klines) < 2:
        return None

    # Track trade progress
    max_profit = 0
    max_drawdown = 0
    minutes_held = 0

    for i, kline in enumerate(klines):
        candle_time = int(kline[0])
        high = float(kline[2])
        low = float(kline[3])
        close = float(kline[4])

        time_elapsed = candle_time - entry_time
        minutes_held = (i + 1)

        # Calculate current profit
        if direction == 'LONG':
            profit_at_high = (high - entry_price) / entry_price
            profit_at_low = (low - entry_price) / entry_price
            profit_at_close = (close - entry_price) / entry_price

            # Check SL hit (low reached SL)
            if profit_at_low <= -STOP_LOSS:
                return {
                    'exit_reason': 'SL',
                    'exit_price': entry_price * (1 - STOP_LOSS),
                    'pnl_pct': -STOP_LOSS,
                    'minutes_held': minutes_held,
                    'max_profit': max_profit,
                    'max_drawdown': max_drawdown
                }

            # Check TP hit (high reached TP)
            if profit_at_high >= TAKE_PROFIT_LONG:
                return {
                    'exit_reason': 'TP',
                    'exit_price': entry_price * (1 + TAKE_PROFIT_LONG),
                    'pnl_pct': TAKE_PROFIT_LONG,
                    'minutes_held': minutes_held,
                    'max_profit': max(max_profit, profit_at_high),
                    'max_drawdown': max_drawdown
                }

            max_profit = max(max_profit, profit_at_high)
            max_drawdown = min(max_drawdown, profit_at_low)

            # Time-based exit: 15 min if >3% profit
            if time_elapsed >= TIME_EXIT_PROFITABLE and profit_at_close >= PROFIT_THRESHOLD:
                return {
                    'exit_reason': 'TIME_PROFITABLE',
                    'exit_price': close,
                    'pnl_pct': profit_at_close,
                    'minutes_held': minutes_held,
                    'max_profit': max_profit,
                    'max_drawdown': max_drawdown
                }

        else:  # SHORT
            profit_at_high = (entry_price - high) / entry_price
            profit_at_low = (entry_price - low) / entry_price
            profit_at_close = (entry_price - close) / entry_price

            # Check SL hit (high reached SL)
            if profit_at_high <= -STOP_LOSS:
                return {
                    'exit_reason': 'SL',
                    'exit_price': entry_price * (1 + STOP_LOSS),
                    'pnl_pct': -STOP_LOSS,
                    'minutes_held': minutes_held,
                    'max_profit': max_profit,
                    'max_drawdown': max_drawdown
                }

            # Check TP hit (low reached TP)
            if profit_at_low >= TAKE_PROFIT_SHORT:
                return {
                    'exit_reason': 'TP',
                    'exit_price': entry_price * (1 - TAKE_PROFIT_SHORT),
                    'pnl_pct': TAKE_PROFIT_SHORT,
                    'minutes_held': minutes_held,
                    'max_profit': max(max_profit, profit_at_low),
                    'max_drawdown': max_drawdown
                }

            max_profit = max(max_profit, profit_at_low)
            max_drawdown = min(max_drawdown, profit_at_high)

            # Time-based exit: 15 min if >3% profit
            if time_elapsed >= TIME_EXIT_PROFITABLE and profit_at_close >= PROFIT_THRESHOLD:
                return {
                    'exit_reason': 'TIME_PROFITABLE',
                    'exit_price': close,
                    'pnl_pct': profit_at_close,
                    'minutes_held': minutes_held,
                    'max_profit': max_profit,
                    'max_drawdown': max_drawdown
                }

    # 30-min hard cap - force close at last close price
    final_close = float(klines[-1][4])
    if direction == 'LONG':
        final_pnl = (final_close - entry_price) / entry_price
    else:
        final_pnl = (entry_price - final_close) / entry_price

    return {
        'exit_reason': 'TIME_HARD_CAP',
        'exit_price': final_close,
        'pnl_pct': final_pnl,
        'minutes_held': minutes_held,
        'max_profit': max_profit,
        'max_drawdown': max_drawdown
    }


def main():
    """Main execution"""
    print("="*80)
    print("REALISTIC EXIT SIMULATION - Proper Timing Analysis")
    print("="*80)
    print()

    # Load precursor data
    analysis_dir = Path(__file__).parent
    precursor_file = analysis_dir / '226_movers_precursors.json'

    print(f"Loading precursor data from: {precursor_file}")
    with open(precursor_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    movers = data['movers']
    print(f"✓ Loaded {len(movers)} movers\n")

    # Track results
    trades = []
    entries_skipped = 0

    print("Simulating trades with proper entry → exit timing...")
    print("-"*80)

    for i, mover in enumerate(movers, 1):
        symbol = mover['symbol']
        move_pct = mover['move_metadata']['move_pct']
        actual_direction = mover['move_metadata']['direction']
        precursors = mover['precursor_candles']

        print(f"\n[{i}/{len(movers)}] {symbol} (actual move: {move_pct:+.1f}% {actual_direction})")

        # Check each precursor candle for entry signal
        entry_signal = None
        entry_candle = None

        for candle in precursors:
            signal = check_entry_signal(candle)
            if signal:
                entry_signal = signal
                entry_candle = candle
                break

        if not entry_signal:
            print(f"  → No entry signal detected")
            entries_skipped += 1
            continue

        # Entry detected
        entry_time = entry_candle['timestamp']
        entry_price = entry_candle['close']

        print(f"  → Entry signal: {entry_signal} at {entry_candle['time']}")
        print(f"     Price: ${entry_price:.6f}")
        print(f"     RSI: {entry_candle['rsi']}, BB: {entry_candle['bb_pct_b']}, Z: {entry_candle['zscore']}")

        # Simulate trade
        result = simulate_trade(symbol, entry_time, entry_price, entry_signal)

        if result is None:
            print(f"  → Failed to fetch price data")
            entries_skipped += 1
            continue

        # Determine win/loss
        is_win = result['pnl_pct'] > 0
        win_loss = "WIN" if is_win else "LOSS"

        print(f"  → Exit: {result['exit_reason']} after {result['minutes_held']} min")
        print(f"     P&L: {result['pnl_pct']*100:+.2f}% ({win_loss})")
        print(f"     Max profit: {result['max_profit']*100:+.2f}%, Max DD: {result['max_drawdown']*100:+.2f}%")

        trades.append({
            'symbol': symbol,
            'actual_move_pct': move_pct,
            'actual_direction': actual_direction,
            'entry_signal': entry_signal,
            'entry_price': entry_price,
            'entry_time': entry_candle['time'],
            'result': result,
            'is_win': is_win
        })

        # Rate limiting
        import time
        time.sleep(0.3)

    # Calculate statistics
    print("\n" + "="*80)
    print("SIMULATION RESULTS")
    print("="*80)

    total_movers = len(movers)
    total_entries = len(trades)
    entries_skipped_count = entries_skipped

    wins = [t for t in trades if t['is_win']]
    losses = [t for t in trades if not t['is_win']]

    print(f"\nTotal movers analyzed: {total_movers}")
    print(f"Entry signals detected: {total_entries} ({total_entries/total_movers*100:.1f}%)")
    print(f"No signal (skipped): {entries_skipped_count} ({entries_skipped_count/total_movers*100:.1f}%)")

    print(f"\nWins: {len(wins)} ({len(wins)/total_entries*100:.1f}% win rate)")
    print(f"Losses: {len(losses)} ({len(losses)/total_entries*100:.1f}%)")

    # Exit reasons breakdown
    exit_reasons = {}
    for trade in trades:
        reason = trade['result']['exit_reason']
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    print(f"\nExit Reasons:")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count} ({count/total_entries*100:.1f}%)")

    # P&L calculation (with 20x leverage)
    leverage = 20
    position_size_per_trade = 1  # $1 margin per trade
    total_pnl = 0
    fee_rate = 0.0004  # 0.04% taker fee per side

    for trade in trades:
        pnl_pct = trade['result']['pnl_pct']
        entry_value = position_size_per_trade * leverage
        exit_value = entry_value * (1 + pnl_pct)

        # Calculate fees
        entry_fee = entry_value * fee_rate
        exit_fee = exit_value * fee_rate
        total_fee = entry_fee + exit_fee

        # Net P&L
        gross_pnl = entry_value * pnl_pct
        net_pnl = gross_pnl - total_fee

        total_pnl += net_pnl

    print(f"\nP&L CALCULATION (20x leverage, $1 margin per trade):")
    print(f"  Gross P&L: ${sum(t['result']['pnl_pct'] * leverage for t in trades):.2f}")
    print(f"  Fees (0.08% per trade): ${sum(leverage * 0.0008 * 2 for t in trades):.2f}")
    print(f"  Net P&L: ${total_pnl:.2f}")
    print(f"  Capital deployed: ${total_entries} margin")
    print(f"  ROI on deployed: {total_pnl/total_entries*100:+.1f}%")
    print(f"  ROI on $100 capital: {total_pnl/100*100:+.1f}%")

    # Average hold time
    avg_hold = sum(t['result']['minutes_held'] for t in trades) / len(trades)
    print(f"\nAverage hold time: {avg_hold:.1f} minutes")

    # Save results
    output_file = analysis_dir / 'realistic_exit_simulation_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'parameters': {
                'stop_loss': STOP_LOSS,
                'take_profit_long': TAKE_PROFIT_LONG,
                'take_profit_short': TAKE_PROFIT_SHORT,
                'time_exit_profitable_min': 15,
                'time_exit_hard_cap_min': 30,
                'leverage': leverage
            },
            'summary': {
                'total_movers': total_movers,
                'entries': total_entries,
                'entries_skipped': entries_skipped_count,
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': len(wins)/total_entries*100 if total_entries > 0 else 0,
                'net_pnl': total_pnl,
                'roi_deployed_pct': total_pnl/total_entries*100 if total_entries > 0 else 0,
                'roi_total_pct': total_pnl,
                'avg_hold_minutes': avg_hold
            },
            'exit_reasons': exit_reasons,
            'trades': trades
        }, f, indent=2)

    print(f"\n✓ Results saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
