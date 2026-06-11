"""
Fetch the most recent positions (last 7 days)
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
    """Reconstruct position history from individual trades"""
    print(f"\n{'='*80}")
    print(f"RECONSTRUCTING POSITION HISTORY")
    print(f"{'='*80}")

    trades_by_symbol = defaultdict(list)
    for trade in trades:
        symbol = trade["symbol"]
        trades_by_symbol[symbol].append(trade)

    for symbol in trades_by_symbol:
        trades_by_symbol[symbol].sort(key=lambda t: int(t["time"]))

    positions = []

    for symbol, symbol_trades in trades_by_symbol.items():
        position_amt = 0.0
        entry_trades = []
        entry_qty_total = 0.0
        entry_value_total = 0.0

        for trade in symbol_trades:
            side = trade["side"]
            qty = float(trade["qty"])
            price = float(trade["price"])
            trade_time = int(trade["time"])
            realized_pnl = float(trade.get("realizedPnl", 0))

            if side == "BUY":
                new_position_amt = position_amt + qty
            else:
                new_position_amt = position_amt - qty

            if abs(new_position_amt) > abs(position_amt):
                entry_trades.append(trade)
                entry_qty_total += qty
                entry_value_total += qty * price

            elif abs(new_position_amt) < abs(position_amt):
                if entry_qty_total > 0:
                    avg_entry_price = entry_value_total / entry_qty_total

                    if position_amt > 0:
                        direction = "LONG"
                    elif position_amt < 0:
                        direction = "SHORT"
                    else:
                        direction = "UNKNOWN"

                    exit_qty = qty
                    position_pnl = realized_pnl
                    outcome = "WIN" if position_pnl > 0 else "LOSS" if position_pnl < 0 else "BREAKEVEN"

                    if entry_trades:
                        entry_time = int(entry_trades[0]["time"])
                        exit_time = trade_time
                        duration_ms = exit_time - entry_time
                        duration_minutes = duration_ms / 1000 / 60
                    else:
                        entry_time = trade_time
                        duration_minutes = 0

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

                    if new_position_amt == 0:
                        entry_trades = []
                        entry_qty_total = 0.0
                        entry_value_total = 0.0
                    else:
                        exit_ratio = exit_qty / entry_qty_total
                        entry_qty_total -= exit_qty
                        entry_value_total -= exit_qty * avg_entry_price

            position_amt = new_position_amt

    print(f"\n{'='*80}")
    print(f"TOTAL POSITIONS RECONSTRUCTED: {len(positions)}")
    print(f"{'='*80}\n")

    return positions


def main():
    """Fetch last 7 days of positions"""
    print(f"\n{'='*80}")
    print(f"FETCHING LATEST POSITIONS (Last 7 Days)")
    print(f"{'='*80}\n")

    # Start from May 24, 2026
    START_YEAR = 2026
    START_MONTH = 5
    START_DAY = 24
    START_HOUR = 0
    START_MINUTE = 0

    start_time_ms = cst_to_utc_milliseconds(START_YEAR, START_MONTH, START_DAY, START_HOUR, START_MINUTE)

    print("Initializing Binance API client...")
    executor = OrderExecutor()

    try:
        trades = fetch_all_trades(executor, start_time_ms)

        if not trades:
            print("\nNo new trades found since May 24.")
            return

        positions = reconstruct_positions(trades)

        if not positions:
            print("\nNo positions could be reconstructed.")
            return

        # Show summary
        total_pnl = sum(p["pnl_usdt"] for p in positions)
        winning = [p for p in positions if p["outcome"] == "WIN"]
        losing = [p for p in positions if p["outcome"] == "LOSS"]

        print(f"\nQUICK SUMMARY:")
        print(f"Total Positions: {len(positions)}")
        print(f"Winning: {len(winning)} | Losing: {len(losing)}")
        print(f"Total P&L: ${total_pnl:.2f}")
        print(f"First: {positions[0]['entry_time_cst']}")
        print(f"Last: {positions[-1]['exit_time_cst']}")

        # Show recent losing positions
        print(f"\n{'='*120}")
        print(f"RECENT LOSING POSITIONS:")
        print(f"{'='*120}")

        recent_losing = [p for p in positions if p["outcome"] == "LOSS"]
        recent_losing.sort(key=lambda x: x["exit_time"], reverse=True)  # Most recent first

        if recent_losing:
            print(f"\nTotal Recent Losses: {len(recent_losing)} positions")
            print(f"Total Loss Amount: ${sum(p['pnl_usdt'] for p in recent_losing):.2f}\n")

            print(f"{'#':<4} {'Symbol':<15} {'Dir':<6} {'Entry Time':<22} {'Exit Time':<22} {'Dur(h)':<8} {'Loss $':<10}")
            print(f"{'-'*120}")

            for i, pos in enumerate(recent_losing[:50], 1):  # Show top 50
                duration_hrs = pos['duration_minutes'] / 60
                print(f"{i:<4} {pos['symbol']:<15} {pos['direction']:<6} {pos['entry_time_cst']:<22} {pos['exit_time_cst']:<22} {duration_hrs:<8.2f} ${pos['pnl_usdt']:<9.2f}")
        else:
            print("\nNo losing positions in this period!")

        # Export to file
        output_dir = os.path.join("docs", "trades_export")
        os.makedirs(output_dir, exist_ok=True)

        with open(os.path.join(output_dir, "latest_positions.json"), 'w') as f:
            json.dump(positions, f, indent=2)

        print(f"\n\nData exported to: docs/trades_export/latest_positions.json")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        executor.close()


if __name__ == "__main__":
    main()
