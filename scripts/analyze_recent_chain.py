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

    params = {
        'startTime': start_time_ms,
        'limit': 1000
    }
    params = executor._sign_params(params)
    resp = executor.client.get('https://fapi.binance.com/fapi/v1/userTrades', params=params, headers=executor._headers())
    trades = resp.json()

    # Group by symbol
    from collections import defaultdict
    symbol_pnl = defaultdict(float)
    symbol_trades = defaultdict(list)
    
    for t in trades:
        symbol = t['symbol']
        symbol_pnl[symbol] += float(t['realizedPnl'])
        symbol_trades[symbol].append(t)

    # Find worst performer
    worst_symbol = min(symbol_pnl.items(), key=lambda x: x[1])
    symbol, total_pnl = worst_symbol
    
    print('='*80)
    print(f'WORST CHAIN: {symbol} (Total P&L: ${total_pnl:.2f})')
    print('='*80)
    
    # Analyze trades
    symbol_data = symbol_trades[symbol]
    symbol_data.sort(key=lambda x: x['time'])
    
    print(f'\nTotal trades: {len(symbol_data)}')
    
    entries = [t for t in symbol_data if t['side'] == 'BUY']
    exits = [t for t in symbol_data if t['side'] == 'SELL']
    
    print(f'Entries (BUY): {len(entries)}')
    print(f'Exits (SELL): {len(exits)}')
    
    if entries:
        print('\nENTRY PRICES:')
        total_qty = sum(float(t['qty']) for t in entries)
        total_value = sum(float(t['price']) * float(t['qty']) for t in entries)
        avg_entry = total_value / total_qty if total_qty > 0 else 0
        print(f'  Average entry: ${avg_entry:.6f}')
        print(f'  First entry: ${float(entries[0]["price"]):.6f}')
        print(f'  Last entry: ${float(entries[-1]["price"]):.6f}')
    
    if exits:
        print('\nEXIT PRICES:')
        total_qty = sum(float(t['qty']) for t in exits)
        total_value = sum(float(t['price']) * float(t['qty']) for t in exits)
        avg_exit = total_value / total_qty if total_qty > 0 else 0
        print(f'  Average exit: ${avg_exit:.6f}')
        print(f'  First exit: ${float(exits[0]["price"]):.6f}')
        print(f'  Last exit: ${float(exits[-1]["price"]):.6f}')
    
    if entries and exits:
        direction = 'LONG'
        price_move_pct = ((avg_exit - avg_entry) / avg_entry) * 100
        print(f'\nDIRECTION: {direction}')
        print(f'Price movement: {price_move_pct:+.2f}%')
        
        if price_move_pct < 0:
            print('Result: Price moved DOWN while LONG (LOSS)')
        else:
            print('Result: Price moved UP while LONG (WIN)')

finally:
    executor.close()
