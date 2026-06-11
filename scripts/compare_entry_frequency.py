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
    
    # Compare two periods:
    # Period 1: June 8-9 (before my changes)
    # Period 2: June 10-11 (after my changes)
    
    june8_start = datetime(2026, 6, 8, 0, 0, tzinfo=cst)
    june8_end = datetime(2026, 6, 10, 0, 0, tzinfo=cst)
    june10_start = datetime(2026, 6, 10, 0, 0, tzinfo=cst)
    june10_end = datetime(2026, 6, 11, 23, 59, tzinfo=cst)
    
    def analyze_period(start_dt, end_dt, label):
        start_ms = int(start_dt.timestamp() * 1000)
        params = {'startTime': start_ms, 'limit': 1000}
        params = executor._sign_params(params)
        resp = executor.client.get('https://fapi.binance.com/fapi/v1/userTrades', 
                                   params=params, headers=executor._headers())
        trades = resp.json()
        
        # Filter to period
        trades = [t for t in trades if start_ms <= t['time'] <= int(end_dt.timestamp() * 1000)]
        
        # Count entries during overnight hours (00:00-08:00 CST)
        overnight_entries = []
        for t in trades:
            if t['side'] == 'BUY' or t['side'] == 'SELL':  # Entry trades
                trade_dt = datetime.fromtimestamp(t['time']/1000, tz=pytz.UTC).astimezone(cst)
                if 0 <= trade_dt.hour < 8:  # Overnight hours
                    overnight_entries.append(t)
        
        # Count unique symbols (positions)
        from collections import defaultdict
        symbol_entries = defaultdict(list)
        for t in overnight_entries:
            symbol_entries[t['symbol']].append(t)
        
        print(f'\n{label}')
        print(f'  Total overnight entries: {len(overnight_entries)}')
        print(f'  Unique overnight positions: {len(symbol_entries)}')
        print(f'  Symbols: {", ".join(list(symbol_entries.keys())[:10])}')
        
        return len(overnight_entries), len(symbol_entries)
    
    print('='*80)
    print('OVERNIGHT ENTRY FREQUENCY COMPARISON')
    print('='*80)
    
    before = analyze_period(june8_start, june8_end, 'BEFORE MY CHANGES (June 8-9)')
    after = analyze_period(june10_start, june10_end, 'AFTER MY CHANGES (June 10-11)')
    
    print(f'\n{"="*80}')
    print(f'CHANGE: {after[0] - before[0]:+d} entries ({after[1] - before[1]:+d} positions)')
    
finally:
    executor.close()
