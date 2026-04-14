"""
Extract last 30 trades from bot.log
"""
import re
from datetime import datetime

def parse_log():
    # Read log file
    with open('bot.log', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    trades = []
    pending_entry = None
    pending_exit = None

    for line in lines:
        # Match entry lines
        entry_match = re.search(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] MARKET order filled: ([\w\d]+) (BUY|SELL) @ ([\d.]+) \| Executed qty=([\d.]+)',
            line
        )
        if entry_match:
            timestamp_str, symbol, side, price, qty = entry_match.groups()
            pending_entry = {
                'entry_time': timestamp_str,
                'symbol': symbol,
                'direction': 'LONG' if side == 'BUY' else 'SHORT',
                'entry_price': float(price),
                'quantity': float(qty),
                'mae_pct': 0.0,
                'mae_candle': 0,
                'total_candles': 0
            }
            continue

        # Match exit lines (WIN or LOSS)
        exit_match = re.search(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] (WIN|LOSS): ([\w\d]+) (LONG|SHORT) @ ([\d.]+) \| PnL=\$(-?[\d.]+) \| Level=(\d+)',
            line
        )
        if exit_match:
            timestamp_str, outcome, symbol, direction, exit_price, pnl, level = exit_match.groups()
            pending_exit = {
                'exit_time': timestamp_str,
                'exit_symbol': symbol,
                'exit_direction': direction,
                'exit_price': float(exit_price),
                'outcome': outcome,
                'pnl': float(pnl),
                'level': int(level)
            }

            # If we have a matching pending entry, combine them
            if pending_entry and pending_entry['symbol'] == symbol and pending_entry['direction'] == direction:
                pending_entry.update({
                    'exit_time': timestamp_str,
                    'exit_price': float(exit_price),
                    'outcome': outcome,
                    'pnl': float(pnl),
                    'level': int(level)
                })
                # Will wait for MAE line before adding to trades
            continue

        # Match MAE lines
        mae_match = re.search(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] MAE: (-?[\d.]+)% \(candle (\d+) of (\d+)\)',
            line
        )
        if mae_match:
            timestamp_str, mae_pct, mae_candle, total_candles = mae_match.groups()

            # Attach to pending entry if it has an exit
            if pending_entry and 'exit_time' in pending_entry:
                pending_entry['mae_pct'] = float(mae_pct)
                pending_entry['mae_candle'] = int(mae_candle)
                pending_entry['total_candles'] = int(total_candles)
                trades.append(pending_entry.copy())
                pending_entry = None
                pending_exit = None

    # Get last 30 trades
    last_30 = trades[-30:] if len(trades) >= 30 else trades

    return last_30, len(trades)

def main():
    last_30, total = parse_log()

    print(f"Total trades found: {total}")
    print(f"Extracting last: {len(last_30)}")

    # Generate markdown
    md_lines = ["# Last 30 Trades\n"]
    md_lines.append(f"**Total trades in history:** {total}\n")
    md_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    for i, trade in enumerate(reversed(last_30), 1):
        md_lines.append(f"## Trade #{len(last_30) - i + 1}\n")
        md_lines.append(f"- **Symbol:** {trade['symbol']}\n")
        md_lines.append(f"- **Direction:** {trade['direction']}\n")
        md_lines.append(f"- **Entry Time:** {trade['entry_time']}\n")
        md_lines.append(f"- **Entry Price:** {trade['entry_price']}\n")
        md_lines.append(f"- **Exit Time:** {trade.get('exit_time', 'N/A')}\n")
        md_lines.append(f"- **Exit Price:** {trade.get('exit_price', 'N/A')}\n")
        md_lines.append(f"- **Quantity:** {trade['quantity']}\n")
        md_lines.append(f"- **Outcome:** {trade.get('outcome', 'N/A')}\n")
        md_lines.append(f"- **PnL:** ${trade.get('pnl', 0):.2f}\n")
        md_lines.append(f"- **Level:** {trade.get('level', 'N/A')}\n")
        md_lines.append(f"- **MAE:** {trade.get('mae_pct', 0):.2f}%\n")
        md_lines.append(f"- **MAE Candle:** {trade.get('mae_candle', 0)} of {trade.get('total_candles', 0)}\n\n")

    # Write to file
    with open('docs/Last_30_Trades.md', 'w', encoding='utf-8') as f:
        f.writelines(md_lines)

    print(f"Created docs/Last_30_Trades.md")

if __name__ == "__main__":
    main()
