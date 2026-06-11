#!/usr/bin/env python3
"""
Analyze Entry Timing to 10% Move

For each mover:
1. Detect ALL possible entry signals from 6 precursor candles
2. Track time from each entry to when 10% TP would hit
3. Find optimal entry timing pattern
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Ideal settings - momentum strategy
RSI_UP = 65
RSI_DOWN = 30
BB_UP = 0.7
BB_DOWN = 0.25
Z_UP = 1.2
Z_DOWN = -1.2

BINANCE_BASE = "https://fapi.binance.com"


def check_momentum_signal(candle):
    """Check for momentum entry signal"""
    rsi = candle.get('rsi')
    bb = candle.get('bb_pct_b')
    z = candle.get('zscore')

    if rsi is None or bb is None or z is None:
        return None

    if rsi > RSI_UP and bb > BB_UP and z > Z_UP:
        return 'LONG'
    if rsi < RSI_DOWN and bb < BB_DOWN and z < Z_DOWN:
        return 'SHORT'
    return None


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


def find_tp_hit_time(klines, entry_price, direction, tp_pct):
    """
    Find when TP would hit

    Returns: (minutes_to_tp, tp_hit)
    """
    for i, kline in enumerate(klines):
        high = float(kline[2])
        low = float(kline[3])

        if direction == 'LONG':
            if (high - entry_price) / entry_price >= tp_pct:
                return i + 1, True  # TP hit
        else:  # SHORT
            if (entry_price - low) / entry_price >= tp_pct:
                return i + 1, True  # TP hit

    return len(klines), False  # TP never hit


def main():
    """Main execution"""
    print("="*80)
    print("ENTRY TIMING ANALYSIS")
    print("="*80)
    print()

    analysis_dir = Path(__file__).parent
    precursor_file = analysis_dir / '226_movers_precursors.json'

    with open(precursor_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    movers = data['movers']
    print(f"Analyzing {len(movers)} movers...\n")

    results = []
    tp_hit_times = []

    for i, mover in enumerate(movers, 1):
        symbol = mover['symbol']
        actual_direction = mover['move_metadata']['direction']
        move_pct = abs(mover['move_metadata']['move_pct'])
        precursors = mover['precursor_candles']

        print(f"[{i}/{len(movers)}] {symbol} ({move_pct:.1f}% {actual_direction})")

        # Check each precursor for entry signal
        entry_found = False
        best_entry = None

        for candle_idx, candle in enumerate(precursors):
            signal = check_momentum_signal(candle)
            if signal and signal == actual_direction:  # Correct direction only
                entry_time = candle['timestamp']
                entry_price = candle['close']
                candle_offset = candle['candle_offset']

                # Fetch klines from entry to 4 hours later
                end_time = entry_time + (4 * 60 * 60 * 1000)
                klines = get_klines(symbol, entry_time, end_time)

                if not klines:
                    continue

                # Find when 10% TP hits
                tp_pct = 0.10 if actual_direction == 'UP' else 0.08
                minutes_to_tp, tp_hit = find_tp_hit_time(klines, entry_price, actual_direction, tp_pct)

                if tp_hit:
                    print(f"  Candle {candle_offset}: Entry @ ${entry_price:.6f}")
                    print(f"    → TP hit after {minutes_to_tp} min ({minutes_to_tp/60:.1f}h)")

                    if not entry_found or minutes_to_tp < best_entry['minutes_to_tp']:
                        best_entry = {
                            'candle_offset': candle_offset,
                            'entry_price': entry_price,
                            'entry_time': candle['time'],
                            'minutes_to_tp': minutes_to_tp,
                            'tp_hit': True
                        }
                        entry_found = True

        if entry_found:
            print(f"  ✓ BEST: Candle {best_entry['candle_offset']}, TP in {best_entry['minutes_to_tp']} min")
            tp_hit_times.append(best_entry['minutes_to_tp'])

            results.append({
                'symbol': symbol,
                'move_pct': move_pct,
                'direction': actual_direction,
                'best_entry': best_entry
            })
        else:
            print(f"  ✗ No entry signal or TP never hit")

        print()

        import time
        time.sleep(0.2)

    # Analysis
    print("="*80)
    print("TIMING ANALYSIS SUMMARY")
    print("="*80)

    total_movers = len(movers)
    tp_hits = len(results)

    print(f"\nTotal movers: {total_movers}")
    print(f"TP hits with correct entry: {tp_hits} ({tp_hits/total_movers*100:.1f}%)")

    if tp_hit_times:
        tp_hit_times.sort()
        avg_time = sum(tp_hit_times) / len(tp_hit_times)
        median_time = tp_hit_times[len(tp_hit_times)//2]
        min_time = min(tp_hit_times)
        max_time = max(tp_hit_times)

        # Percentiles
        p25 = tp_hit_times[len(tp_hit_times)//4]
        p75 = tp_hit_times[(len(tp_hit_times)*3)//4]
        p90 = tp_hit_times[(len(tp_hit_times)*9)//10]

        print(f"\nTime to TP Hit:")
        print(f"  Average: {avg_time:.1f} min ({avg_time/60:.1f}h)")
        print(f"  Median: {median_time} min ({median_time/60:.1f}h)")
        print(f"  Min: {min_time} min ({min_time/60:.1f}h)")
        print(f"  Max: {max_time} min ({max_time/60:.1f}h)")
        print(f"\nPercentiles:")
        print(f"  25th: {p25} min ({p25/60:.1f}h)")
        print(f"  75th: {p75} min ({p75/60:.1f}h)")
        print(f"  90th: {p90} min ({p90/60:.1f}h)")

        # Recommended timeout for 90% catch rate
        print(f"\n💡 RECOMMENDED TIMEOUT: {p90} min ({p90/60:.1f}h)")
        print(f"   This will catch 90% of TP hits")

        # Analyze entry timing pattern (which candle offset works best)
        candle_offsets = {}
        for result in results:
            offset = result['best_entry']['candle_offset']
            candle_offsets[offset] = candle_offsets.get(offset, 0) + 1

        print(f"\nBest Entry Candle Distribution:")
        for offset in sorted(candle_offsets.keys()):
            count = candle_offsets[offset]
            print(f"  Candle {offset}: {count} times ({count/len(results)*100:.1f}%)")

        # Find optimal entry candle
        best_candle = max(candle_offsets.items(), key=lambda x: x[1])
        print(f"\n💡 OPTIMAL ENTRY TIMING: Candle {best_candle[0]}")
        print(f"   ({abs(best_candle[0]) * 5} min before move)")

    # Save
    output_file = analysis_dir / 'entry_timing_analysis.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_movers': total_movers,
                'tp_hits': tp_hits,
                'tp_hit_rate': tp_hits/total_movers*100 if total_movers > 0 else 0,
                'avg_time_to_tp_min': avg_time if tp_hit_times else None,
                'median_time_to_tp_min': median_time if tp_hit_times else None,
                'p90_time_min': p90 if tp_hit_times else None,
                'recommended_timeout_min': p90 if tp_hit_times else None
            },
            'results': results
        }, f, indent=2)

    print(f"\n✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
