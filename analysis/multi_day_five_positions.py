#!/usr/bin/env python3
"""
Multi-Day Validation: 5 Simultaneous Positions Strategy

Test 5 positions + 2-hour checks across multiple periods
"""

import sys
import json
import requests
import time
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BINANCE_BASE = "https://fapi.binance.com"

# STRATEGY PARAMETERS
TRIGGER_PCT = 0.02
LOOKBACK_MIN = 10
VOL_MULT = 1.2
TP_LONG = 0.10
TP_SHORT = 0.08
STOP_LOSS = None
CHECK_INTERVAL_MIN = 120
MAX_TIMEOUT_MIN = 240
MAX_POSITIONS = 5
BASE_SIZE_USD = 1.0


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
                "limit": 1500
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

    start_price = float(klines[0][1])
    end_price = float(klines[-1][4])
    price_change_pct = ((end_price - start_price) / start_price) * 100

    return {
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
                'direction': move_data['direction']
            })

        time.sleep(0.1)

    return movers


def detect_move(klines, idx, trigger_pct, lookback_min, vol_mult):
    """Detect if move is starting"""
    if idx < 20:
        return None, 0, 0, 0

    lookback_start = max(0, idx - lookback_min)
    lookback_candles = klines[lookback_start:idx + 1]

    if len(lookback_candles) < 2:
        return None, 0, 0, 0

    start_price = float(lookback_candles[0][1])
    current_price = float(lookback_candles[-1][4])
    price_change = (current_price - start_price) / start_price

    if abs(price_change) < trigger_pct:
        return None, 0, 0, 0

    current_vol = float(klines[idx][5])
    avg_vol = sum(float(k[5]) for k in klines[max(0, idx-20):idx]) / min(20, idx)

    if avg_vol == 0 or current_vol < avg_vol * vol_mult:
        return None, 0, 0, 0

    direction = 'LONG' if price_change > 0 else 'SHORT'

    # Signal strength score
    volume_score = current_vol / avg_vol if avg_vol > 0 else 0
    momentum_score = abs(price_change) * 100
    signal_score = momentum_score + (volume_score * 10)

    return direction, price_change, current_price, signal_score


def simulate_trade_with_two_hour_check(klines, entry_idx, entry_price, direction, tp, sl):
    """Simulate trade with 2-hour profit checks"""
    max_hold = min(MAX_TIMEOUT_MIN, len(klines) - entry_idx - 1)
    checkpoints = [120, 240]

    for i in range(1, max_hold + 1):
        candle_idx = entry_idx + i
        if candle_idx >= len(klines):
            break

        high = float(klines[candle_idx][2])
        low = float(klines[candle_idx][3])
        close = float(klines[candle_idx][4])

        if direction == 'LONG':
            if (high - entry_price) / entry_price >= tp:
                return 'TP', tp, i
            if sl and (entry_price - low) / entry_price >= sl:
                return 'SL', -sl, i
        else:
            if (entry_price - low) / entry_price >= tp:
                return 'TP', tp, i
            if sl and (high - entry_price) / entry_price >= sl:
                return 'SL', -sl, i

        if i in checkpoints:
            if direction == 'LONG':
                current_pnl = (close - entry_price) / entry_price
            else:
                current_pnl = (entry_price - close) / entry_price

            if current_pnl <= 0:
                return f'CHECK_EXIT_{i}min', current_pnl, i

    final_idx = min(entry_idx + max_hold, len(klines) - 1)
    final_close = float(klines[final_idx][4])

    if direction == 'LONG':
        pnl = (final_close - entry_price) / entry_price
    else:
        pnl = (entry_price - final_close) / entry_price

    return 'MAX_TIMEOUT', pnl, max_hold


def validate_strategy_for_period(movers, period_name):
    """Test 5 positions strategy on movers from a specific period"""
    print(f"\n  Testing 5-position strategy on {len(movers)} movers from {period_name}...")

    current_time_ms = int(time.time() * 1000)

    # Scan all movers for signals
    signals = []

    for i, mover in enumerate(movers[:100], 1):
        if i % 20 == 0:
            print(f"    Scanning: {i}/{min(100, len(movers))}...")

        symbol = mover['symbol']

        end_time = current_time_ms
        start_time = current_time_ms - (6 * 60 * 60 * 1000)
        klines = get_klines(symbol, start_time, end_time)

        if not klines or len(klines) < 30:
            continue

        for idx in range(20, len(klines) - MAX_TIMEOUT_MIN):
            result = detect_move(klines, idx, TRIGGER_PCT, LOOKBACK_MIN, VOL_MULT)

            if result[0]:
                direction, detected_move, entry_price, score = result

                signals.append({
                    'symbol': symbol,
                    'direction': direction,
                    'entry_price': entry_price,
                    'entry_idx': idx,
                    'score': score,
                    'klines': klines
                })
                break

        time.sleep(0.2)

    if not signals:
        return None

    # Sort by score and take top 5
    signals.sort(key=lambda x: x['score'], reverse=True)
    top_signals = signals[:MAX_POSITIONS]

    print(f"    Found {len(signals)} signals, taking top {len(top_signals)}")

    # Execute positions
    trades = []

    for sig in top_signals:
        tp = TP_LONG if sig['direction'] == 'LONG' else TP_SHORT
        exit_reason, pnl, minutes = simulate_trade_with_two_hour_check(
            sig['klines'], sig['entry_idx'], sig['entry_price'],
            sig['direction'], tp, STOP_LOSS
        )

        is_win = pnl > 0

        trades.append({
            'symbol': sig['symbol'],
            'exit_reason': exit_reason,
            'pnl_pct': pnl,
            'minutes_held': minutes,
            'is_win': is_win
        })

    total_entries = len(trades)
    wins = sum(1 for t in trades if t['is_win'])
    tp_hits = sum(1 for t in trades if t['exit_reason'] == 'TP')

    leverage = 20
    total_pnl = sum((t['pnl_pct'] * leverage * BASE_SIZE_USD) - (leverage * BASE_SIZE_USD * 0.0008) for t in trades)
    total_deployed = BASE_SIZE_USD * total_entries

    return {
        'total_movers': len(movers),
        'signals_found': len(signals),
        'positions_taken': total_entries,
        'win_rate': wins / total_entries * 100,
        'tp_hit_rate': tp_hits / total_entries * 100,
        'net_pnl': total_pnl,
        'total_deployed': total_deployed,
        'roi_pct': (total_pnl / total_deployed * 100) if total_deployed > 0 else 0,
        'avg_hold_min': sum(t['minutes_held'] for t in trades) / len(trades),
        'trades': trades
    }


def main():
    """Main execution"""
    print("="*80)
    print("MULTI-DAY VALIDATION: 5 SIMULTANEOUS POSITIONS")
    print("="*80)
    print()

    print(f"Strategy Parameters:")
    print(f"  Entry: {TRIGGER_PCT*100}% move in {LOOKBACK_MIN} min, vol >{VOL_MULT}x")
    print(f"  TP: {TP_LONG*100}% LONG, {TP_SHORT*100}% SHORT")
    print(f"  Check Interval: Every {CHECK_INTERVAL_MIN} min (2 hours)")
    print(f"  Max Positions: {MAX_POSITIONS} simultaneous")
    print(f"  Position Size: ${BASE_SIZE_USD} each")
    print()

    print("Fetching symbol list...")
    symbols = get_symbols()
    print(f"✓ Found {len(symbols)} USDT perpetual symbols")
    print()

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

        movers = find_movers_for_period(symbols, period['timestamp'], min_move_pct=10.0)

        print(f"  ✓ Found {len(movers)} symbols with 10%+ moves")

        if len(movers) == 0:
            print(f"  ✗ No movers found for this period")
            continue

        results = validate_strategy_for_period(movers, period['name'])

        if results:
            all_results.append({
                'period': period['name'],
                'days_ago': period['days_ago'],
                'results': results
            })

            print(f"\n  Results for {period['name']}:")
            print(f"    Signals: {results['signals_found']}")
            print(f"    Positions: {results['positions_taken']}")
            print(f"    Win rate: {results['win_rate']:.1f}%")
            print(f"    TP hit rate: {results['tp_hit_rate']:.1f}%")
            print(f"    Net P&L: ${results['net_pnl']:.2f}")
            print(f"    ROI: {results['roi_pct']:+.1f}%")
            print(f"    Avg hold: {results['avg_hold_min']:.1f} min")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY - 5 POSITIONS ACROSS ALL PERIODS")
    print("="*80)

    if not all_results:
        print("\n✗ No results to analyze")
        return

    print(f"\nTested {len(all_results)} different periods:")
    print()
    print(f"{'Period':<30} {'Signals':>8} {'Pos':>5} {'Win%':>7} {'TP%':>6} {'P&L':>10} {'ROI':>8}")
    print("-"*80)

    total_pnl = 0
    total_deployed = 0
    total_positions = 0
    total_wins = 0

    for result in all_results:
        r = result['results']
        total_pnl += r['net_pnl']
        total_deployed += r['total_deployed']
        total_positions += r['positions_taken']
        total_wins += int(r['positions_taken'] * r['win_rate'] / 100)

        print(f"{result['period']:<30} {r['signals_found']:>8} {r['positions_taken']:>5} {r['win_rate']:>6.1f}% {r['tp_hit_rate']:>5.1f}% ${r['net_pnl']:>8.2f} {r['roi_pct']:>7.1f}%")

    avg_win_rate = (total_wins / total_positions * 100) if total_positions > 0 else 0
    avg_roi = (total_pnl / total_deployed * 100) if total_deployed > 0 else 0

    print("-"*80)
    print(f"{'AVERAGE':<30} {'-':>8} {total_positions/len(all_results):>5.1f} {avg_win_rate:>6.1f}% {'-':>6} ${total_pnl/len(all_results):>8.2f} {avg_roi:>7.1f}%")
    print()

    profitable_periods = sum(1 for r in all_results if r['results']['net_pnl'] > 0)
    print(f"Consistency:")
    print(f"  Profitable periods: {profitable_periods}/{len(all_results)} ({profitable_periods/len(all_results)*100:.1f}%)")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  Avg P&L per period: ${total_pnl/len(all_results):.2f}")
    print(f"  Total positions: {total_positions}")
    print(f"  Overall win rate: {avg_win_rate:.1f}%")
    print()

    # Save results
    analysis_dir = Path(__file__).parent
    output_file = analysis_dir / 'multi_day_five_positions_results.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'strategy': {
                'trigger_pct': TRIGGER_PCT,
                'lookback_min': LOOKBACK_MIN,
                'vol_mult': VOL_MULT,
                'tp_long': TP_LONG,
                'tp_short': TP_SHORT,
                'check_interval_min': CHECK_INTERVAL_MIN,
                'max_positions': MAX_POSITIONS,
                'base_size_usd': BASE_SIZE_USD
            },
            'periods_tested': len(all_results),
            'aggregate_metrics': {
                'total_positions': total_positions,
                'total_pnl': total_pnl,
                'total_deployed': total_deployed,
                'avg_pnl_per_period': total_pnl / len(all_results),
                'overall_win_rate': avg_win_rate,
                'overall_roi': avg_roi,
                'profitable_periods': profitable_periods,
                'consistency_pct': profitable_periods / len(all_results) * 100
            },
            'period_results': all_results
        }, f, indent=2)

    print(f"✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
