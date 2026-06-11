"""
Binance Position History Retrieval Script
Reconstructs position history (entry/exit records) from trade data
"""
import sys
import os
import json
import csv
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
import pytz

# Add src directory to path to import OrderExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor
import config


def cst_to_utc_milliseconds(year: int, month: int, day: int, hour: int, minute: int) -> int:
    """Convert CST datetime to UTC Unix milliseconds"""
    cst = pytz.timezone('US/Central')
    target_time_cst = cst.localize(datetime(year, month, day, hour, minute, 0))
    target_time_utc = target_time_cst.astimezone(pytz.UTC)
    start_time_ms = int(target_time_utc.timestamp() * 1000)

    print(f"\n{'='*80}")
    print(f"TIMESTAMP CONVERSION")
    print(f"{'='*80}")
    print(f"Input (CST):  {target_time_cst.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"UTC:          {target_time_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Unix (ms):    {start_time_ms}")
    print(f"{'='*80}\n")

    return start_time_ms


def ms_to_cst_string(timestamp_ms: int) -> str:
    """Convert Unix milliseconds to CST datetime string"""
    utc_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
    cst = pytz.timezone('US/Central')
    cst_time = utc_time.astimezone(cst)
    return cst_time.strftime('%Y-%m-%d %H:%M:%S CST')


def fetch_all_trades(executor: OrderExecutor, start_time_ms: int) -> List[Dict]:
    """Fetch all trades from Binance API with pagination"""
    all_trades = []
    current_start_time = start_time_ms
    batch_num = 1

    print(f"\n{'='*80}")
    print(f"FETCHING TRADES FROM BINANCE API")
    print(f"{'='*80}")

    while True:
        try:
            params = {
                "startTime": current_start_time,
                "limit": 1000
            }
            params = executor._sign_params(params)

            print(f"Batch {batch_num}: Fetching trades (startTime={current_start_time})...", end=" ")

            resp = executor.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/userTrades",
                params=params,
                headers=executor._headers()
            )

            resp.raise_for_status()
            trades = resp.json()

            if not trades:
                print("No more trades found.")
                break

            print(f"{len(trades)} trades retrieved")
            all_trades.extend(trades)

            if len(trades) < 1000:
                print(f"Last batch retrieved (< 1000 trades).")
                break

            current_start_time = trades[-1]["time"] + 1
            batch_num += 1
            time.sleep(0.1)

        except Exception as e:
            print(f"\nERROR fetching trades: {e}")
            import traceback
            traceback.print_exc()
            break

    print(f"\n{'='*80}")
    print(f"TOTAL TRADES RETRIEVED: {len(all_trades)}")
    print(f"{'='*80}\n")

    return all_trades


def reconstruct_positions(trades: List[Dict]) -> List[Dict]:
    """
    Reconstruct position history from individual trades

    Logic:
    - Group trades by symbol and process chronologically
    - Track running position (LONG/SHORT) and quantity
    - Match entry trades with exit trades
    - Calculate position-level metrics

    Returns:
        List of position dictionaries with entry/exit data
    """
    print(f"\n{'='*80}")
    print(f"RECONSTRUCTING POSITION HISTORY")
    print(f"{'='*80}")

    # Group trades by symbol
    trades_by_symbol = defaultdict(list)
    for trade in trades:
        symbol = trade["symbol"]
        trades_by_symbol[symbol].append(trade)

    # Sort trades within each symbol by time
    for symbol in trades_by_symbol:
        trades_by_symbol[symbol].sort(key=lambda t: int(t["time"]))

    positions = []

    for symbol, symbol_trades in trades_by_symbol.items():
        print(f"\nProcessing {symbol}: {len(symbol_trades)} trades")

        # Track current position state
        position_amt = 0.0  # Positive = LONG, Negative = SHORT, 0 = Flat
        entry_trades = []  # Trades that opened current position
        entry_qty_total = 0.0
        entry_value_total = 0.0

        for trade in symbol_trades:
            side = trade["side"]  # "BUY" or "SELL"
            qty = float(trade["qty"])
            price = float(trade["price"])
            trade_time = int(trade["time"])
            realized_pnl = float(trade.get("realizedPnl", 0))

            # Determine trade's effect on position
            if side == "BUY":
                new_position_amt = position_amt + qty
            else:  # SELL
                new_position_amt = position_amt - qty

            # Check if this is an entry or exit
            if abs(new_position_amt) > abs(position_amt):
                # ENTRY: Position size increased
                entry_trades.append(trade)
                entry_qty_total += qty
                entry_value_total += qty * price

            elif abs(new_position_amt) < abs(position_amt):
                # EXIT: Position size decreased (partial or full close)
                if entry_qty_total > 0:
                    # Calculate average entry price
                    avg_entry_price = entry_value_total / entry_qty_total

                    # Determine direction
                    if position_amt > 0:
                        direction = "LONG"
                    elif position_amt < 0:
                        direction = "SHORT"
                    else:
                        direction = "UNKNOWN"

                    # Calculate exit quantity
                    exit_qty = qty

                    # Calculate position P&L
                    # Note: realizedPnl from Binance already includes fees
                    position_pnl = realized_pnl

                    # Determine outcome
                    outcome = "WIN" if position_pnl > 0 else "LOSS" if position_pnl < 0 else "BREAKEVEN"

                    # Calculate duration
                    if entry_trades:
                        entry_time = int(entry_trades[0]["time"])
                        exit_time = trade_time
                        duration_ms = exit_time - entry_time
                        duration_minutes = duration_ms / 1000 / 60
                    else:
                        entry_time = trade_time
                        duration_minutes = 0

                    # Create position record
                    position = {
                        "symbol": symbol,
                        "direction": direction,
                        "entry_time": entry_time,
                        "entry_time_cst": ms_to_cst_string(entry_time),
                        "exit_time": trade_time,
                        "exit_time_cst": ms_to_cst_string(trade_time),
                        "entry_price": round(avg_entry_price, 8),
                        "exit_price": round(price, 8),
                        "quantity": round(exit_qty, 8),
                        "pnl_usdt": round(position_pnl, 4),
                        "outcome": outcome,
                        "duration_minutes": round(duration_minutes, 2),
                        "entry_trade_ids": [t["id"] for t in entry_trades],
                        "exit_trade_id": trade["id"]
                    }

                    positions.append(position)

                    # If position fully closed, reset tracking
                    if new_position_amt == 0:
                        entry_trades = []
                        entry_qty_total = 0.0
                        entry_value_total = 0.0
                    else:
                        # Partial exit - reduce entry tracking proportionally
                        exit_ratio = exit_qty / entry_qty_total
                        entry_qty_total -= exit_qty
                        entry_value_total -= exit_qty * avg_entry_price

            # Update position amount
            position_amt = new_position_amt

    print(f"\n{'='*80}")
    print(f"TOTAL POSITIONS RECONSTRUCTED: {len(positions)}")
    print(f"{'='*80}\n")

    return positions


def export_positions_to_csv(positions: List[Dict], output_path: str):
    """Export positions to CSV format"""
    print(f"Exporting to CSV: {output_path}...", end=" ")

    columns = [
        "entry_time_cst", "exit_time_cst", "symbol", "direction",
        "entry_price", "exit_price", "quantity", "pnl_usdt",
        "outcome", "duration_minutes"
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(positions)

    print("OK")


def export_positions_to_json(positions: List[Dict], output_path: str):
    """Export positions to JSON format"""
    print(f"Exporting to JSON: {output_path}...", end=" ")

    with open(output_path, 'w', encoding='utf-8') as jsonfile:
        json.dump(positions, jsonfile, indent=2, ensure_ascii=False)

    print("OK")


def generate_position_summary(positions: List[Dict], output_path: str, start_date_str: str):
    """Generate Markdown summary report for positions"""
    print(f"Generating Markdown summary: {output_path}...", end=" ")

    if not positions:
        with open(output_path, 'w', encoding='utf-8') as mdfile:
            mdfile.write(f"# Position Summary: {start_date_str}\n\n")
            mdfile.write("**No positions found in this period.**\n")
        print("OK")
        return

    # Calculate statistics
    total_positions = len(positions)
    winning_positions = [p for p in positions if p["outcome"] == "WIN"]
    losing_positions = [p for p in positions if p["outcome"] == "LOSS"]
    breakeven_positions = [p for p in positions if p["outcome"] == "BREAKEVEN"]

    win_rate = (len(winning_positions) / total_positions * 100) if total_positions > 0 else 0

    total_pnl = sum(p["pnl_usdt"] for p in positions)
    avg_win = sum(p["pnl_usdt"] for p in winning_positions) / len(winning_positions) if winning_positions else 0
    avg_loss = sum(p["pnl_usdt"] for p in losing_positions) / len(losing_positions) if losing_positions else 0
    avg_duration = sum(p["duration_minutes"] for p in positions) / total_positions if total_positions > 0 else 0

    # Symbol breakdown
    symbols = set(p["symbol"] for p in positions)
    symbol_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})

    for pos in positions:
        symbol = pos["symbol"]
        if pos["outcome"] == "WIN":
            symbol_stats[symbol]["wins"] += 1
        elif pos["outcome"] == "LOSS":
            symbol_stats[symbol]["losses"] += 1
        symbol_stats[symbol]["pnl"] += pos["pnl_usdt"]

    # Sort by P&L
    sorted_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)

    # Top positions
    sorted_by_pnl = sorted(positions, key=lambda p: p["pnl_usdt"], reverse=True)
    top_wins = sorted_by_pnl[:10]
    top_losses = sorted_by_pnl[-10:][::-1]

    # Long vs Short performance
    long_positions = [p for p in positions if p["direction"] == "LONG"]
    short_positions = [p for p in positions if p["direction"] == "SHORT"]

    long_pnl = sum(p["pnl_usdt"] for p in long_positions)
    short_pnl = sum(p["pnl_usdt"] for p in short_positions)

    # Write report
    with open(output_path, 'w', encoding='utf-8') as mdfile:
        mdfile.write(f"# Position Summary: {start_date_str}\n\n")

        mdfile.write("## Overview\n\n")
        mdfile.write(f"- **Total Positions:** {total_positions:,}\n")
        mdfile.write(f"- **Total P&L:** ${total_pnl:,.2f} USDT\n")
        mdfile.write(f"- **Symbols Traded:** {len(symbols)}\n")
        mdfile.write(f"- **Date Range:** {positions[0]['entry_time_cst']} to {positions[-1]['exit_time_cst']}\n\n")

        mdfile.write("## Performance\n\n")
        mdfile.write(f"- **Winning Positions:** {len(winning_positions)} ({win_rate:.1f}%)\n")
        mdfile.write(f"- **Losing Positions:** {len(losing_positions)} ({len(losing_positions)/total_positions*100:.1f}%)\n")
        mdfile.write(f"- **Breakeven Positions:** {len(breakeven_positions)} ({len(breakeven_positions)/total_positions*100:.1f}%)\n\n")

        mdfile.write(f"- **Average Win:** ${avg_win:.2f}\n")
        mdfile.write(f"- **Average Loss:** ${avg_loss:.2f}\n")
        mdfile.write(f"- **Average Duration:** {avg_duration:.1f} minutes\n\n")

        if avg_loss != 0:
            profit_factor = abs(avg_win / avg_loss)
            mdfile.write(f"- **Profit Factor (Avg Win/Avg Loss):** {profit_factor:.2f}x\n\n")

        mdfile.write("## Direction Performance\n\n")
        mdfile.write(f"- **LONG Positions:** {len(long_positions)} (P&L: ${long_pnl:,.2f})\n")
        mdfile.write(f"- **SHORT Positions:** {len(short_positions)} (P&L: ${short_pnl:,.2f})\n\n")

        mdfile.write("## Top 10 Best Positions\n\n")
        mdfile.write("| Entry Time (CST) | Exit Time (CST) | Symbol | Direction | Entry Price | Exit Price | P&L (USDT) |\n")
        mdfile.write("|------------------|-----------------|--------|-----------|-------------|------------|------------|\n")
        for pos in top_wins:
            mdfile.write(f"| {pos['entry_time_cst']} | {pos['exit_time_cst']} | {pos['symbol']} | "
                        f"{pos['direction']} | {pos['entry_price']:.6f} | {pos['exit_price']:.6f} | "
                        f"${pos['pnl_usdt']:.2f} |\n")
        mdfile.write("\n")

        mdfile.write("## Top 10 Worst Positions\n\n")
        mdfile.write("| Entry Time (CST) | Exit Time (CST) | Symbol | Direction | Entry Price | Exit Price | P&L (USDT) |\n")
        mdfile.write("|------------------|-----------------|--------|-----------|-------------|------------|------------|\n")
        for pos in top_losses:
            mdfile.write(f"| {pos['entry_time_cst']} | {pos['exit_time_cst']} | {pos['symbol']} | "
                        f"{pos['direction']} | {pos['entry_price']:.6f} | {pos['exit_price']:.6f} | "
                        f"${pos['pnl_usdt']:.2f} |\n")
        mdfile.write("\n")

        mdfile.write("## Symbol Breakdown\n\n")
        mdfile.write("| Symbol | Wins | Losses | Total P&L (USDT) | Win Rate |\n")
        mdfile.write("|--------|------|--------|------------------|----------|\n")
        for symbol, stats in sorted_symbols:
            total = stats["wins"] + stats["losses"]
            win_pct = (stats["wins"] / total * 100) if total > 0 else 0
            mdfile.write(f"| {symbol} | {stats['wins']} | {stats['losses']} | "
                        f"${stats['pnl']:.2f} | {win_pct:.1f}% |\n")
        mdfile.write("\n")

        mdfile.write("---\n\n")
        mdfile.write(f"*Report generated on {datetime.now(pytz.timezone('US/Central')).strftime('%Y-%m-%d %H:%M:%S CST')}*\n")

    print("OK")


def main():
    """Main execution function"""
    print(f"\n{'='*80}")
    print(f"BINANCE POSITION HISTORY RETRIEVAL")
    print(f"{'='*80}\n")

    # Define start time: May 4, 2026, 2:26 PM CST
    START_YEAR = 2026
    START_MONTH = 5
    START_DAY = 4
    START_HOUR = 14
    START_MINUTE = 26

    start_time_ms = cst_to_utc_milliseconds(START_YEAR, START_MONTH, START_DAY, START_HOUR, START_MINUTE)

    print("Initializing Binance API client...")
    executor = OrderExecutor()

    try:
        # Fetch all trades
        trades = fetch_all_trades(executor, start_time_ms)

        if not trades:
            print("\nWARNING: No trades found from the specified date.")
            return

        # Reconstruct positions from trades
        positions = reconstruct_positions(trades)

        if not positions:
            print("\nWARNING: No positions could be reconstructed from trades.")
            return

        # Create output directory
        output_dir = os.path.join("docs", "trades_export")
        os.makedirs(output_dir, exist_ok=True)

        # Generate file names
        date_str = f"{START_YEAR}-{START_MONTH:02d}-{START_DAY:02d}"
        csv_path = os.path.join(output_dir, f"positions_from_{date_str}.csv")
        json_path = os.path.join(output_dir, f"positions_from_{date_str}.json")
        md_path = os.path.join(output_dir, f"positions_from_{date_str}.md")

        # Export to files
        print(f"\n{'='*80}")
        print(f"EXPORTING POSITION DATA")
        print(f"{'='*80}")
        export_positions_to_csv(positions, csv_path)
        export_positions_to_json(positions, json_path)
        generate_position_summary(positions, md_path, f"{date_str} onwards")

        print(f"\n{'='*80}")
        print(f"EXPORT COMPLETE")
        print(f"{'='*80}")
        print(f"Files saved to: {output_dir}/")
        print(f"  - {os.path.basename(csv_path)}")
        print(f"  - {os.path.basename(json_path)}")
        print(f"  - {os.path.basename(md_path)}")
        print(f"{'='*80}\n")

        # Display summary
        total_pnl = sum(p["pnl_usdt"] for p in positions)
        win_rate = (len([p for p in positions if p["outcome"] == "WIN"]) / len(positions) * 100) if positions else 0
        symbols = set(p["symbol"] for p in positions)

        print(f"SUMMARY:")
        print(f"   Total Positions: {len(positions):,}")
        print(f"   Total P&L: ${total_pnl:,.2f} USDT")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Symbols: {len(symbols)}")
        print(f"   First Position: {positions[0]['entry_time_cst']}")
        print(f"   Last Position: {positions[-1]['exit_time_cst']}")
        print(f"\nOK - All exports successful!\n")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        executor.close()
        print("HTTP client closed.")


if __name__ == "__main__":
    main()
