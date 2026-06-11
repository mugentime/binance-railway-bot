#!/usr/bin/env python3
"""
Multi-Day Martingale Chain Validation

Strategy:
- Use 2-hour entry criteria (proven to find signals)
- If position loses → increase size by 1.5x and re-enter
- Continue chain until TOTAL chain is profitable
- No time-based exits on chain - only profitability
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
MAX_TIMEOUT_MIN = 240
MARTINGALE_MULT = 1.5
MAX_CHAIN_LEVEL = 5
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
    """Calculate 24h price change"""
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
    movers = []
    for i, symbol in enumerate(symbols):
        if i % 50 == 0:
            print(f"    Scanning: {i}/{len(symbols)}...")
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

    current_vol = float(klines[idx][5])
    avg_vol = sum(float(k[5]) for k in klines[max(0, idx-20):idx]) / min(20, idx)

    if avg_vol == 0 or current_vol < avg_vol * vol_mult:
        return None, 0, 0

    direction = 'LONG' if price_change > 0 else 'SHORT'
    return direction, price_change, current_price


def simulate_position(klines, entry_idx, entry_price, direction, tp, max_hold):
    """Simulate a single position"""
    max_hold_candles = min(max_hold, len(klines) - entry_idx - 1)

    for i in range(1, max_hold_candles + 1):
        candle_idx = entry_idx + i
        if candle_idx >= len(klines):
            break

        high = float(klines[candle_idx][2])
        low = float(klines[candle_idx][3])

        if direction == 'LONG':
            if (high - entry_price) / entry_price >= tp:
                return 'TP', tp, i
        else:
            if (entry_price - low) / entry_price >= tp:
                return 'TP', tp, i

    # Timeout
    final_idx = min(entry_idx + max_hold_candles, len(klines) - 1)
    final_close = float(klines[final_idx][4])

    if direction == 'LONG':
        pnl = (final_close - entry_price) / entry_price
    else:
        pnl = (entry_price - final_close) / entry_price

    return 'TIMEOUT', pnl, max_hold_candles


def simulate_martingale_chain(klines, initial_entry_idx):
    """Simulate martingale chain until profitable"""

    # Get initial entry
    direction, detected_move, entry_price = detect_move(
        klines, initial_entry_idx, TRIGGER_PCT, LOOKBACK_MIN, VOL_MULT
    )

    if not direction:
        return None

    chain_trades = []
    current_level = 0
    current_idx = initial_entry_idx
    chain_pnl_usd = 0
    total_deployed = 0

    while current_level < MAX_CHAIN_LEVEL:
        if current_idx + MAX_TIMEOUT_MIN >= len(klines):
            break

        # Position size for this level
        position_size = BASE_SIZE_USD * (MARTINGALE_MULT ** current_level)

        # Entry price
        entry_price = float(klines[current_idx][4])

        # Simulate position
        tp = TP_LONG if direction == 'LONG' else TP_SHORT
        exit_reason, pnl_pct, minutes = simulate_position(
            klines, current_idx, entry_price, direction, tp, MAX_TIMEOUT_MIN
        )

        # Calculate P&L
        leverage = 20
        pnl_usd = (pnl_pct * leverage * position_size) - (leverage * position_size * 0.0008)

        chain_trades.append({
            'level': current_level,
            'size_usd': position_size,
            'direction': direction,
            'entry_price': entry_price,
            'exit_reason': exit_reason,
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'minutes': minutes
        })

        total_deployed += position_size
        chain_pnl_usd += pnl_usd
        current_idx += minutes + 5  # Move forward

        # Check if chain is profitable
        if chain_pnl_usd > 0:
            return {
                'chain_trades': chain_trades,
                'chain_pnl_usd': chain_pnl_usd,
                'total_deployed': total_deployed,
                'levels': current_level + 1,
                'outcome': 'WIN'
            }

        # Continue to next level if loss
        current_level += 1

    # Max level reached
    return {
        'chain_trades': chain_trades,
        'chain_pnl_usd': chain_pnl_usd,
        'total_deployed': total_deployed,
        'levels': current_level,
        'outcome': 'LOSS'
    }


def validate_period(movers, period_name):
    """Test martingale chains for a period"""
    print(f"\n  Testing martingale chains on {len(movers)} movers...")

    current_time_ms = int(time.time() * 1000)
    chains = []

    for i, mover in enumerate(movers[:50], 1):  # Test on first 50 movers
        if i % 10 == 0:
            print(f"    Progress: {i}/{min(50, len(movers))}...")

        symbol = mover['symbol']

        end_time = current_time_ms
        start_time = current_time_ms - (6 * 60 * 60 * 1000)
        klines = get_klines(symbol, start_time, end_time)

        if not klines or len(klines) < 30:
            continue

        # Find first entry and simulate chain
        for idx in range(20, len(klines) - (MAX_TIMEOUT_MIN * MAX_CHAIN_LEVEL)):
            chain = simulate_martingale_chain(klines, idx)

            if chain:
                chain['symbol'] = symbol
                chains.append(chain)
                break

        time.sleep(0.2)

    if not chains:
        return None

    # Calculate results
    total_chains = len(chains)
    winning_chains = sum(1 for c in chains if c['outcome'] == 'WIN')
    total_pnl = sum(c['chain_pnl_usd'] for c in chains)
    total_deployed = sum(c['total_deployed'] for c in chains)
    avg_levels = sum(c['levels'] for c in chains) / len(chains)

    return {
        'total_movers': len(movers),
        'chains_executed': total_chains,
        'winning_chains': winning_chains,
        'chain_win_rate': winning_chains / total_chains * 100,
        'avg_chain_levels': avg_levels,
        'total_pnl': total_pnl,
        'total_deployed': total_deployed,
        'roi_pct': (total_pnl / total_deployed * 100) if total_deployed > 0 else 0,
        'chains': chains
    }


def main():
    """Main execution"""
    print("="*80)
    print("MULTI-DAY MARTINGALE CHAIN VALIDATION")
    print("="*80)
    print()

    print(f"Strategy:")
    print(f"  Entry: {TRIGGER_PCT*100}% move in {LOOKBACK_MIN} min, vol >{VOL_MULT}x")
    print(f"  TP: {TP_LONG*100}% LONG, {TP_SHORT*100}% SHORT")
    print(f"  Martingale: {MARTINGALE_MULT}x multiplier")
    print(f"  Max Levels: {MAX_CHAIN_LEVEL}")
    print(f"  Continue chain until profitable")
    print()

    symbols = get_symbols()
    print(f"✓ Found {len(symbols)} symbols")
    print()

    current_time = int(time.time() * 1000)

    validation_periods = []
    for days_ago in [1, 2, 3, 5, 7]:
        period_timestamp = current_time - (days_ago * 24 * 60 * 60 * 1000)
        period_date = datetime.fromtimestamp(period_timestamp / 1000)
        validation_periods.append({
            'name': f"{days_ago} day(s) ago ({period_date.strftime('%Y-%m-%d')})",
            'timestamp': period_timestamp
        })

    print(f"Testing {len(validation_periods)} periods:")
    for p in validation_periods:
        print(f"  - {p['name']}")
    print()
    print("-"*80)

    all_results = []

    for period in validation_periods:
        print(f"\n{'='*80}")
        print(f"PERIOD: {period['name']}")
        print('='*80)

        movers = find_movers_for_period(symbols, period['timestamp'], 10.0)
        print(f"  ✓ Found {len(movers)} movers")

        if not movers:
            continue

        results = validate_period(movers, period['name'])

        if results:
            all_results.append({
                'period': period['name'],
                'results': results
            })

            print(f"\n  Results:")
            print(f"    Chains: {results['chains_executed']}")
            print(f"    Win rate: {results['chain_win_rate']:.1f}%")
            print(f"    Avg levels: {results['avg_chain_levels']:.1f}")
            print(f"    Total P&L: ${results['total_pnl']:.2f}")
            print(f"    ROI: {results['roi_pct']:+.1f}%")

    # Summary
    print("\n" + "="*80)
    print("MARTINGALE CHAIN SUMMARY")
    print("="*80)

    if not all_results:
        print("\n✗ No results")
        return

    print(f"\nTested {len(all_results)} periods:\n")
    print(f"{'Period':<30} {'Chains':>7} {'Win%':>7} {'Levels':>7} {'P&L':>10} {'ROI':>8}")
    print("-"*80)

    total_pnl = 0
    total_deployed = 0
    total_chains = 0
    total_wins = 0

    for result in all_results:
        r = result['results']
        total_pnl += r['total_pnl']
        total_deployed += r['total_deployed']
        total_chains += r['chains_executed']
        total_wins += r['winning_chains']

        print(f"{result['period']:<30} {r['chains_executed']:>7} {r['chain_win_rate']:>6.1f}% {r['avg_chain_levels']:>7.1f} ${r['total_pnl']:>8.2f} {r['roi_pct']:>7.1f}%")

    avg_win_rate = (total_wins / total_chains * 100) if total_chains > 0 else 0
    avg_roi = (total_pnl / total_deployed * 100) if total_deployed > 0 else 0

    print("-"*80)
    print(f"{'AVERAGE':<30} {total_chains/len(all_results):>7.1f} {avg_win_rate:>6.1f}% {'-':>7} ${total_pnl/len(all_results):>8.2f} {avg_roi:>7.1f}%")
    print()

    profitable = sum(1 for r in all_results if r['results']['total_pnl'] > 0)
    print(f"Consistency:")
    print(f"  Profitable periods: {profitable}/{len(all_results)} ({profitable/len(all_results)*100:.1f}%)")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  Avg P&L per period: ${total_pnl/len(all_results):.2f}")
    print()

    # Save
    analysis_dir = Path(__file__).parent
    output_file = analysis_dir / 'martingale_multi_day_results.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'strategy': {
                'martingale_mult': MARTINGALE_MULT,
                'max_chain_level': MAX_CHAIN_LEVEL,
                'base_size_usd': BASE_SIZE_USD
            },
            'aggregate': {
                'total_chains': total_chains,
                'total_pnl': total_pnl,
                'avg_pnl_per_period': total_pnl / len(all_results),
                'overall_win_rate': avg_win_rate,
                'profitable_periods': profitable
            },
            'results': all_results
        }, f, indent=2)

    print(f"✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
