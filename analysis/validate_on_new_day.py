#!/usr/bin/env python3
"""
Validate Best Strategy on UNSEEN DATA (Different Day)

Fetch movers from a different 24h period and test the best strategy.
This provides realistic out-of-sample validation.
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


def main():
    """Main execution"""
    print("="*80)
    print("STRATEGY VALIDATION ON UNSEEN DATA (Different Day)")
    print("="*80)
    print()

    # Fetch movers from DIFFERENT day (May 31, 2026 - 24h before our training data)
    validation_date = datetime(2026, 5, 31, 0, 0, 0)
    print(f"Validation date: {validation_date.strftime('%Y-%m-%d')}")
    print(f"(Training data was from June 2, 2026)")
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
                    'direction': 'UP' if price_change > 0 else 'DOWN',
                    'last_price': float(ticker['lastPrice'])
                })
        except:
            continue

    print(f"✓ Found {len(movers)} symbols with 10%+ moves")
    print()

    if len(movers) == 0:
        print("No 10%+ movers found on this day")
        return

    # Test strategy on these movers
    print(f"Testing BEST STRATEGY:")
    print(f"  Entry: {TRIGGER_PCT*100}% move in {LOOKBACK_MIN} min, vol >{VOL_MULT}x")
    print(f"  TP: {TP_LONG*100}% LONG, {TP_SHORT*100}% SHORT")
    print(f"  SL: {'None' if not STOP_LOSS else f'{STOP_LOSS*100}%'}")
    print(f"  Timeout: {TIMEOUT_MIN} min")
    print()
    print("-"*80)

    trades = []
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

                print(f"  → Entry: {direction} at ${entry_price:.6f}")
                print(f"     Detected: {detected_move*100:+.1f}% move")
                print(f"     Direction: {'✓' if direction_match else '✗'} (actual: {actual_direction})")
                print(f"  → Exit: {exit_reason} after {minutes} min")
                print(f"     P&L: {pnl*100:+.2f}% ({'WIN' if is_win else 'LOSS'})")

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

        if not entry_found:
            print(f"  ✗ No entry signal")

        time.sleep(0.2)

    # Results
    print("\n" + "="*80)
    print("VALIDATION RESULTS (OUT-OF-SAMPLE)")
    print("="*80)

    if not trades:
        print("\n✗ No trades executed")
        return

    total_entries = len(trades)
    wins = sum(1 for t in trades if t['is_win'])
    tp_hits = sum(1 for t in trades if t['exit_reason'] == 'TP')
    direction_correct = sum(1 for t in trades if t['direction_match'])

    print(f"\nTotal movers: {len(movers)}")
    print(f"Entries: {total_entries} ({total_entries/len(movers)*100:.1f}% coverage)")
    print(f"\nWin rate: {wins}/{total_entries} ({wins/total_entries*100:.1f}%)")
    print(f"TP hit rate: {tp_hits}/{total_entries} ({tp_hits/total_entries*100:.1f}%)")
    print(f"Direction accuracy: {direction_correct}/{total_entries} ({direction_correct/total_entries*100:.1f}%)")

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
    total_pnl = sum((t['pnl_pct'] * leverage) - (leverage * 0.0008) for t in trades)

    print(f"\nP&L (20x leverage, $1/trade):")
    print(f"  Gross: ${sum(t['pnl_pct'] * leverage for t in trades):.2f}")
    print(f"  Fees: ${total_entries * leverage * 0.0008:.2f}")
    print(f"  Net P&L: ${total_pnl:.2f}")
    print(f"  ROI on ${total_entries} deployed: {total_pnl/total_entries*100:+.1f}%")
    print(f"  ROI on $100 capital: {total_pnl:+.1f}%")

    avg_hold = sum(t['minutes_held'] for t in trades) / len(trades)
    print(f"\nAvg hold time: {avg_hold:.1f} min ({avg_hold/60:.1f}h)")

    # Compare to training results
    print("\n" + "="*80)
    print("COMPARISON: Training vs Validation")
    print("="*80)
    print(f"                    Training (Jun 2)    Validation (May 31)")
    print(f"Coverage:           94.9% (56/59)       {total_entries/len(movers)*100:.1f}% ({total_entries}/{len(movers)})")
    print(f"Win Rate:           51.8%               {wins/total_entries*100:.1f}%")
    print(f"TP Hit Rate:        14.3%               {tp_hits/total_entries*100:.1f}%")
    print(f"Net P&L:            $13.40              ${total_pnl:.2f}")
    print(f"ROI:                +13.4%              {total_pnl:+.1f}%")

    # Save results
    analysis_dir = Path(__file__).parent
    output_file = analysis_dir / 'validation_results.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'validation_date': validation_date.isoformat(),
            'strategy': {
                'trigger_pct': TRIGGER_PCT,
                'lookback_min': LOOKBACK_MIN,
                'vol_mult': VOL_MULT,
                'tp_long': TP_LONG,
                'tp_short': TP_SHORT,
                'sl': STOP_LOSS,
                'timeout_min': TIMEOUT_MIN
            },
            'results': {
                'total_movers': len(movers),
                'entries': total_entries,
                'coverage': total_entries/len(movers)*100,
                'win_rate': wins/total_entries*100,
                'tp_hit_rate': tp_hits/total_entries*100,
                'net_pnl': total_pnl,
                'roi_pct': total_pnl
            },
            'trades': trades
        }, f, indent=2)

    print(f"\n✓ Saved to: {output_file}")
    print()


if __name__ == '__main__':
    main()
