#!/usr/bin/env python3
"""Get trades from last 24 hours."""

import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor
import pytz

def main():
    executor = OrderExecutor()
    try:
        # Get trades from last 24 hours
        cst = pytz.timezone('US/Central')
        now = datetime.now(cst)
        yesterday = now - timedelta(days=1)
        start_time_ms = int(yesterday.timestamp() * 1000)

        params = {'startTime': start_time_ms, 'limit': 1000}
        params = executor._sign_params(params)

        resp = executor.client.get('https://fapi.binance.com/fapi/v1/userTrades', params=params, headers=executor._headers())
        resp.raise_for_status()
        trades = resp.json()

        print('='*80)
        print(f'TRADES IN LAST 24 HOURS: {len(trades)} trades')
        print('='*80)

        # Calculate total realized P&L
        total_pnl = sum(float(t['realizedPnl']) for t in trades)

        # Group by symbol
        symbols = {}
        for trade in trades:
            symbol = trade['symbol']
            if symbol not in symbols:
                symbols[symbol] = {'trades': 0, 'pnl': 0}
            symbols[symbol]['trades'] += 1
            symbols[symbol]['pnl'] += float(trade['realizedPnl'])

        print(f'\nTotal Realized P&L (24h): ${total_pnl:.2f}')
        print(f'Number of symbols traded: {len(symbols)}')

        print('\nTop 10 Symbols by P&L:')
        print('-'*80)
        sorted_symbols = sorted(symbols.items(), key=lambda x: x[1]['pnl'], reverse=True)
        for i, (symbol, data) in enumerate(sorted_symbols[:10], 1):
            print(f'{i:2}. {symbol:12} | Trades: {data["trades"]:3} | P&L: ${data["pnl"]:+8.2f}')

        print('\n10 Most Recent Trades:')
        print('-'*80)

        for i, trade in enumerate(sorted(trades, key=lambda x: x['time'], reverse=True)[:10], 1):
            time_cst = datetime.fromtimestamp(int(trade['time'])/1000, tz=pytz.UTC).astimezone(cst)
            pnl = float(trade['realizedPnl'])
            print(f'{i:2}. {trade["symbol"]:12} {trade["side"]:5} | {time_cst.strftime("%m-%d %H:%M CST")} | Qty: {float(trade["qty"]):8.4f} | P&L: ${pnl:+7.2f}')

    finally:
        executor.close()

if __name__ == '__main__':
    main()
