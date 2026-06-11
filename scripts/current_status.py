#!/usr/bin/env python3
"""Quick current status check"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from order_executor import OrderExecutor

executor = OrderExecutor()
try:
    # Get balance
    params = {}
    params = executor._sign_params(params)
    resp = executor.client.get('https://fapi.binance.com/fapi/v2/account', params=params, headers=executor._headers())
    account = resp.json()

    wallet = float(account['totalWalletBalance'])
    unrealized = float(account['totalUnrealizedProfit'])
    margin = float(account['totalMarginBalance'])
    available = float(account['availableBalance'])

    print('='*80)
    print('CURRENT ACCOUNT STATUS')
    print('='*80)
    print(f'Wallet Balance:    ${wallet:.2f}')
    print(f'Unrealized P&L:    ${unrealized:+.2f}')
    print(f'Margin Balance:    ${margin:.2f}')
    print(f'Available Balance: ${available:.2f}')
    print()

    # Get positions
    resp = executor.client.get('https://fapi.binance.com/fapi/v2/positionRisk', params=executor._sign_params({}), headers=executor._headers())
    positions = [p for p in resp.json() if float(p['positionAmt']) != 0]

    if positions:
        print('OPEN POSITIONS:')
        print('-'*80)
        for pos in positions:
            symbol = pos['symbol']
            amt = float(pos['positionAmt'])
            entry = float(pos['entryPrice'])
            mark = float(pos.get('markPrice', entry))
            pnl = float(pos['unRealizedProfit'])
            pnl_pct = (pnl / abs(amt * entry)) * 100 if amt != 0 else 0
            side = 'LONG' if amt > 0 else 'SHORT'

            print(f'{symbol:12} {side:5} | Entry: ${entry:.6f} | Mark: ${mark:.6f}')
            print(f'             Qty: {abs(amt):,.1f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)')
    else:
        print('No open positions')
    print('='*80)

finally:
    executor.close()
