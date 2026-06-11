#!/usr/bin/env python3
"""
5 Simultaneous Positions Strategy

Strategy:
- Scan all pairs every cycle
- Find top 5 best signals
- Enter all 5 positions simultaneously
- Use 2-hour profit checks on each position
- This multiplies coverage by up to 5x
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
STOP_LOSS = None        # No SL
CHECK_INTERVAL_MIN = 120  # 2 hours
MAX_TIMEOUT_MIN = 240     # 4 hours
MAX_POSITIONS = 5         # 5 simultaneous positions
BASE_SIZE_USD = 1.0       # $1 per position


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

    # Return signal strength score for ranking
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

        # Check for TP hit
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

        # 2-hour profit check
        if i in checkpoints:
            if direction == 'LONG':
                current_pnl = (close - entry_price) / entry_price
            else:
                current_pnl = (entry_price - close) / entry_price

            if current_pnl <= 0:
                return f'CHECK_EXIT_{i}min', current_pnl, i

    # Max timeout
    final_idx = min(entry_idx + max_hold, len(klines) - 1)
    final_close = float(klines[final_idx][4])

    if direction == 'LONG':
        pnl = (final_close - entry_price) / entry_price
    else:
        pnl = (entry_price - final_close) / entry_price

    return 'MAX_TIMEOUT', pnl, max_hold


def main():
    """Main execution"""
    print("="*80)
    print("5 SIMULTANEOUS POSITIONS STRATEGY")
    print("="*80)
    print()

    print(f"Strategy Rules:")
    print(f"  Entry: {TRIGGER_PCT*100}% move in {LOOKBACK_MIN} min, vol >{VOL_MULT}x")
    print(f"  TP: {TP_LONG*100}% LONG, {TP_SHORT*100}% SHORT")
    print(f"  Check Interval: Every {CHECK_INTERVAL_MIN} min (2 hours)")
    print(f"  Max Positions: {MAX_POSITIONS} simultaneous")
    print(f"  Base Size: ${BASE_SIZE_USD} per position")
    print(f"  → Find top {MAX_POSITIONS} signals and enter all")
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

    # Scan all movers for entry signals
    print("Scanning all movers for entry signals...")
    current_time_ms = int(time.time() * 1000)

    signals = []

    for mover in movers:
        symbol = mover['symbol']

        # Fetch klines
        end_time = current_time_ms
        start_time = current_time_ms - (6 * 60 * 60 * 1000)
        klines = get_klines(symbol, start_time, end_time)

        if not klines or len(klines) < 30:
            continue

        # Find entry signal
        for idx in range(20, len(klines) - MAX_TIMEOUT_MIN):
            result = detect_move(klines, idx, TRIGGER_PCT, LOOKBACK_MIN, VOL_MULT)

            if result[0]:  # Has signal
                direction, detected_move, entry_price, score = result

                signals.append({
                    'symbol': symbol,
                    'actual_direction': mover['direction'],
                    'actual_move': abs(mover['price_change_pct']),
                    'entry_direction': direction,
                    'entry_price': entry_price,
                    'entry_idx': idx,
                    'detected_move': detected_move,
                    'score': score,
                    'klines': klines
                })
                break

        time.sleep(0.1)

    print(f"✓ Found {len(signals)} entry signals")
    print()

    if len(signals) == 0:
        print("No entry signals found")
        return

    # Sort by score and take top 5
    signals.sort(key=lambda x: x['score'], reverse=True)
    top_signals = signals[:MAX_POSITIONS]

    print(f"Top {len(top_signals)} signals selected:")
    for i, sig in enumerate(top_signals, 1):
        print(f"  {i}. {sig['symbol']} {sig['entry_direction']} | Score: {sig['score']:.2f} | "
              f"Move: {sig['detected_move']*100:+.1f}%")
    print()

    # Execute all positions
    print("="*80)
    print(f"EXECUTING {len(top_signals)} POSITIONS SIMULTANEOUSLY")
    print("="*80)

    trades = []

    for sig in top_signals:
        print(f"\n{sig['symbol']} {sig['entry_direction']} @ ${sig['entry_price']:.6f}")

        # Simulate trade
        tp = TP_LONG if sig['entry_direction'] == 'LONG' else TP_SHORT
        exit_reason, pnl, minutes = simulate_trade_with_two_hour_check(
            sig['klines'], sig['entry_idx'], sig['entry_price'],
            sig['entry_direction'], tp, STOP_LOSS
        )

        is_win = pnl > 0
        direction_match = (sig['entry_direction'] == sig['actual_direction'])

        print(f"  Exit: {exit_reason} after {minutes} min")
        print(f"  P&L: {pnl*100:+.2f}% ({'WIN' if is_win else 'LOSS'})")

        trades.append({
            'symbol': sig['symbol'],
            'actual_move': sig['actual_move'],
            'actual_direction': sig['actual_direction'],
            'entry_direction': sig['entry_direction'],
            'direction_match': direction_match,
            'exit_reason': exit_reason,
            'pnl_pct': pnl,
            'minutes_held': minutes,
            'is_win': is_win,
            'score': sig['score']
        })

    # Results
    print("\n" + "="*80)
    print("RESULTS - 5 SIMULTANEOUS POSITIONS")
    print("="*80)

    total_entries = len(trades)
    wins = sum(1 for t in trades if t['is_win'])
    tp_hits = sum(1 for t in trades if t['exit_reason'] == 'TP')
    check_exits = sum(1 for t in trades if 'CHECK_EXIT' in t['exit_reason'])

    print(f"\nTotal movers: {len(movers)}")
    print(f"Signals found: {len(signals)} ({len(signals)/len(movers)*100:.1f}%)")
    print(f"Positions taken: {total_entries} (top {MAX_POSITIONS})")
    print(f"Effective coverage: {total_entries} positions across {len(movers)} movers")
    print(f"\nWin rate: {wins}/{total_entries} ({wins/total_entries*100:.1f}%)")
    print(f"TP hit rate: {tp_hits}/{total_entries} ({tp_hits/total_entries*100:.1f}%)")
    print(f"2-hour exits: {check_exits}/{total_entries} ({check_exits/total_entries*100:.1f}%)")

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
    total_pnl = sum((t['pnl_pct'] * leverage * BASE_SIZE_USD) - (leverage * BASE_SIZE_USD * 0.0008) for t in trades)
    total_deployed = BASE_SIZE_USD * total_entries

    print(f"\nP&L (20x leverage, ${BASE_SIZE_USD} per position):")
    print(f"  Total Deployed: ${total_deployed:.2f}")
    print(f"  Net P&L: ${total_pnl:.2f}")
    print(f"  ROI on deployed: {total_pnl/total_deployed*100:+.1f}%")
    print(f"  ROI on $100 capital: {total_pnl:+.1f}%")

    avg_hold = sum(t['minutes_held'] for t in trades) / len(trades)
    print(f"\nAvg hold time: {avg_hold:.1f} min ({avg_hold/60:.1f}h)")

    # Save results
    analysis_dir = Path(__file__).parent
    output_file = analysis_dir / 'five_position_results.json'

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
            'results': {
                'total_movers': len(movers),
                'signals_found': len(signals),
                'positions_taken': total_entries,
                'win_rate': wins/total_entries*100,
                'tp_hit_rate': tp_hits/total_entries*100,
                'net_pnl': total_pnl,
                'total_deployed': total_deployed,
                'roi_pct': total_pnl/total_deployed*100,
                'avg_hold_min': avg_hold
            },
            'trades': trades
        }, f, indent=2)

    print(f"\n✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
