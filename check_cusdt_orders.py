#!/usr/bin/env python3
"""Check all orders for CUSDT"""
import sys
sys.path.insert(0, 'src')

from order_executor import OrderExecutor
import config

executor = OrderExecutor()
symbol = "CUSDT"

print("="*80)
print(f"CHECKING ALL ORDERS FOR {symbol}")
print("="*80)

# Get regular open orders
print("\n1. Regular open orders (/fapi/v1/openOrders):")
try:
    params = {"symbol": symbol}
    params = executor._sign_params(params)
    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/openOrders",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    orders = resp.json()

    if orders:
        for order in orders:
            print(f"   Order ID: {order['orderId']}")
            print(f"   Type: {order['type']}")
            print(f"   Side: {order['side']}")
            print(f"   Price: {order.get('price', 'N/A')}")
            print(f"   Stop Price: {order.get('stopPrice', 'N/A')}")
            print(f"   Quantity: {order['origQty']}")
            print(f"   Status: {order['status']}")
            print()
    else:
        print("   No regular orders")
except Exception as e:
    print(f"   Error: {e}")

# Try conditional orders endpoint
print("\n2. Conditional/Algo orders (/fapi/v1/openAlgoOrders):")
try:
    params = {"symbol": symbol}
    params = executor._sign_params(params)
    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/openAlgoOrders",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    result = resp.json()

    if result and 'orders' in result and result['orders']:
        for order in result['orders']:
            print(f"   Algo ID: {order.get('algoId', 'N/A')}")
            print(f"   Type: {order.get('algoType', 'N/A')}")
            print(f"   Side: {order.get('side', 'N/A')}")
            print(f"   Trigger Price: {order.get('triggerPrice', 'N/A')}")
            print(f"   Order Price: {order.get('price', 'N/A')}")
            print(f"   Quantity: {order.get('quantity', 'N/A')}")
            print(f"   Status: {order.get('status', 'N/A')}")
            print()
    else:
        print("   No algo orders")
except Exception as e:
    print(f"   Error: {e}")

# Get current position
print("\n3. Current position:")
try:
    position = executor.get_position(symbol)
    if position:
        qty = float(position['positionAmt'])
        if qty != 0:
            direction = "LONG" if qty > 0 else "SHORT"
            entry = float(position['entryPrice'])
            pnl = float(position['unRealizedProfit'])
            print(f"   {symbol} {direction}")
            print(f"   Quantity: {abs(qty)}")
            print(f"   Entry: {entry:.6f}")
            print(f"   PNL: ${pnl:.2f}")
        else:
            print("   No position")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "="*80)
