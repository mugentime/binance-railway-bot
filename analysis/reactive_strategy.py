#!/usr/bin/env python3
"""
REACTIVE Strategy - Detect Move STARTING, Enter Quickly

SIMPLE ENTRY SIGNALS:
1. Price moved 2-3% in last 5-10 minutes (momentum detected)
2. Volume spike >1.5x average (confirmation)
3. Enter SAME direction as detected move

EXIT:
- TP: 3% (realistic, achievable)
- SL: 2% (tight, we're riding momentum)
- Timeout: 30 min (move should continue or we exit)
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# SIMPLE ENTRY PARAMETERS
PRICE_MOVE_TRIGGER = 0.02  # 2% price move to trigger entry
LOOKBACK_MINUTES = 5       # Detect move in last 5 minutes
VOLUME_MULTIPLIER = 1.5    # Volume must be 1.5x average

# EXIT PARAMETERS
TAKE_PROFIT = 0.03   # 3% TP (lowered from 10%)
STOP_LOSS = 0.02     # 2% SL (tighter)
TIMEOUT_MINUTES = 30 # 30 min max hold

BINANCE_BASE = "https://fapi.binance.com"


def get_klines(symbol, start_time, end_time):
    """Fetch 1-min klines"""
    try:
        r = requests.get(
            f"{BINANCE_BASE}/fapi/v1/klines",
            params={
                "symbol": symbol,
                "interval": "1m",
                "startTime": start_time,
                "endTime": end_time,
                "limit": 1500
            },
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return None


def detect_move_starting(klines, current_idx):
    """
    Detect if a move is STARTING right now

    Check last LOOKBACK_MINUTES candles:
    1. Did price move ≥2% in that period?
    2. Is volume elevated (>1.5x average)?

    Returns: ('LONG'/'SHORT'/None, move_pct, entry_price)
    """
    if current_idx < 20:  # Need history for volume average
        return None, 0, 0

    # Get lookback window
    lookback_start = max(0, current_idx - LOOKBACK_MINUTES)
    lookback_candles = klines[lookback_start:current_idx + 1]

    if len(lookback_candles) < 2:
        return None, 0, 0

    # Calculate price move in lookback period
    start_price = float(lookback_candles[0][1])  # Open of first candle
    current_price = float(lookback_candles[-1][4])  # Close of current candle

    price_change = (current_price - start_price) / start_price

    # Check if move is significant enough
    if abs(price_change) < PRICE_MOVE_TRIGGER:
        return None, 0, 0

    # Check volume confirmation
    current_volume = float(klines[current_idx][5])
    avg_volume = sum(float(k[5]) for k in klines[max(0, current_idx-20):current_idx]) / min(20, current_idx)

    if avg_volume == 0 or current_volume < avg_volume * VOLUME_MULTIPLIER:
        return None, 0, 0

    # Move detected!
    direction = 'LONG' if price_change > 0 else 'SHORT'
    entry_price = current_price

    return direction, price_change, entry_price


def simulate_trade(klines, entry_idx, entry_price, direction):
    """
    Simulate trade after entry

    Returns: exit_reason, pnl_pct, minutes_held
    """
    max_hold = min(TIMEOUT_MINUTES, len(klines) - entry_idx - 1)

    for i in range(1, max_hold + 1):
        candle_idx = entry_idx + i
        if candle_idx >= len(klines):
            break

        high = float(klines[candle_idx][2])
        low = float(klines[candle_idx][3])
        close = float(klines[candle_idx][4])

        if direction == 'LONG':
            # Check TP
            if (high - entry_price) / entry_price >= TAKE_PROFIT:
                return 'TP', TAKE_PROFIT, i

            # Check SL
            if (entry_price - low) / entry_price >= STOP_LOSS:
                return 'SL', -STOP_LOSS, i

        else:  # SHORT
            # Check TP
            if (entry_price - low) / entry_price >= TAKE_PROFIT:
                return 'TP', TAKE_PROFIT, i

            # Check SL
            if (high - entry_price) / entry_price >= STOP_LOSS:
                return 'SL', -STOP_LOSS, i

    # Timeout
    final_idx = min(entry_idx + max_hold, len(klines) - 1)
    final_close = float(klines[final_idx][4])

    if direction == 'LONG':
        pnl = (final_close - entry_price) / entry_price
    else:
        pnl = (entry_price - final_close) / entry_price

    return 'TIMEOUT', pnl, max_hold


def main():
    """Main execution"""
    print("="*80)
    print("REACTIVE STRATEGY - Detect Move Starting, Enter Quickly")
    print("="*80)
    print(f"\nENTRY SIGNALS (Simple):")
    print(f"  1. Price moves ≥{PRICE_MOVE_TRIGGER*100}% in last {LOOKBACK_MINUTES} min")
    print(f"  2. Volume >{VOLUME_MULTIPLIER}x average")
    print(f"  → Enter SAME direction as detected move")
    print(f"\nEXIT:")
    print(f"  TP: {TAKE_PROFIT*100}%")
    print(f"  SL: {STOP_LOSS*100}%")
    print(f"  Timeout: {TIMEOUT_MINUTES} min")
    print()

    analysis_dir = Path(__file__).parent
    precursor_file = analysis_dir / '226_movers_precursors.json'

    with open(precursor_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    movers = data['movers']
    print(f"Analyzing {len(movers)} movers...\n")

    trades = []

    for i, mover in enumerate(movers, 1):
        symbol = mover['symbol']
        actual_direction = mover['move_metadata']['direction']
        move_pct = abs(mover['move_metadata']['move_pct'])
        move_time = mover['move_metadata']['timestamp']

        print(f"[{i}/{len(movers)}] {symbol} ({move_pct:.1f}% {actual_direction})")

        # Fetch klines covering the move
        start_time = move_time - (60 * 60 * 1000)  # 1 hour before
        end_time = move_time + (2 * 60 * 60 * 1000)  # 2 hours after

        klines = get_klines(symbol, start_time, end_time)

        if not klines or len(klines) < 30:
            print(f"  ✗ Insufficient data\n")
            continue

        # Scan for entry signal (detect move starting)
        entry_found = False

        for idx in range(20, len(klines) - TIMEOUT_MINUTES):
            direction, detected_move, entry_price = detect_move_starting(klines, idx)

            if direction:
                # Move detected! Enter trade
                candle_time = datetime.fromtimestamp(klines[idx][0] / 1000)

                # Check if direction matches actual move
                direction_match = (direction == actual_direction)

                # Simulate trade
                exit_reason, pnl, minutes = simulate_trade(klines, idx, entry_price, direction)

                is_win = pnl > 0

                print(f"  → ENTRY: {direction} at ${entry_price:.6f}")
                print(f"     Detected: {detected_move*100:+.1f}% move")
                print(f"     Direction: {'✓ CORRECT' if direction_match else '✗ WRONG'}")
                print(f"  → EXIT: {exit_reason} after {minutes} min")
                print(f"     P&L: {pnl*100:+.2f}% ({'WIN' if is_win else 'LOSS'})")

                trades.append({
                    'symbol': symbol,
                    'actual_move': move_pct,
                    'actual_direction': actual_direction,
                    'entry_direction': direction,
                    'direction_match': direction_match,
                    'detected_move_pct': detected_move * 100,
                    'entry_price': entry_price,
                    'exit_reason': exit_reason,
                    'pnl_pct': pnl,
                    'minutes_held': minutes,
                    'is_win': is_win
                })

                entry_found = True
                break  # Take first signal only

        if not entry_found:
            print(f"  ✗ No entry signal detected")

        print()

        import time
        time.sleep(0.2)

    # Results
    print("="*80)
    print("REACTIVE STRATEGY RESULTS")
    print("="*80)

    total_entries = len(trades)
    if total_entries == 0:
        print("\n✗ No trades executed")
        return

    wins = [t for t in trades if t['is_win']]
    direction_correct = [t for t in trades if t['direction_match']]

    print(f"\nTotal entries: {total_entries} out of {len(movers)} movers")
    print(f"Coverage: {total_entries/len(movers)*100:.1f}%")
    print(f"\nDirection accuracy: {len(direction_correct)}/{total_entries} ({len(direction_correct)/total_entries*100:.1f}%)")
    print(f"Win rate: {len(wins)}/{total_entries} ({len(wins)/total_entries*100:.1f}%)")

    # Exit breakdown
    exit_reasons = {}
    for t in trades:
        reason = t['exit_reason']
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    print(f"\nExit Reasons:")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count} ({count/total_entries*100:.1f}%)")

    # P&L
    leverage = 20
    total_pnl = 0

    for t in trades:
        gross_pnl = leverage * t['pnl_pct']
        fees = leverage * 0.0008  # 0.08% round trip
        total_pnl += (gross_pnl - fees)

    print(f"\nP&L (20x leverage, $1/trade):")
    print(f"  Gross P&L: ${sum(t['pnl_pct'] * leverage for t in trades):.2f}")
    print(f"  Fees: ${total_entries * leverage * 0.0008:.2f}")
    print(f"  Net P&L: ${total_pnl:.2f}")
    print(f"  ROI on ${total_entries} deployed: {total_pnl/total_entries*100:+.1f}%")
    print(f"  ROI on $100 capital: {total_pnl:+.1f}%")

    # Average hold time
    avg_hold = sum(t['minutes_held'] for t in trades) / len(trades)
    print(f"\nAverage hold time: {avg_hold:.1f} minutes")

    # Save
    output_file = analysis_dir / 'reactive_strategy_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'strategy': 'REACTIVE - detect move starting, enter quickly',
            'parameters': {
                'price_move_trigger': PRICE_MOVE_TRIGGER,
                'lookback_minutes': LOOKBACK_MINUTES,
                'volume_multiplier': VOLUME_MULTIPLIER,
                'take_profit': TAKE_PROFIT,
                'stop_loss': STOP_LOSS,
                'timeout_minutes': TIMEOUT_MINUTES
            },
            'summary': {
                'total_movers': len(movers),
                'entries': total_entries,
                'coverage': total_entries/len(movers)*100,
                'direction_accuracy': len(direction_correct)/total_entries*100 if total_entries > 0 else 0,
                'win_rate': len(wins)/total_entries*100 if total_entries > 0 else 0,
                'net_pnl': total_pnl,
                'roi_pct': total_pnl
            },
            'trades': trades
        }, f, indent=2)

    print(f"\n✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
