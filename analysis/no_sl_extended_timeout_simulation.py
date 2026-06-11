#!/usr/bin/env python3
"""
No Stop Loss + Extended Timeout Simulation

Removes SL and extends timeout to catch all TP hits.
Tests: How long does it take for trades to hit TP without SL?
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
NO_STOP_LOSS = True  # No SL!
TAKE_PROFIT_LONG = 0.10  # 10% for UP
TAKE_PROFIT_SHORT = 0.08  # 8% for DOWN
MAX_WAIT_TIME = 4 * 60 * 60 * 1000  # 4 hours max (ms)

# Entry thresholds (ideal settings)
RSI_SHORT = 55
RSI_LONG = 45
BB_SHORT = 0.6
BB_LONG = 0.3
Z_SHORT = 0.5
Z_LONG = -0.5

BINANCE_BASE = "https://fapi.binance.com"


def get_klines(symbol, interval="1m", start_time=None, end_time=None, limit=1500):
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


def simulate_trade_no_sl(symbol, entry_time, entry_price, direction, max_wait_ms):
    """
    Simulate trade WITHOUT stop loss, wait for TP

    Args:
        symbol: Trading symbol
        entry_time: Entry timestamp (ms)
        entry_price: Entry price
        direction: 'LONG' or 'SHORT'
        max_wait_ms: Maximum wait time (ms)

    Returns:
        Dict with exit details
    """
    # Fetch 1-min klines for extended period
    end_time = entry_time + max_wait_ms

    # Binance API limit is 1500 candles per request
    # For 4 hours = 240 candles, we're fine
    klines = get_klines(symbol, "1m", entry_time, end_time, limit=1500)

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

        minutes_held = (i + 1)

        # Calculate current profit
        if direction == 'LONG':
            profit_at_high = (high - entry_price) / entry_price
            profit_at_low = (low - entry_price) / entry_price
            profit_at_close = (close - entry_price) / entry_price

            # NO STOP LOSS CHECK!

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

        else:  # SHORT
            profit_at_high = (entry_price - high) / entry_price
            profit_at_low = (entry_price - low) / entry_price
            profit_at_close = (entry_price - close) / entry_price

            # NO STOP LOSS CHECK!

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

    # Max time reached without hitting TP
    final_close = float(klines[-1][4])
    if direction == 'LONG':
        final_pnl = (final_close - entry_price) / entry_price
    else:
        final_pnl = (entry_price - final_close) / entry_price

    return {
        'exit_reason': 'MAX_TIME_NO_TP',
        'exit_price': final_close,
        'pnl_pct': final_pnl,
        'minutes_held': minutes_held,
        'max_profit': max_profit,
        'max_drawdown': max_drawdown
    }


def main():
    """Main execution"""
    print("="*80)
    print("NO STOP LOSS + EXTENDED TIMEOUT SIMULATION")
    print("="*80)
    print(f"Parameters:")
    print(f"  Stop Loss: DISABLED")
    print(f"  TP LONG: {TAKE_PROFIT_LONG*100}%")
    print(f"  TP SHORT: {TAKE_PROFIT_SHORT*100}%")
    print(f"  Max wait: {MAX_WAIT_TIME / (60*60*1000):.0f} hours")
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

    print("Simulating trades WITHOUT stop loss, extended timeout...")
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

        # Simulate trade WITHOUT SL
        result = simulate_trade_no_sl(symbol, entry_time, entry_price, entry_signal, MAX_WAIT_TIME)

        if result is None:
            print(f"  → Failed to fetch price data")
            entries_skipped += 1
            continue

        # Determine win/loss
        is_win = result['pnl_pct'] > 0
        win_loss = "WIN" if is_win else "LOSS"

        hours = result['minutes_held'] / 60
        print(f"  → Exit: {result['exit_reason']} after {result['minutes_held']} min ({hours:.1f}h)")
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
    print("SIMULATION RESULTS (NO SL, EXTENDED TIMEOUT)")
    print("="*80)

    total_movers = len(movers)
    total_entries = len(trades)

    wins = [t for t in trades if t['is_win']]
    losses = [t for t in trades if not t['is_win']]

    print(f"\nTotal movers analyzed: {total_movers}")
    print(f"Entry signals detected: {total_entries} ({total_entries/total_movers*100:.1f}%)")
    print(f"No signal (skipped): {entries_skipped} ({entries_skipped/total_movers*100:.1f}%)")

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

    # TP trades - analyze hold time
    tp_trades = [t for t in trades if t['result']['exit_reason'] == 'TP']
    if tp_trades:
        avg_tp_time = sum(t['result']['minutes_held'] for t in tp_trades) / len(tp_trades)
        max_tp_time = max(t['result']['minutes_held'] for t in tp_trades)
        min_tp_time = min(t['result']['minutes_held'] for t in tp_trades)

        print(f"\nTP Hit Timing (for {len(tp_trades)} TP trades):")
        print(f"  Average: {avg_tp_time:.1f} min ({avg_tp_time/60:.1f}h)")
        print(f"  Minimum: {min_tp_time} min ({min_tp_time/60:.1f}h)")
        print(f"  Maximum: {max_tp_time} min ({max_tp_time/60:.1f}h)")

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
    if trades:
        avg_hold = sum(t['result']['minutes_held'] for t in trades) / len(trades)
        print(f"\nAverage hold time: {avg_hold:.1f} minutes ({avg_hold/60:.1f} hours)")

    # Save results
    output_file = analysis_dir / 'no_sl_extended_timeout_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'parameters': {
                'stop_loss': 'DISABLED',
                'take_profit_long': TAKE_PROFIT_LONG,
                'take_profit_short': TAKE_PROFIT_SHORT,
                'max_wait_hours': MAX_WAIT_TIME / (60*60*1000),
                'leverage': leverage
            },
            'summary': {
                'total_movers': total_movers,
                'entries': total_entries,
                'entries_skipped': entries_skipped,
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': len(wins)/total_entries*100 if total_entries > 0 else 0,
                'net_pnl': total_pnl,
                'roi_deployed_pct': total_pnl/total_entries*100 if total_entries > 0 else 0,
                'roi_total_pct': total_pnl,
                'avg_hold_minutes': avg_hold if trades else 0
            },
            'exit_reasons': exit_reasons,
            'trades': trades
        }, f, indent=2)

    print(f"\n✓ Results saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
