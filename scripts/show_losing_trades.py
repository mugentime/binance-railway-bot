#!/usr/bin/env python3
import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from order_executor import OrderExecutor
import pytz

executor = OrderExecutor()
try:
    cst = pytz.timezone('US/Central')
    now = datetime.now(cst)
    yesterday = now - timedelta(days=1)
    start_time_ms = int(yesterday.timestamp() * 1000)

    params = {'startTime': start_time_ms, 'limit': 1000}
    params = executor._sign_params(params)
    resp = executor.client.get('https://fapi.binance.com/fapi/v1/userTrades', params=params, headers=executor._headers())
    trades = resp.json()

    from collections import defaultdict
    symbol_pnl = defaultdict(float)
    symbol_trades = defaultdict(list)

    for t in trades:
        symbol = t['symbol']
        symbol_pnl[symbol] += float(t['realizedPnl'])
        symbol_trades[symbol].append(t)

    sorted_symbols = sorted(symbol_pnl.items(), key=lambda x: x[1])

    print('='*80)
    print('WORST PERFORMERS (24h):')
    print('='*80)
    for symbol, pnl in sorted_symbols[:10]:
        trade_count = len(symbol_trades[symbol])
        print(f'{symbol:15} | Trades: {trade_count:3} | PNL: ${pnl:+8.2f}')

    if sorted_symbols:
        worst_symbol, worst_pnl = sorted_symbols[0]
        print()
        print('='*80)
        print(f'WORST CHAIN DETAILS: {worst_symbol} (${worst_pnl:.2f})')
        print('='*80)

        worst_trades = symbol_trades[worst_symbol]
        worst_trades.sort(key=lambda x: x['time'])

        entries = [t for t in worst_trades if t['side'] == 'BUY']
        exits = [t for t in worst_trades if t['side'] == 'SELL']

        print(f'Total trades: {len(worst_trades)} ({len(entries)} entries, {len(exits)} exits)')
        print(f'Direction: {"LONG" if entries else "SHORT"}')

        if entries:
            entry_prices = [float(t['price']) for t in entries]
            print(f'Entry range: ${min(entry_prices):.6f} -> ${max(entry_prices):.6f}')

        if exits:
            exit_prices = [float(t['price']) for t in exits]
            print(f'Exit range: ${min(exit_prices):.6f} -> ${max(exit_prices):.6f}')

finally:
    executor.close()
