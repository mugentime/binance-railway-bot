#!/usr/bin/env python3
"""
Optimize Reactive Strategy to Hit 50%+ Coverage with 10% TP

Test different combinations:
- Entry trigger: 1%, 1.5%, 2%, 2.5%, 3%
- Lookback: 3min, 5min, 10min
- Volume multiplier: 1.2x, 1.5x, 2x
- Stop loss: None, 1.5%, 2%, 3%
- Timeout: 1h, 2h, 4h

Goal: ≥50% coverage (30+ movers), 10% TP, positive P&L
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from itertools import product

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BINANCE_BASE = "https://fapi.binance.com"


def get_klines(symbol, start_time, end_time):
    """Fetch 1-min klines"""
    try:
        r = requests.get(
            f"{BINANCE_BASE}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1m", "startTime": start_time, "endTime": end_time, "limit": 1500},
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except:
        return None


def detect_move(klines, idx, trigger_pct, lookback_min, vol_mult):
    """Detect if move is starting"""
    if idx < 20:
        return None, 0, 0

    lookback_start = max(0, idx - lookback_min)
    lookback_candles = klines[lookback_start:idx + 1]

    if len(lookback_candles) < 2:
        return None, 0, 0

    start_price = float(lookback_candles[0][1])
    current_price = float(lookback_candles[-1][4])
    price_change = (current_price - start_price) / start_price

    if abs(price_change) < trigger_pct:
        return None, 0, 0

    # Volume check
    current_vol = float(klines[idx][5])
    avg_vol = sum(float(k[5]) for k in klines[max(0, idx-20):idx]) / min(20, idx)

    if avg_vol == 0 or current_vol < avg_vol * vol_mult:
        return None, 0, 0

    direction = 'LONG' if price_change > 0 else 'SHORT'
    return direction, price_change, current_price


def simulate_trade(klines, entry_idx, entry_price, direction, tp, sl, timeout_min):
    """Simulate trade"""
    max_hold = min(timeout_min, len(klines) - entry_idx - 1)

    for i in range(1, max_hold + 1):
        candle_idx = entry_idx + i
        if candle_idx >= len(klines):
            break

        high = float(klines[candle_idx][2])
        low = float(klines[candle_idx][3])

        if direction == 'LONG':
            if (high - entry_price) / entry_price >= tp:
                return 'TP', tp, i
            if sl and (entry_price - low) / entry_price >= sl:
                return 'SL', -sl, i
        else:  # SHORT
            if (entry_price - low) / entry_price >= tp:
                return 'TP', tp, i
            if sl and (high - entry_price) / entry_price >= sl:
                return 'SL', -sl, i

    # Timeout
    final_idx = min(entry_idx + max_hold, len(klines) - 1)
    final_close = float(klines[final_idx][4])

    if direction == 'LONG':
        pnl = (final_close - entry_price) / entry_price
    else:
        pnl = (entry_price - final_close) / entry_price

    return 'TIMEOUT', pnl, max_hold


def test_strategy(movers, trigger_pct, lookback_min, vol_mult, tp_long, tp_short, sl, timeout_min):
    """Test a strategy configuration"""
    trades = []

    for mover in movers:
        symbol = mover['symbol']
        actual_direction = mover['move_metadata']['direction']
        move_time = mover['move_metadata']['timestamp']

        start_time = move_time - (60 * 60 * 1000)
        end_time = move_time + (timeout_min * 60 * 1000 + 60 * 60 * 1000)

        klines = get_klines(symbol, start_time, end_time)
        if not klines or len(klines) < 30:
            continue

        # Find entry signal
        for idx in range(20, len(klines) - timeout_min):
            direction, detected_move, entry_price = detect_move(klines, idx, trigger_pct, lookback_min, vol_mult)

            if direction:
                tp = tp_long if direction == 'LONG' else tp_short
                exit_reason, pnl, minutes = simulate_trade(klines, idx, entry_price, direction, tp, sl, timeout_min)

                trades.append({
                    'symbol': symbol,
                    'direction': direction,
                    'actual_direction': actual_direction,
                    'direction_match': direction == actual_direction,
                    'exit_reason': exit_reason,
                    'pnl_pct': pnl,
                    'minutes_held': minutes,
                    'is_win': pnl > 0
                })
                break

    if not trades:
        return None

    # Calculate metrics
    total_entries = len(trades)
    wins = sum(1 for t in trades if t['is_win'])
    tp_hits = sum(1 for t in trades if t['exit_reason'] == 'TP')
    direction_correct = sum(1 for t in trades if t['direction_match'])

    leverage = 20
    total_pnl = sum((t['pnl_pct'] * leverage) - (leverage * 0.0008) for t in trades)

    return {
        'params': {
            'trigger_pct': trigger_pct,
            'lookback_min': lookback_min,
            'vol_mult': vol_mult,
            'tp_long': tp_long,
            'tp_short': tp_short,
            'sl': sl,
            'timeout_min': timeout_min
        },
        'metrics': {
            'coverage': total_entries / len(movers) * 100,
            'entries': total_entries,
            'win_rate': wins / total_entries * 100,
            'tp_hit_rate': tp_hits / total_entries * 100,
            'direction_accuracy': direction_correct / total_entries * 100,
            'net_pnl': total_pnl,
            'roi_pct': total_pnl,
            'avg_hold_min': sum(t['minutes_held'] for t in trades) / len(trades)
        },
        'trades': trades
    }


def main():
    """Main optimization loop"""
    print("="*80)
    print("REACTIVE STRATEGY OPTIMIZATION")
    print("="*80)
    print(f"Goal: ≥50% coverage, 10% TP, positive P&L\n")

    # Load movers
    analysis_dir = Path(__file__).parent
    with open(analysis_dir / '226_movers_precursors.json', 'r', encoding='utf-8') as f:
        movers = json.load(f)['movers']

    print(f"Testing on {len(movers)} movers...\n")

    # Parameter grid (FOCUSED TEST - 16 combinations)
    param_grid = {
        'trigger_pct': [0.015, 0.02, 0.025],
        'lookback_min': [5, 10],
        'vol_mult': [1.2, 1.5],
        'tp_long': [0.10],
        'tp_short': [0.08],
        'sl': [None, 0.02],
        'timeout_min': [120, 240]
    }

    # Generate all combinations
    keys = param_grid.keys()
    values = param_grid.values()
    combinations = [dict(zip(keys, v)) for v in product(*values)]

    print(f"Total combinations to test: {len(combinations)}\n")

    results = []
    best_result = None

    for i, params in enumerate(combinations, 1):
        print(f"[{i}/{len(combinations)}] Testing: trigger={params['trigger_pct']*100:.1f}%, "
              f"lookback={params['lookback_min']}min, vol={params['vol_mult']}x, "
              f"SL={params['sl']*100 if params['sl'] else 'None'}%, "
              f"timeout={params['timeout_min']}min", end="")

        result = test_strategy(movers, **params)

        if result:
            metrics = result['metrics']
            print(f" → Coverage: {metrics['coverage']:.1f}%, "
                  f"Win: {metrics['win_rate']:.1f}%, "
                  f"TP: {metrics['tp_hit_rate']:.1f}%, "
                  f"P&L: ${metrics['net_pnl']:.2f}")

            results.append(result)

            # Check if this meets our goal
            if (metrics['coverage'] >= 50 and
                metrics['net_pnl'] > 0 and
                metrics['tp_hit_rate'] > 10):

                if not best_result or metrics['net_pnl'] > best_result['metrics']['net_pnl']:
                    best_result = result
                    print(f"  ✓✓✓ NEW BEST! P&L: ${metrics['net_pnl']:.2f}")
        else:
            print(" → No trades")

    # Summary
    print("\n" + "="*80)
    print("OPTIMIZATION COMPLETE")
    print("="*80)

    if best_result:
        m = best_result['metrics']
        p = best_result['params']

        print(f"\n🎯 BEST STRATEGY FOUND:")
        print(f"\nParameters:")
        print(f"  Entry trigger: {p['trigger_pct']*100:.1f}% move")
        print(f"  Lookback: {p['lookback_min']} minutes")
        print(f"  Volume multiplier: {p['vol_mult']}x")
        print(f"  TP LONG: {p['tp_long']*100}%")
        print(f"  TP SHORT: {p['tp_short']*100}%")
        print(f"  Stop Loss: {p['sl']*100 if p['sl'] else 'None'}%")
        print(f"  Timeout: {p['timeout_min']} minutes")

        print(f"\nPerformance:")
        print(f"  Coverage: {m['entries']}/{len(movers)} ({m['coverage']:.1f}%)")
        print(f"  Win rate: {m['win_rate']:.1f}%")
        print(f"  TP hit rate: {m['tp_hit_rate']:.1f}%")
        print(f"  Direction accuracy: {m['direction_accuracy']:.1f}%")
        print(f"  Net P&L: ${m['net_pnl']:.2f}")
        print(f"  ROI: {m['roi_pct']:+.1f}%")
        print(f"  Avg hold: {m['avg_hold_min']:.1f} min")

        # Save best result
        output_file = analysis_dir / 'best_reactive_strategy.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(best_result, f, indent=2)

        print(f"\n✓ Saved best strategy to: {output_file}")
    else:
        print("\n✗ No strategy met the goals (≥50% coverage, positive P&L, >10% TP hits)")

    # Save all results
    all_results_file = analysis_dir / 'all_strategy_results.json'
    with open(all_results_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'total_tested': len(results),
            'results': sorted(results, key=lambda x: x['metrics']['net_pnl'], reverse=True)[:20]
        }, f, indent=2)

    print(f"✓ Saved top 20 strategies to: {all_results_file}")
    print()


if __name__ == '__main__':
    main()
