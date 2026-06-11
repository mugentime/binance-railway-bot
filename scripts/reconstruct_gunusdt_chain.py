#!/usr/bin/env python3
"""Reconstruct the exact GUNUSDT martingale chain sequence."""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor
import pytz

def main():
    executor = OrderExecutor()
    try:
        # Get ALL GUNUSDT trades from June 4-10
        cst = pytz.timezone('US/Central')

        # Start from June 4, 2026
        june4_start = datetime(2026, 6, 4, 0, 0, 0, tzinfo=cst)
        start_time_ms = int(june4_start.timestamp() * 1000)

        params = {
            'symbol': 'GUNUSDT',
            'startTime': start_time_ms,
            'limit': 100
        }
        params = executor._sign_params(params)

        resp = executor.client.get(
            'https://fapi.binance.com/fapi/v1/userTrades',
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        trades = resp.json()

        print('='*100)
        print('GUNUSDT CHAIN RECONSTRUCTION - MARTINGALE LEVEL TRACKING')
        print('='*100)

        # Group trades by timestamp to identify multi-trade operations
        from collections import defaultdict
        trades_by_time = defaultdict(list)

        for trade in trades:
            timestamp = trade['time']
            trades_by_time[timestamp].append(trade)

        # Sort timestamps
        sorted_times = sorted(trades_by_time.keys())

        print(f'\nFound {len(trades)} total trades across {len(sorted_times)} distinct timestamps\n')

        # Track position state
        position_qty = 0.0
        entry_prices = []  # Track all entry prices for averaging
        entry_quantities = []  # Track quantities
        martingale_level = 0

        for i, timestamp in enumerate(sorted_times, 1):
            batch = trades_by_time[timestamp]
            time_cst = datetime.fromtimestamp(timestamp/1000, tz=pytz.UTC).astimezone(cst)

            # Analyze this batch
            total_buy = sum(float(t['qty']) for t in batch if t['side'] == 'BUY')
            total_sell = sum(float(t['qty']) for t in batch if t['side'] == 'SELL')
            total_pnl = sum(float(t['realizedPnl']) for t in batch)

            # Determine operation type
            if total_buy > 0 and total_sell == 0:
                op_type = "ENTRY"
                position_qty += total_buy

                # Calculate average entry price for this batch
                total_value = sum(float(t['price']) * float(t['qty']) for t in batch if t['side'] == 'BUY')
                avg_price = total_value / total_buy if total_buy > 0 else 0
                entry_prices.append(avg_price)
                entry_quantities.append(total_buy)

                print(f"{i:2}. {time_cst.strftime('%m-%d %H:%M:%S')} | ENTRY L{martingale_level} | "
                      f"Bought {total_buy:12,.1f} @ ${avg_price:.6f} | "
                      f"Position: {position_qty:12,.1f} | "
                      f"{len(batch)} fill(s)")

            elif total_sell > 0 and total_buy == 0:
                op_type = "EXIT"
                old_position_qty = position_qty
                position_qty -= total_sell

                # Calculate average exit price for this batch
                total_value = sum(float(t['price']) * float(t['qty']) for t in batch if t['side'] == 'SELL')
                avg_exit_price = total_value / total_sell if total_sell > 0 else 0

                # Determine if this was a win or loss
                outcome = "WIN" if total_pnl > 0 else "LOSS" if total_pnl < 0 else "BREAKEVEN"

                print(f"{i:2}. {time_cst.strftime('%m-%d %H:%M:%S')} | EXIT  L{martingale_level} | "
                      f"Sold {total_sell:12,.1f} @ ${avg_exit_price:.6f} | "
                      f"P&L: ${total_pnl:+8.2f} | {outcome} | "
                      f"{len(batch)} fill(s)")

                # After exit, check position state
                if abs(position_qty) < 0.01:  # Position fully closed
                    if outcome == "WIN":
                        # Win: reduce level by 1
                        if martingale_level > 0:
                            martingale_level -= 1
                            print(f"      >> Level reduced to {martingale_level}")
                    elif outcome == "LOSS":
                        # Loss: increment level (or reset if at max)
                        if martingale_level >= 10:  # MAX_LEVEL
                            print(f"      >> MAX LEVEL HIT! Resetting to 0")
                            martingale_level = 0
                        else:
                            martingale_level += 1
                            print(f"      >> Level increased to {martingale_level}")

                    # Clear entry tracking
                    entry_prices = []
                    entry_quantities = []
            else:
                op_type = "MIXED"
                print(f"{i:2}. {time_cst.strftime('%m-%d %H:%M:%S')} | MIXED | "
                      f"Buy: {total_buy:,.1f} Sell: {total_sell:,.1f} | "
                      f"P&L: ${total_pnl:+8.2f}")

        print('\n' + '='*100)
        print('CHAIN ANALYSIS COMPLETE')
        print('='*100)

    finally:
        executor.close()

if __name__ == '__main__':
    main()
