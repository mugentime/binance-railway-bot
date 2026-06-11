#!/usr/bin/env python3
"""
Direction Fix: Momentum Strategy Instead of Mean-Reversion

CURRENT (WRONG - Mean-reversion):
  Overbought (RSI>55, BB>0.6, Z>0.5) → SHORT (bet on reversal DOWN)
  Oversold (RSI<45, BB<0.3, Z<-0.5) → LONG (bet on reversal UP)

FIXED (Momentum-following):
  Overbought → LONG (ride momentum UP)
  Oversold → SHORT (ride momentum DOWN)
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
TIME_EXIT_HARD_CAP = 4 * 60 * 60 * 1000  # 4 hours (ms)

# Entry thresholds (same values, REVERSED logic)
RSI_MOMENTUM_UP = 65    # RSI > 55 → LONG (was SHORT)
RSI_MOMENTUM_DOWN = 30  # RSI < 45 → SHORT (was LONG)
BB_MOMENTUM_UP = 0.7    # BB > 0.6 → LONG (was SHORT)
BB_MOMENTUM_DOWN = 0.25  # BB < 0.3 → SHORT (was LONG)
Z_MOMENTUM_UP = 1.2     # Z > 0.5 → LONG (was SHORT)
Z_MOMENTUM_DOWN = -1.2  # Z < -0.5 → SHORT (was LONG)

BINANCE_BASE = "https://fapi.binance.com"


def get_klines(symbol, interval="1m", start_time=None, end_time=None, limit=1500):
    """Fetch klines from Binance"""
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
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


def check_entry_signal_MOMENTUM(candle):
    """
    MOMENTUM strategy - ride the trend instead of betting on reversal

    Returns: 'LONG' or 'SHORT' or None
    """
    rsi = candle.get('rsi')
    bb_pct_b = candle.get('bb_pct_b')
    zscore = candle.get('zscore')

    if rsi is None or bb_pct_b is None or zscore is None:
        return None

    # LONG signal - momentum UP (overbought = keep going up)
    if rsi > RSI_MOMENTUM_UP and bb_pct_b > BB_MOMENTUM_UP and zscore > Z_MOMENTUM_UP:
        return 'LONG'  # REVERSED from SHORT

    # SHORT signal - momentum DOWN (oversold = keep going down)
    if rsi < RSI_MOMENTUM_DOWN and bb_pct_b < BB_MOMENTUM_DOWN and zscore < Z_MOMENTUM_DOWN:
        return 'SHORT'  # REVERSED from LONG

    return None


def simulate_trade(symbol, entry_time, entry_price, direction, max_wait_ms):
    """Simulate trade with SL and TP"""
    end_time = entry_time + max_wait_ms
    klines = get_klines(symbol, "1m", entry_time, end_time, limit=1500)

    if not klines or len(klines) < 2:
        return None

    max_profit = 0
    max_drawdown = 0

    for i, kline in enumerate(klines):
        high = float(kline[2])
        low = float(kline[3])
        close = float(kline[4])
        minutes_held = i + 1

        if direction == 'LONG':
            profit_high = (high - entry_price) / entry_price
            profit_low = (low - entry_price) / entry_price
            profit_close = (close - entry_price) / entry_price

            # Check SL
            if profit_low <= -STOP_LOSS:
                return {
                    'exit_reason': 'SL',
                    'pnl_pct': -STOP_LOSS,
                    'minutes_held': minutes_held,
                    'max_profit': max_profit,
                    'max_drawdown': max_drawdown
                }

            # Check TP
            if profit_high >= TAKE_PROFIT_LONG:
                return {
                    'exit_reason': 'TP',
                    'pnl_pct': TAKE_PROFIT_LONG,
                    'minutes_held': minutes_held,
                    'max_profit': max(max_profit, profit_high),
                    'max_drawdown': max_drawdown
                }

            max_profit = max(max_profit, profit_high)
            max_drawdown = min(max_drawdown, profit_low)

        else:  # SHORT
            profit_high = (entry_price - high) / entry_price
            profit_low = (entry_price - low) / entry_price
            profit_close = (entry_price - close) / entry_price

            # Check SL
            if profit_high <= -STOP_LOSS:
                return {
                    'exit_reason': 'SL',
                    'pnl_pct': -STOP_LOSS,
                    'minutes_held': minutes_held,
                    'max_profit': max_profit,
                    'max_drawdown': max_drawdown
                }

            # Check TP
            if profit_low >= TAKE_PROFIT_SHORT:
                return {
                    'exit_reason': 'TP',
                    'pnl_pct': TAKE_PROFIT_SHORT,
                    'minutes_held': minutes_held,
                    'max_profit': max(max_profit, profit_low),
                    'max_drawdown': max_drawdown
                }

            max_profit = max(max_profit, profit_low)
            max_drawdown = min(max_drawdown, profit_high)

    # Time cap
    final_close = float(klines[-1][4])
    if direction == 'LONG':
        final_pnl = (final_close - entry_price) / entry_price
    else:
        final_pnl = (entry_price - final_close) / entry_price

    return {
        'exit_reason': 'TIME_CAP',
        'pnl_pct': final_pnl,
        'minutes_held': len(klines),
        'max_profit': max_profit,
        'max_drawdown': max_drawdown
    }


def main():
    """Main execution"""
    print("="*80)
    print("DIRECTION FIX: Momentum Strategy (Reversed Logic)")
    print("="*80)
    print("\nOLD LOGIC (Mean-reversion):")
    print("  Overbought → SHORT (bet on drop)")
    print("  Oversold → LONG (bet on rise)")
    print("\nNEW LOGIC (Momentum-following):")
    print("  Overbought → LONG (ride momentum UP)")
    print("  Oversold → SHORT (ride momentum DOWN)")
    print()

    # Load precursor data
    analysis_dir = Path(__file__).parent
    precursor_file = analysis_dir / '226_movers_precursors.json'

    with open(precursor_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    movers = data['movers']
    print(f"✓ Loaded {len(movers)} movers\n")

    trades = []
    entries_skipped = 0

    print("Simulating with MOMENTUM direction logic...")
    print("-"*80)

    for i, mover in enumerate(movers, 1):
        symbol = mover['symbol']
        move_pct = mover['move_metadata']['move_pct']
        actual_direction = mover['move_metadata']['direction']
        precursors = mover['precursor_candles']

        print(f"\n[{i}/{len(movers)}] {symbol} (actual: {move_pct:+.1f}% {actual_direction})")

        # Check for MOMENTUM entry signal
        entry_signal = None
        entry_candle = None

        for candle in precursors:
            signal = check_entry_signal_MOMENTUM(candle)
            if signal:
                entry_signal = signal
                entry_candle = candle
                break

        if not entry_signal:
            print(f"  → No entry signal")
            entries_skipped += 1
            continue

        entry_time = entry_candle['timestamp']
        entry_price = entry_candle['close']

        # Check direction alignment
        direction_match = (entry_signal == actual_direction)
        match_str = "✓ CORRECT" if direction_match else "✗ WRONG"

        print(f"  → Entry: {entry_signal} {match_str} (actual: {actual_direction})")
        print(f"     Price: ${entry_price:.6f}")

        # Simulate trade
        result = simulate_trade(symbol, entry_time, entry_price, entry_signal, TIME_EXIT_HARD_CAP)

        if result is None:
            print(f"  → Failed to fetch data")
            entries_skipped += 1
            continue

        is_win = result['pnl_pct'] > 0
        print(f"  → Exit: {result['exit_reason']} after {result['minutes_held']} min")
        print(f"     P&L: {result['pnl_pct']*100:+.2f}% ({'WIN' if is_win else 'LOSS'})")

        trades.append({
            'symbol': symbol,
            'actual_move_pct': move_pct,
            'actual_direction': actual_direction,
            'entry_signal': entry_signal,
            'direction_match': direction_match,
            'entry_price': entry_price,
            'result': result,
            'is_win': is_win
        })

        import time
        time.sleep(0.3)

    # Results
    print("\n" + "="*80)
    print("MOMENTUM STRATEGY RESULTS")
    print("="*80)

    total_entries = len(trades)
    wins = [t for t in trades if t['is_win']]
    losses = [t for t in trades if not t['is_win']]

    # Direction accuracy
    direction_correct = [t for t in trades if t['direction_match']]
    direction_accuracy = len(direction_correct) / total_entries * 100 if total_entries > 0 else 0

    print(f"\nTotal entries: {total_entries}")
    print(f"Direction accuracy: {len(direction_correct)}/{total_entries} ({direction_accuracy:.1f}%)")
    print(f"Win rate: {len(wins)}/{total_entries} ({len(wins)/total_entries*100:.1f}%)")

    # Exit breakdown
    exit_reasons = {}
    for trade in trades:
        reason = trade['result']['exit_reason']
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    print(f"\nExit Reasons:")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count} ({count/total_entries*100:.1f}%)")

    # P&L
    leverage = 20
    total_pnl = 0
    fee_rate = 0.0004

    for trade in trades:
        pnl_pct = trade['result']['pnl_pct']
        entry_value = leverage
        gross_pnl = entry_value * pnl_pct
        fees = entry_value * fee_rate * 2
        total_pnl += (gross_pnl - fees)

    print(f"\nP&L (20x leverage, $1/trade):")
    print(f"  Net P&L: ${total_pnl:.2f}")
    print(f"  ROI on ${total_entries} deployed: {total_pnl/total_entries*100:+.1f}%")
    print(f"  ROI on $100 capital: {total_pnl:+.1f}%")

    # TP hit rate
    tp_hits = [t for t in trades if t['result']['exit_reason'] == 'TP']
    print(f"\nTP Hit Rate: {len(tp_hits)}/{total_entries} ({len(tp_hits)/total_entries*100:.1f}%)")

    if tp_hits:
        avg_tp_time = sum(t['result']['minutes_held'] for t in tp_hits) / len(tp_hits)
        print(f"  Average TP time: {avg_tp_time:.1f} min ({avg_tp_time/60:.1f}h)")

    # Save
    output_file = analysis_dir / 'momentum_direction_fix_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'strategy': 'MOMENTUM (reversed from mean-reversion)',
            'direction_accuracy': direction_accuracy,
            'win_rate': len(wins)/total_entries*100 if total_entries > 0 else 0,
            'tp_hit_rate': len(tp_hits)/total_entries*100 if total_entries > 0 else 0,
            'net_pnl': total_pnl,
            'trades': trades
        }, f, indent=2)

    print(f"\n✓ Results saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
