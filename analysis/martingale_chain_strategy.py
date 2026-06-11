#!/usr/bin/env python3
"""
Martingale Chain Strategy Validation

Strategy:
- Enter position at base size
- If loss → increase size by 1.5x and enter new position
- Continue chain until TOTAL chain P&L is positive
- Then reset and start new chain
- No time-based exits, only profitability-based
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
TRIGGER_PCT = 0.02      # 2% move
LOOKBACK_MIN = 10       # 10 minutes
VOL_MULT = 1.2          # 1.2x volume
TP_LONG = 0.10          # 10%
TP_SHORT = 0.08         # 8%
STOP_LOSS = None        # No SL for martingale
MAX_HOLD_MIN = 240      # Max 4 hours per position
MARTINGALE_MULT = 1.5   # 1.5x size increase
MAX_CHAIN_LEVEL = 5     # Max 5 levels in chain
BASE_SIZE_USD = 1.0     # $1 base position


def get_24h_tickers():
    """Fetch all 24h ticker data"""
    try:
        r = requests.get(f"{BINANCE_BASE}/fapi/v1/ticker/24hr", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error fetching tickers: {e}")
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


def simulate_position(klines, entry_idx, entry_price, direction, tp, max_hold):
    """
    Simulate a single position in the chain
    Returns: (exit_reason, pnl_pct, minutes_held)
    """
    max_hold_candles = min(max_hold, len(klines) - entry_idx - 1)

    for i in range(1, max_hold_candles + 1):
        candle_idx = entry_idx + i
        if candle_idx >= len(klines):
            break

        high = float(klines[candle_idx][2])
        low = float(klines[candle_idx][3])

        # Check for TP hit
        if direction == 'LONG':
            if (high - entry_price) / entry_price >= tp:
                return 'TP', tp, i
        else:  # SHORT
            if (entry_price - low) / entry_price >= tp:
                return 'TP', tp, i

    # Timeout - close at market
    final_idx = min(entry_idx + max_hold_candles, len(klines) - 1)
    final_close = float(klines[final_idx][4])

    if direction == 'LONG':
        pnl = (final_close - entry_price) / entry_price
    else:
        pnl = (entry_price - final_close) / entry_price

    return 'TIMEOUT', pnl, max_hold_candles


def simulate_martingale_chain(symbol, klines, start_idx):
    """
    Simulate a complete martingale chain until profitable

    Returns: {
        'chain_trades': [...],
        'chain_pnl_pct': float,
        'chain_pnl_usd': float,
        'total_deployed': float,
        'levels': int,
        'total_minutes': int
    }
    """
    chain_trades = []
    current_level = 0
    current_size_usd = BASE_SIZE_USD
    total_deployed = 0
    chain_pnl_usd = 0
    current_idx = start_idx
    total_minutes = 0

    # Initial direction from first entry
    direction, detected_move, entry_price = detect_move(
        klines, current_idx, TRIGGER_PCT, LOOKBACK_MIN, VOL_MULT
    )

    if not direction:
        return None  # No entry signal

    initial_direction = direction

    while current_level < MAX_CHAIN_LEVEL:
        # Check if we have enough data left
        if current_idx + MAX_HOLD_MIN >= len(klines):
            break

        # Entry price
        entry_price = float(klines[current_idx][4])

        # Calculate position size for this level
        position_size = BASE_SIZE_USD * (MARTINGALE_MULT ** current_level)

        # Simulate position
        tp = TP_LONG if initial_direction == 'LONG' else TP_SHORT
        exit_reason, pnl_pct, minutes = simulate_position(
            klines, current_idx, entry_price, initial_direction, tp, MAX_HOLD_MIN
        )

        # Calculate P&L in USD
        leverage = 20
        pnl_usd = (pnl_pct * leverage * position_size) - (leverage * position_size * 0.0008)

        # Track trade
        chain_trades.append({
            'level': current_level,
            'size_usd': position_size,
            'direction': initial_direction,
            'entry_price': entry_price,
            'exit_reason': exit_reason,
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'minutes': minutes
        })

        total_deployed += position_size
        chain_pnl_usd += pnl_usd
        total_minutes += minutes
        current_idx += minutes + 5  # Move forward + 5 min cooldown

        # Check if chain is profitable
        if chain_pnl_usd > 0:
            # Chain completed successfully!
            return {
                'symbol': symbol,
                'chain_trades': chain_trades,
                'chain_pnl_usd': chain_pnl_usd,
                'total_deployed': total_deployed,
                'levels': current_level + 1,
                'total_minutes': total_minutes,
                'outcome': 'WIN'
            }

        # If we hit TP, we're profitable - shouldn't reach here
        if exit_reason == 'TP':
            return {
                'symbol': symbol,
                'chain_trades': chain_trades,
                'chain_pnl_usd': chain_pnl_usd,
                'total_deployed': total_deployed,
                'levels': current_level + 1,
                'total_minutes': total_minutes,
                'outcome': 'WIN'
            }

        # Loss - continue chain at next level
        current_level += 1

    # Max chain level reached without profit
    return {
        'symbol': symbol,
        'chain_trades': chain_trades,
        'chain_pnl_usd': chain_pnl_usd,
        'total_deployed': total_deployed,
        'levels': current_level,
        'total_minutes': total_minutes,
        'outcome': 'LOSS'
    }


def main():
    """Main execution"""
    print("="*80)
    print("MARTINGALE CHAIN STRATEGY VALIDATION")
    print("="*80)
    print()

    print(f"Strategy Rules:")
    print(f"  Entry: {TRIGGER_PCT*100}% move in {LOOKBACK_MIN} min, vol >{VOL_MULT}x")
    print(f"  TP: {TP_LONG*100}% LONG, {TP_SHORT*100}% SHORT")
    print(f"  Martingale Multiplier: {MARTINGALE_MULT}x")
    print(f"  Max Chain Level: {MAX_CHAIN_LEVEL}")
    print(f"  Base Size: ${BASE_SIZE_USD}")
    print(f"  Max Hold per Position: {MAX_HOLD_MIN} min")
    print(f"  → Continue chain until TOTAL chain is profitable")
    print()

    print("Fetching 24h ticker data...")
    tickers = get_24h_tickers()

    if not tickers:
        print("Failed to fetch ticker data")
        return

    # Filter for 10%+ movers
    movers = []
    for ticker in tickers:
        try:
            price_change = float(ticker['priceChangePercent'])
            if abs(price_change) >= 10.0:
                movers.append({
                    'symbol': ticker['symbol'],
                    'price_change_pct': price_change,
                    'direction': 'UP' if price_change > 0 else 'DOWN'
                })
        except:
            continue

    print(f"✓ Found {len(movers)} symbols with 10%+ moves")
    print()

    if len(movers) == 0:
        print("No 10%+ movers found")
        return

    # Test strategy
    print(f"Testing MARTINGALE CHAIN strategy:")
    print("-"*80)

    chains = []
    current_time_ms = int(time.time() * 1000)

    for i, mover in enumerate(movers, 1):
        symbol = mover['symbol']
        actual_direction = mover['direction']
        move_pct = abs(mover['price_change_pct'])

        print(f"\n[{i}/{len(movers)}] {symbol} ({move_pct:.1f}% {actual_direction})")

        # Fetch klines (last 6 hours)
        end_time = current_time_ms
        start_time = current_time_ms - (6 * 60 * 60 * 1000)

        klines = get_klines(symbol, start_time, end_time)

        if not klines or len(klines) < 30:
            print(f"  ✗ Insufficient data")
            continue

        # Find entry signal and simulate chain
        for idx in range(20, len(klines) - (MAX_HOLD_MIN * MAX_CHAIN_LEVEL)):
            chain = simulate_martingale_chain(symbol, klines, idx)

            if chain:
                print(f"  → Chain started with {chain['levels']} levels")
                for j, trade in enumerate(chain['chain_trades']):
                    print(f"     Level {trade['level']}: {trade['direction']} ${trade['size_usd']:.2f} @ ${trade['entry_price']:.6f} → "
                          f"{trade['exit_reason']} {trade['pnl_pct']*100:+.2f}% (${trade['pnl_usd']:+.2f})")

                print(f"  → Chain {chain['outcome']}: Total P&L ${chain['chain_pnl_usd']:+.2f} "
                      f"| Deployed: ${chain['total_deployed']:.2f} | Time: {chain['total_minutes']} min")

                chains.append(chain)
                break

        time.sleep(0.2)

    # Results
    print("\n" + "="*80)
    print("MARTINGALE CHAIN RESULTS")
    print("="*80)

    if not chains:
        print("\n✗ No chains executed")
        return

    total_chains = len(chains)
    winning_chains = sum(1 for c in chains if c['outcome'] == 'WIN')

    total_pnl = sum(c['chain_pnl_usd'] for c in chains)
    total_deployed = sum(c['total_deployed'] for c in chains)
    avg_levels = sum(c['levels'] for c in chains) / len(chains)
    avg_time = sum(c['total_minutes'] for c in chains) / len(chains)

    print(f"\nTotal movers: {len(movers)}")
    print(f"Chains executed: {total_chains} ({total_chains/len(movers)*100:.1f}% coverage)")
    print(f"\nChain win rate: {winning_chains}/{total_chains} ({winning_chains/total_chains*100:.1f}%)")
    print(f"Average chain levels: {avg_levels:.1f}")
    print(f"Average chain duration: {avg_time:.1f} min ({avg_time/60:.1f}h)")

    # Level distribution
    level_dist = {}
    for c in chains:
        level_dist[c['levels']] = level_dist.get(c['levels'], 0) + 1

    print(f"\nChain Level Distribution:")
    for level in sorted(level_dist.keys()):
        print(f"  {level} level(s): {level_dist[level]} chains ({level_dist[level]/total_chains*100:.1f}%)")

    # P&L
    print(f"\nP&L (20x leverage):")
    print(f"  Total Deployed: ${total_deployed:.2f}")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  ROI on deployed: {total_pnl/total_deployed*100:+.1f}%")
    print(f"  ROI on $100 capital: {total_pnl:+.1f}%")
    print(f"  Avg P&L per chain: ${total_pnl/total_chains:+.2f}")

    # Save results
    analysis_dir = Path(__file__).parent
    output_file = analysis_dir / 'martingale_chain_results.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'strategy': {
                'trigger_pct': TRIGGER_PCT,
                'lookback_min': LOOKBACK_MIN,
                'vol_mult': VOL_MULT,
                'tp_long': TP_LONG,
                'tp_short': TP_SHORT,
                'martingale_mult': MARTINGALE_MULT,
                'max_chain_level': MAX_CHAIN_LEVEL,
                'base_size_usd': BASE_SIZE_USD,
                'max_hold_min': MAX_HOLD_MIN
            },
            'results': {
                'total_movers': len(movers),
                'chains_executed': total_chains,
                'coverage': total_chains/len(movers)*100,
                'chain_win_rate': winning_chains/total_chains*100,
                'avg_chain_levels': avg_levels,
                'avg_chain_duration_min': avg_time,
                'total_pnl': total_pnl,
                'total_deployed': total_deployed,
                'roi_pct': total_pnl/total_deployed*100
            },
            'chains': chains
        }, f, indent=2)

    print(f"\n✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
