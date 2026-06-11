#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from order_executor import OrderExecutor

executor = OrderExecutor()
try:
    # Check for open algo orders (conditional orders)
    params = {}
    params = executor._sign_params(params)
    resp = executor.client.get('https://fapi.binance.com/fapi/v1/openAlgoOrders', params=params, headers=executor._headers())
    algo_orders = resp.json()
    
    print('='*80)
    print('OPEN CONDITIONAL ORDERS (Stop Loss / Take Profit)')
    print('='*80)
    
    if 'data' in algo_orders and algo_orders['data']:
        orders = algo_orders['data']
        for order in orders:
            symbol = order.get('symbol')
            side = order.get('side')
            order_type = order.get('orderType')
            stop_price = order.get('stopPrice')
            algo_id = order.get('algoId')
            print(f'Symbol: {symbol}')
            print(f'Type: {order_type} {side}')
            print(f'Stop Price: ${stop_price}')
            print(f'Algo ID: {algo_id}')
            print('-'*80)
    else:
        print('No conditional orders found')
    
    print()
    
    # Check positions
    resp = executor.client.get('https://fapi.binance.com/fapi/v2/positionRisk', params=executor._sign_params({}), headers=executor._headers())
    positions = [p for p in resp.json() if float(p['positionAmt']) != 0]
    
    print('OPEN POSITIONS:')
    print('-'*80)
    if positions:
        for pos in positions:
            print(f'{pos["symbol"]}: {float(pos["positionAmt"])} units')
    else:
        print('No open positions')
    
    print('='*80)
    
finally:
    executor.close()
