#!/usr/bin/env python3
"""
Martingale Chain Strategy - Current Movers
Test martingale chains on current 10%+ movers
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
MAX_TIMEOUT_MIN = 240
MARTINGALE_MULT = 1.5
MAX_CHAIN_LEVEL = 5
BASE_SIZE_USD = 1.0


def get_24h_ticker():
    """Get 24h ticker data for all symbols"""
    try:
        r = requests.get(f"{BINANCE_BASE}/fapi/v1/ticker/24hr", timeout=10)
        r.raise_for_status()
        return r.json()
    except:
        return []


def get_klines(symbol, lookback_hours=6):
    """Fetch recent klines"""
    try:
        end_time = int(time.time() * 1000)
        start_time = end_time - (lookback_hours * 60 * 60 * 1000)

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


def simulate_martingale_chain(klines, initial_signal):
    """Simulate martingale chain until profitable"""
    direction = initial_signal['direction']
    entry_idx = initial_signal['entry_idx']

    chain_trades = []
    current_level = 0
    current_idx = entry_idx
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
                'symbol': initial_signal['symbol'],
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
        'symbol': initial_signal['symbol'],
        'chain_trades': chain_trades,
        'chain_pnl_usd': chain_pnl_usd,
        'total_deployed': total_deployed,
        'levels': current_level,
        'outcome': 'LOSS'
    }


def main():
    """Main execution"""
    print("="*80)
    print("MARTINGALE CHAIN STRATEGY - CURRENT MOVERS")
    print("="*80)
    print()

    print(f"Strategy:")
    print(f"  Entry: {TRIGGER_PCT*100}% move in {LOOKBACK_MIN} min, vol >{VOL_MULT}x")
    print(f"  TP: {TP_LONG*100}% LONG, {TP_SHORT*100}% SHORT")
    print(f"  Martingale: {MARTINGALE_MULT}x multiplier")
    print(f"  Max Levels: {MAX_CHAIN_LEVEL}")
    print(f"  Base Size: ${BASE_SIZE_USD}")
    print()

    print("Fetching 24h ticker data...")
    ticker_data = get_24h_ticker()

    if not ticker_data:
        print("✗ Failed to fetch ticker data")
        return

    # Find 10%+ movers
    movers = []
    for ticker in ticker_data:
        if ticker['symbol'].endswith('USDT'):
            price_change_pct = float(ticker['priceChangePercent'])
            if abs(price_change_pct) >= 10.0:
                movers.append({
                    'symbol': ticker['symbol'],
                    'price_change_pct': abs(price_change_pct),
                    'direction': 'UP' if price_change_pct > 0 else 'DOWN'
                })

    print(f"✓ Found {len(movers)} symbols with 10%+ moves")
    print()

    if not movers:
        print("✗ No movers found")
        return

    # Scan all movers for entry signals
    print("Scanning all movers for entry signals...")
    signals = []

    for i, mover in enumerate(movers[:100], 1):
        if i % 20 == 0:
            print(f"  Progress: {i}/{min(100, len(movers))}...")

        symbol = mover['symbol']
        klines = get_klines(symbol, lookback_hours=6)

        if not klines or len(klines) < 30:
            continue

        # Find first entry signal
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
                    'klines': klines,
                    'actual_move': mover['price_change_pct'],
                    'actual_direction': mover['direction']
                })
                break

        time.sleep(0.1)

    if not signals:
        print("✗ No entry signals found")
        return

    print(f"✓ Found {len(signals)} entry signals")
    print()

    # Sort by score and test top 10 chains
    signals.sort(key=lambda x: x['score'], reverse=True)
    top_signals = signals[:10]

    print(f"Testing martingale chains on top {len(top_signals)} signals...")
    print()

    chains = []
    for sig in top_signals:
        chain = simulate_martingale_chain(sig['klines'], sig)
        if chain:
            chains.append(chain)

    # Calculate results
    if not chains:
        print("✗ No chains completed")
        return

    print("="*80)
    print("MARTINGALE CHAIN RESULTS")
    print("="*80)
    print()

    winning_chains = sum(1 for c in chains if c['outcome'] == 'WIN')
    total_pnl = sum(c['chain_pnl_usd'] for c in chains)
    total_deployed = sum(c['total_deployed'] for c in chains)
    avg_levels = sum(c['levels'] for c in chains) / len(chains)

    print(f"Total movers: {len(movers)}")
    print(f"Signals found: {len(signals)} ({len(signals)/len(movers)*100:.1f}%)")
    print(f"Chains executed: {len(chains)}")
    print()

    print(f"Chain Results:")
    print(f"  Winning chains: {winning_chains}/{len(chains)} ({winning_chains/len(chains)*100:.1f}%)")
    print(f"  Avg chain levels: {avg_levels:.2f}")
    print(f"  Total deployed: ${total_deployed:.2f}")
    print(f"  Net P&L: ${total_pnl:.2f}")
    print(f"  ROI: {(total_pnl/total_deployed*100):+.1f}%")
    print()

    # Show individual chains
    print("Individual Chains:")
    print("-"*80)
    for i, chain in enumerate(chains, 1):
        outcome_emoji = "✓" if chain['outcome'] == 'WIN' else "✗"
        print(f"{i}. {chain['symbol']} - {outcome_emoji} {chain['outcome']}")
        print(f"   Levels: {chain['levels']} | P&L: ${chain['chain_pnl_usd']:.2f} | Deployed: ${chain['total_deployed']:.2f}")
        for trade in chain['chain_trades']:
            print(f"   L{trade['level']}: ${trade['size_usd']:.2f} | {trade['exit_reason']} | {trade['pnl_pct']*100:+.2f}% | ${trade['pnl_usd']:+.2f}")
    print()

    # Save results
    analysis_dir = Path(__file__).parent
    output_file = analysis_dir / 'martingale_current_results.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'strategy': {
                'martingale_mult': MARTINGALE_MULT,
                'max_chain_level': MAX_CHAIN_LEVEL,
                'base_size_usd': BASE_SIZE_USD
            },
            'results': {
                'total_movers': len(movers),
                'signals_found': len(signals),
                'chains_executed': len(chains),
                'winning_chains': winning_chains,
                'win_rate': winning_chains / len(chains) * 100,
                'avg_levels': avg_levels,
                'total_deployed': total_deployed,
                'total_pnl': total_pnl,
                'roi_pct': (total_pnl / total_deployed * 100)
            },
            'chains': chains
        }, f, indent=2)

    print(f"✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
