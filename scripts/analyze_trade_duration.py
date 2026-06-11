#!/usr/bin/env python3
import sys, os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from order_executor import OrderExecutor
import pytz

executor = OrderExecutor()
try:
    cst = pytz.timezone('US/Central')
    now = datetime.now(cst)
    yesterday = now - timedelta(hours=12)
    start_time_ms = int(yesterday.timestamp() * 1000)

    params = {'startTime': start_time_ms, 'limit': 1000}
    params = executor._sign_params(params)
    resp = executor.client.get('https://fapi.binance.com/fapi/v1/userTrades', params=params, headers=executor._headers())
    trades = resp.json()

    # Group by symbol and calculate position durations
    from collections import defaultdict
    symbol_trades = defaultdict(list)
    
    for t in trades:
        symbol_trades[t['symbol']].append(t)
    
    print('='*80)
    print('RECENT POSITION DURATIONS')
    print('='*80)
    
    durations = []
    for symbol, trades_list in symbol_trades.items():
        trades_list.sort(key=lambda x: x['time'])
        
        # Find entry and exit times
        entries = [t for t in trades_list if t['side'] == 'BUY']
        exits = [t for t in trades_list if t['side'] == 'SELL']
        
        if entries and exits:
            entry_time = min(t['time'] for t in entries)
            exit_time = max(t['time'] for t in exits)
            duration_ms = exit_time - entry_time
            duration_min = duration_ms / 60000
            
            pnl = sum(float(t['realizedPnl']) for t in trades_list)
            
            durations.append((symbol, duration_min, pnl, len(trades_list)))
    
    durations.sort(key=lambda x: x[1])
    
    print(f'\n{"Symbol":<15} {"Duration":<12} {"Trades":<8} {"P&L":<10}')
    print('-'*80)
    for symbol, dur, pnl, count in durations[:20]:
        print(f'{symbol:<15} {dur:>8.1f} min   {count:<8} ${pnl:>+8.2f}')
    
    avg_duration = sum(d[1] for d in durations) / len(durations) if durations else 0
    under_20 = len([d for d in durations if d[1] < 20])
    
    print('='*80)
    print(f'Average duration: {avg_duration:.1f} minutes')
    print(f'Positions under 20 min: {under_20}/{len(durations)} ({under_20/len(durations)*100:.1f}%)')
    
finally:
    executor.close()
