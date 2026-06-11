#!/usr/bin/env python3
"""
Multi-Day Validation of Best Reactive Strategy

Test the optimized strategy across multiple different date periods
to ensure it's not overfitted and works consistently.
"""

import sys
import json
import requests
import time
from pathlib import Path
from datetime import datetime, timedelta

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BINANCE_BASE = "https://fapi.binance.com"

# BEST STRATEGY PARAMETERS (from optimization)
TRIGGER_PCT = 0.02      # 2% move
LOOKBACK_MIN = 10       # 10 minutes
VOL_MULT = 1.2          # 1.2x volume
TP_LONG = 0.10          # 10%
TP_SHORT = 0.08         # 8%
STOP_LOSS = None        # No SL
TIMEOUT_MIN = 240       # 4 hours


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
    except:
        return None


def get_24h_klines(symbol, timestamp):
    """Fetch klines for a specific 24h period"""
    try:
        end_time = timestamp
        start_time = timestamp - (24 * 60 * 60 * 1000)

        r = requests.get(
            f"{BINANCE_BASE}/fapi/v1/klines",
            params={
                "symbol": symbol,
                "interval": "1m",
                "startTime": start_time,
                "endTime": end_time,
                "limit": 1500  # 24h = 1440 candles
            },
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except:
        return None


def calculate_24h_move(klines):
    """Calculate 24h price change from klines"""
    if not klines or len(klines) < 2:
        return None

    start_price = float(klines[0][1])  # Open of first candle
    end_price = float(klines[-1][4])   # Close of last candle

    price_change_pct = ((end_price - start_price) / start_price) * 100

    return {
        'start_price': start_price,
        'end_price': end_price,
        'price_change_pct': price_change_pct,
        'direction': 'UP' if price_change_pct > 0 else 'DOWN'
    }


def get_symbols():
    """Get all USDT perpetual symbols"""
    try:
        r = requests.get(f"{BINANCE_BASE}/fapi/v1/exchangeInfo", timeout=10)
        r.raise_for_status()
        data = r.json()

        symbols = []
        for s in data['symbols']:
            if s['symbol'].endswith('USDT') and s['status'] == 'TRADING':
                symbols.append(s['symbol'])

        return symbols
    except:
        return []


def find_movers_for_period(symbols, timestamp, min_move_pct=10.0):
    """Find symbols that moved 10%+ in a specific 24h period"""
    print(f"  Scanning {len(symbols)} symbols for {min_move_pct}%+ moves...")

    movers = []

    for i, symbol in enumerate(symbols):
        if i % 50 == 0:
            print(f"    Progress: {i}/{len(symbols)}...")

        klines = get_24h_klines(symbol, timestamp)

        if not klines:
            continue

        move_data = calculate_24h_move(klines)

        if move_data and abs(move_data['price_change_pct']) >= min_move_pct:
            movers.append({
                'symbol': symbol,
                'move_pct': abs(move_data['price_change_pct']),
                'direction': move_data['direction'],
                'end_price': move_data['end_price']
            })

        time.sleep(0.1)  # Rate limiting

    return movers


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


def validate_strategy_for_period(movers, period_name):
    """Test strategy on movers from a specific period"""
    print(f"\n  Testing strategy on {len(movers)} movers from {period_name}...")

    trades = []

    for i, mover in enumerate(movers[:100], 1):  # Limit to 100 movers per period
        if i % 20 == 0:
            print(f"    Progress: {i}/{min(100, len(movers))}...")

        symbol = mover['symbol']
        actual_direction = mover['direction']
        move_pct = mover['move_pct']

        # Fetch klines (last 6 hours)
        current_time_ms = int(time.time() * 1000)
        end_time = current_time_ms
        start_time = current_time_ms - (6 * 60 * 60 * 1000)

        klines = get_klines(symbol, start_time, end_time)

        if not klines or len(klines) < 30:
            continue

        # Find entry signal
        entry_found = False

        for idx in range(20, len(klines) - TIMEOUT_MIN):
            direction, detected_move, entry_price = detect_move(
                klines, idx, TRIGGER_PCT, LOOKBACK_MIN, VOL_MULT
            )

            if direction:
                # Simulate trade
                tp = TP_LONG if direction == 'LONG' else TP_SHORT
                exit_reason, pnl, minutes = simulate_trade(
                    klines, idx, entry_price, direction, tp, STOP_LOSS, TIMEOUT_MIN
                )

                is_win = pnl > 0
                direction_match = (direction == actual_direction)

                trades.append({
                    'symbol': symbol,
                    'actual_move': move_pct,
                    'actual_direction': actual_direction,
                    'entry_direction': direction,
                    'direction_match': direction_match,
                    'exit_reason': exit_reason,
                    'pnl_pct': pnl,
                    'minutes_held': minutes,
                    'is_win': is_win
                })

                entry_found = True
                break

        time.sleep(0.2)

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
        'total_movers': len(movers),
        'entries': total_entries,
        'coverage': total_entries / min(100, len(movers)) * 100,
        'win_rate': wins / total_entries * 100,
        'tp_hit_rate': tp_hits / total_entries * 100,
        'direction_accuracy': direction_correct / total_entries * 100,
        'net_pnl': total_pnl,
        'roi_pct': total_pnl,
        'avg_hold_min': sum(t['minutes_held'] for t in trades) / len(trades),
        'trades': trades
    }


def main():
    """Main execution"""
    print("="*80)
    print("MULTI-DAY VALIDATION OF BEST REACTIVE STRATEGY")
    print("="*80)
    print()

    print(f"Strategy Parameters:")
    print(f"  Entry: {TRIGGER_PCT*100}% move in {LOOKBACK_MIN} min, vol >{VOL_MULT}x")
    print(f"  TP: {TP_LONG*100}% LONG, {TP_SHORT*100}% SHORT")
    print(f"  SL: {'None' if not STOP_LOSS else f'{STOP_LOSS*100}%'}")
    print(f"  Timeout: {TIMEOUT_MIN} min")
    print()

    # Get list of symbols
    print("Fetching symbol list...")
    symbols = get_symbols()
    print(f"✓ Found {len(symbols)} USDT perpetual symbols")
    print()

    # Define validation periods (last 7 days)
    current_time = int(time.time() * 1000)

    validation_periods = []
    for days_ago in [1, 2, 3, 5, 7]:
        period_timestamp = current_time - (days_ago * 24 * 60 * 60 * 1000)
        period_date = datetime.fromtimestamp(period_timestamp / 1000)
        validation_periods.append({
            'name': f"{days_ago} day(s) ago ({period_date.strftime('%Y-%m-%d')})",
            'timestamp': period_timestamp,
            'days_ago': days_ago
        })

    print(f"Testing across {len(validation_periods)} different periods:")
    for p in validation_periods:
        print(f"  - {p['name']}")
    print()
    print("-"*80)

    all_results = []

    for period in validation_periods:
        print(f"\n{'='*80}")
        print(f"PERIOD: {period['name']}")
        print('='*80)

        # Find movers for this period
        movers = find_movers_for_period(symbols, period['timestamp'], min_move_pct=10.0)

        print(f"  ✓ Found {len(movers)} symbols with 10%+ moves")

        if len(movers) == 0:
            print(f"  ✗ No movers found for this period")
            continue

        # Validate strategy
        results = validate_strategy_for_period(movers, period['name'])

        if results:
            all_results.append({
                'period': period['name'],
                'days_ago': period['days_ago'],
                'results': results
            })

            print(f"\n  Results for {period['name']}:")
            print(f"    Movers found: {results['total_movers']}")
            print(f"    Coverage: {results['coverage']:.1f}% ({results['entries']} entries)")
            print(f"    Win rate: {results['win_rate']:.1f}%")
            print(f"    TP hit rate: {results['tp_hit_rate']:.1f}%")
            print(f"    Direction accuracy: {results['direction_accuracy']:.1f}%")
            print(f"    Net P&L: ${results['net_pnl']:.2f}")
            print(f"    ROI: {results['roi_pct']:+.1f}%")
            print(f"    Avg hold: {results['avg_hold_min']:.1f} min")

    # Summary across all periods
    print("\n" + "="*80)
    print("SUMMARY ACROSS ALL VALIDATION PERIODS")
    print("="*80)

    if not all_results:
        print("\n✗ No results to analyze")
        return

    print(f"\nTested {len(all_results)} different periods:")
    print()
    print(f"{'Period':<30} {'Coverage':>10} {'Win%':>8} {'TP%':>7} {'P&L':>10} {'ROI':>8}")
    print("-"*80)

    total_trades = 0
    total_pnl = 0
    total_wins = 0
    total_tp_hits = 0

    for result in all_results:
        r = result['results']
        total_trades += r['entries']
        total_pnl += r['net_pnl']
        total_wins += int(r['entries'] * r['win_rate'] / 100)
        total_tp_hits += int(r['entries'] * r['tp_hit_rate'] / 100)

        print(f"{result['period']:<30} {r['coverage']:>9.1f}% {r['win_rate']:>7.1f}% {r['tp_hit_rate']:>6.1f}% ${r['net_pnl']:>8.2f} {r['roi_pct']:>7.1f}%")

    print("-"*80)
    print(f"{'AVERAGE':<30} {sum(r['results']['coverage'] for r in all_results)/len(all_results):>9.1f}% {total_wins/total_trades*100:>7.1f}% {total_tp_hits/total_trades*100:>6.1f}% ${total_pnl:>8.2f} {total_pnl:>7.1f}%")
    print()

    print(f"Aggregate Metrics:")
    print(f"  Total periods tested: {len(all_results)}")
    print(f"  Total trades: {total_trades}")
    print(f"  Overall win rate: {total_wins/total_trades*100:.1f}%")
    print(f"  Overall TP hit rate: {total_tp_hits/total_trades*100:.1f}%")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  Avg P&L per period: ${total_pnl/len(all_results):.2f}")
    print()

    # Consistency check
    profitable_periods = sum(1 for r in all_results if r['results']['net_pnl'] > 0)
    print(f"Consistency:")
    print(f"  Profitable periods: {profitable_periods}/{len(all_results)} ({profitable_periods/len(all_results)*100:.1f}%)")

    pnl_values = [r['results']['net_pnl'] for r in all_results]
    pnl_std = (sum((x - total_pnl/len(all_results))**2 for x in pnl_values) / len(pnl_values))**0.5
    print(f"  P&L std deviation: ${pnl_std:.2f}")
    print()

    # Save results
    analysis_dir = Path(__file__).parent
    output_file = analysis_dir / 'multi_day_validation_results.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'strategy': {
                'trigger_pct': TRIGGER_PCT,
                'lookback_min': LOOKBACK_MIN,
                'vol_mult': VOL_MULT,
                'tp_long': TP_LONG,
                'tp_short': TP_SHORT,
                'sl': STOP_LOSS,
                'timeout_min': TIMEOUT_MIN
            },
            'periods_tested': len(all_results),
            'aggregate_metrics': {
                'total_trades': total_trades,
                'total_pnl': total_pnl,
                'avg_pnl_per_period': total_pnl / len(all_results),
                'overall_win_rate': total_wins / total_trades * 100,
                'overall_tp_hit_rate': total_tp_hits / total_trades * 100,
                'profitable_periods': profitable_periods,
                'consistency_pct': profitable_periods / len(all_results) * 100,
                'pnl_std_deviation': pnl_std
            },
            'period_results': all_results
        }, f, indent=2)

    print(f"✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
