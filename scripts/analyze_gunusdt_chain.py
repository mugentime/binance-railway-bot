#!/usr/bin/env python3
"""Analyze the GUNUSDT losing chain to identify what went wrong."""

import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor
import pytz

def main():
    executor = OrderExecutor()
    try:
        # Get recent GUNUSDT trades
        cst = pytz.timezone('US/Central')

        # Get last 24 hours of trades
        now = datetime.now(cst)
        yesterday = now - timedelta(days=1)
        start_time_ms = int(yesterday.timestamp() * 1000)

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
        print('GUNUSDT CHAIN ANALYSIS - DETAILED TRADE BREAKDOWN')
        print('='*100)
        print(f'\nTotal GUNUSDT Trades: {len(trades)}')

        # Sort by time
        trades.sort(key=lambda x: x['time'])

        # Analyze each trade
        print('\n' + '='*100)
        print('DETAILED TRADE LOG:')
        print('='*100)
        print(f"{'#':<4} {'Time (CST)':<20} {'Side':<5} {'Price':<12} {'Qty':<15} {'Value':<10} {'PnL':<10} {'Fee':<8}")
        print('-'*100)

        position_entries = []
        position_exits = []
        total_pnl = 0
        total_fees = 0

        for i, trade in enumerate(trades, 1):
            time_cst = datetime.fromtimestamp(int(trade['time'])/1000, tz=pytz.UTC).astimezone(cst)
            side = trade['side']
            price = float(trade['price'])
            qty = float(trade['qty'])
            value = price * qty
            pnl = float(trade['realizedPnl'])
            fee = float(trade['commission'])

            total_pnl += pnl
            total_fees += fee

            # Track entries and exits
            if side == 'BUY':
                position_entries.append({
                    'time': time_cst,
                    'price': price,
                    'qty': qty,
                    'value': value
                })
            else:  # SELL
                position_exits.append({
                    'time': time_cst,
                    'price': price,
                    'qty': qty,
                    'value': value,
                    'pnl': pnl
                })

            print(f"{i:<4} {time_cst.strftime('%m-%d %H:%M:%S'):<20} {side:<5} ${price:<11.6f} {qty:<15.1f} ${value:<9.2f} ${pnl:<9.2f} ${fee:<7.4f}")

        # Summary
        print('\n' + '='*100)
        print('CHAIN SUMMARY:')
        print('='*100)
        print(f'Total Entry Trades (BUY): {len(position_entries)}')
        print(f'Total Exit Trades (SELL): {len(position_exits)}')
        print(f'Total Realized P&L: ${total_pnl:.2f}')
        print(f'Total Fees Paid: ${total_fees:.4f}')
        print(f'Net After Fees: ${total_pnl - total_fees:.2f}')

        # Analyze entry prices vs exit prices
        if position_entries and position_exits:
            print('\n' + '='*100)
            print('ENTRY VS EXIT ANALYSIS:')
            print('='*100)

            # Calculate average entry price
            total_entry_value = sum(e['value'] for e in position_entries)
            total_entry_qty = sum(e['qty'] for e in position_entries)
            avg_entry = total_entry_value / total_entry_qty if total_entry_qty > 0 else 0

            # Calculate average exit price
            total_exit_value = sum(e['value'] for e in position_exits)
            total_exit_qty = sum(e['qty'] for e in position_exits)
            avg_exit = total_exit_value / total_exit_qty if total_exit_qty > 0 else 0

            print(f'Average Entry Price: ${avg_entry:.6f}')
            print(f'Average Exit Price: ${avg_exit:.6f}')
            print(f'Price Movement: ${avg_exit - avg_entry:.6f} ({((avg_exit/avg_entry - 1)*100):.2f}%)')
            print(f'Position Direction: LONG (bought first)')

            if avg_exit < avg_entry:
                print(f'Result: LOSS - Price moved AGAINST position (went DOWN while LONG)')
            else:
                print(f'Result: WIN - Price moved WITH position (went UP while LONG)')

        # Entry pattern analysis
        print('\n' + '='*100)
        print('ENTRY PATTERN (Martingale Escalation):')
        print('='*100)

        for i, entry in enumerate(position_entries):
            print(f"Level {i}: {entry['time'].strftime('%H:%M:%S')} | ${entry['price']:.6f} | Qty: {entry['qty']:.1f} | Value: ${entry['value']:.2f}")

        # Exit pattern analysis
        print('\n' + '='*100)
        print('EXIT PATTERN (Stop Loss Triggers):')
        print('='*100)

        for i, exit_trade in enumerate(position_exits):
            print(f"Exit {i+1}: {exit_trade['time'].strftime('%H:%M:%S')} | ${exit_trade['price']:.6f} | Qty: {exit_trade['qty']:.1f} | P&L: ${exit_trade['pnl']:.2f}")

        # Get current price
        print('\n' + '='*100)
        print('CURRENT MARKET STATUS:')
        print('='*100)

        resp = executor.client.get('https://fapi.binance.com/fapi/v1/ticker/price?symbol=GUNUSDT')
        current_price = float(resp.json()['price'])

        print(f'Current GUNUSDT Price: ${current_price:.6f}')

        if position_entries:
            first_entry = position_entries[0]['price']
            last_entry = position_entries[-1]['price']
            print(f'First Entry Price: ${first_entry:.6f}')
            print(f'Last Entry Price: ${last_entry:.6f}')
            print(f'Price Change Since First Entry: {((current_price/first_entry - 1)*100):.2f}%')
            print(f'Price Change Since Last Entry: {((current_price/last_entry - 1)*100):.2f}%')

    finally:
        executor.close()

if __name__ == '__main__':
    main()
