"""
Analyze last 30 trades with regime detection data
Shows: Regime, BTC Slope%, BTC ATR%, and outcome for each trade
"""
import re
from datetime import datetime

def parse_log_with_regime():
    """Extract trades with regime data from bot.log"""

    with open('bot.log', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    trades = []
    current_regime = None
    current_regime_time = None
    pending_entry = None

    for i, line in enumerate(lines):
        # Match regime detection lines
        regime_match = re.search(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] REGIME DETECTED: (\w+) - (\w+) \(ATR=([\d.]+)%, \|Slope\|=([\d.]+)%\)',
            line
        )
        if regime_match:
            timestamp_str, regime_type, regime_name, atr_pct, slope_pct = regime_match.groups()
            current_regime = {
                'time': timestamp_str,
                'type': regime_type,
                'name': regime_name,
                'atr_pct': float(atr_pct),
                'slope_pct': float(slope_pct)
            }
            current_regime_time = timestamp_str
            continue

        # Match entry lines
        entry_match = re.search(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] MARKET order filled: ([\w\d]+) (BUY|SELL) @ ([\d.]+) \| Executed qty=([\d.]+)',
            line
        )
        if entry_match:
            timestamp_str, symbol, side, price, qty = entry_match.groups()

            # Attach regime data to entry
            pending_entry = {
                'entry_time': timestamp_str,
                'symbol': symbol,
                'direction': 'LONG' if side == 'BUY' else 'SHORT',
                'entry_price': float(price),
                'quantity': float(qty),
                'regime': current_regime.copy() if current_regime else None
            }
            continue

        # Match exit lines (WIN or LOSS)
        exit_match = re.search(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] (WIN|LOSS): ([\w\d]+) (LONG|SHORT) @ ([\d.]+) \| PnL=\$(-?[\d.]+) \| Level=(\d+)',
            line
        )
        if exit_match:
            timestamp_str, outcome, symbol, direction, exit_price, pnl, level = exit_match.groups()

            # Match with pending entry
            if pending_entry and pending_entry['symbol'] == symbol and pending_entry['direction'] == direction:
                pending_entry.update({
                    'exit_time': timestamp_str,
                    'exit_price': float(exit_price),
                    'outcome': outcome,
                    'pnl': float(pnl),
                    'level': int(level)
                })
                # Wait for MAE before finalizing
            continue

        # Match MAE lines
        mae_match = re.search(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] MAE: (-?[\d.]+)% \(candle (\d+) of (\d+)\)',
            line
        )
        if mae_match:
            timestamp_str, mae_pct, mae_candle, total_candles = mae_match.groups()

            # Finalize trade
            if pending_entry and 'exit_time' in pending_entry:
                pending_entry['mae_pct'] = float(mae_pct)
                pending_entry['mae_candle'] = int(mae_candle)
                pending_entry['total_candles'] = int(total_candles)
                trades.append(pending_entry.copy())
                pending_entry = None

    return trades

def analyze_regime_accuracy(trades):
    """Analyze if regime detection predicted outcomes correctly"""

    if not trades:
        print("No trades found!")
        return

    # Get last 30 trades
    last_30 = trades[-30:] if len(trades) >= 30 else trades

    print("="*120)
    print("REGIME ANALYSIS: LAST 30 TRADES")
    print("="*120)
    print()
    print(f"Total trades in history: {len(trades)}")
    print(f"Analyzing: {len(last_30)} trades")
    print()

    # Statistics
    total_wins = 0
    total_losses = 0
    ranging_trades = 0
    trending_trades = 0
    longs_in_ranging = 0
    shorts_in_ranging = 0
    longs_in_trending = 0
    shorts_in_trending = 0

    # Detailed output
    print("="*120)
    print(f"{'#':<4} {'Symbol':<12} {'Dir':<6} {'Regime':<10} {'ATR%':<8} {'Slope%':<10} {'Outcome':<8} {'PnL':<10} {'MAE%':<8}")
    print("="*120)

    for i, trade in enumerate(reversed(last_30), 1):
        regime = trade.get('regime')

        if regime:
            regime_type = regime['type']
            atr_pct = regime['atr_pct']
            slope_pct = regime['slope_pct']
        else:
            regime_type = "UNKNOWN"
            atr_pct = 0.0
            slope_pct = 0.0

        direction = trade['direction']
        outcome = trade.get('outcome', 'OPEN')
        pnl = trade.get('pnl', 0.0)
        mae = trade.get('mae_pct', 0.0)

        # Count statistics
        if outcome == 'WIN':
            total_wins += 1
        elif outcome == 'LOSS':
            total_losses += 1

        if regime_type == 'RANGING':
            ranging_trades += 1
            if direction == 'LONG':
                longs_in_ranging += 1
            else:
                shorts_in_ranging += 1
        elif regime_type == 'TRENDING':
            trending_trades += 1
            if direction == 'LONG':
                longs_in_trending += 1
            else:
                shorts_in_trending += 1

        # Color coding for outcome
        outcome_display = outcome

        print(f"{len(last_30)-i+1:<4} {trade['symbol']:<12} {direction:<6} {regime_type:<10} "
              f"{atr_pct:<8.2f} {slope_pct:<10.4f} {outcome_display:<8} ${pnl:<9.2f} {mae:<8.2f}")

    print("="*120)
    print()

    # Summary statistics
    print("="*120)
    print("SUMMARY STATISTICS")
    print("="*120)
    print()

    total_trades = total_wins + total_losses
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    print(f"Win Rate: {total_wins}/{total_trades} = {win_rate:.1f}%")
    print()

    print(f"Regime Distribution:")
    print(f"  - RANGING trades: {ranging_trades} ({ranging_trades/len(last_30)*100:.1f}%)")
    print(f"  - TRENDING trades: {trending_trades} ({trending_trades/len(last_30)*100:.1f}%)")
    print()

    print(f"Direction in RANGING Market:")
    print(f"  - LONG trades: {longs_in_ranging}")
    print(f"  - SHORT trades: {shorts_in_ranging}")
    print()

    print(f"Direction in TRENDING Market:")
    print(f"  - LONG trades: {longs_in_trending}")
    print(f"  - SHORT trades: {shorts_in_trending}")
    print()

    # Key insights
    print("="*120)
    print("KEY INSIGHTS")
    print("="*120)
    print()

    if ranging_trades > trending_trades * 2:
        print("[!] CRITICAL: Bot is operating in RANGING market most of the time")
        print(f"    - {ranging_trades} RANGING vs {trending_trades} TRENDING")
        print(f"    - In ranging markets, LONG signals are penalized by 70%")
        print(f"    - This explains SHORT bias: {shorts_in_ranging} SHORTs vs {longs_in_ranging} LONGs in ranging")
        print()

    if win_rate < 35:
        print(f"[!] CRITICAL: Win rate is {win_rate:.1f}% (below 35%)")
        print()

        # Analyze if regime detection is causing issues
        avg_atr = sum(t.get('regime', {}).get('atr_pct', 0) for t in last_30) / len(last_30)
        avg_slope = sum(abs(t.get('regime', {}).get('slope_pct', 0)) for t in last_30) / len(last_30)

        print(f"Average market conditions during these trades:")
        print(f"  - Average ATR%: {avg_atr:.2f}% (threshold for TRENDING: 1.5%)")
        print(f"  - Average |Slope|%: {avg_slope:.4f}% (threshold for TRENDING: 0.3%)")
        print()

        if avg_atr < 1.5 and avg_slope < 0.3:
            print("[!] DIAGNOSIS: Market is genuinely RANGING (low volatility + flat slope)")
            print("    - But bot is still taking trades and losing")
            print("    - POSSIBLE ISSUE: Bot should be MORE SELECTIVE in ranging markets")
            print("    - Consider RAISING signal thresholds when market is ranging")
            print()
        else:
            print("[OK] Market has trending characteristics")
            print("    - Issue may be with trade execution, not regime detection")
            print()

    # Check if all trades are SHORTs
    all_shorts = all(t['direction'] == 'SHORT' for t in last_30)
    if all_shorts:
        print("[!] CRITICAL: ALL trades are SHORT positions")
        print("    - This confirms LONG signals are being completely blocked")
        print("    - Regime penalty (70% reduction) + trend filter is too aggressive")
        print("    - Consider adjusting penalty from 70% to 50% in ranging markets")
        print()

def main():
    print()
    print("Loading bot.log and extracting trades with regime data...")
    print()

    trades = parse_log_with_regime()
    analyze_regime_accuracy(trades)

    print()
    print("Analysis complete!")
    print()

if __name__ == "__main__":
    main()
