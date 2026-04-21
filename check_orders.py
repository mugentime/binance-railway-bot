"""Quick script to check open orders on Binance"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
from utils import log
import config

executor = OrderExecutor()

try:
    # Get all open orders
    params = {}
    params = executor._sign_params(params)
    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/openOrders",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    orders = resp.json()

    print(f"\n{'='*80}")
    print(f"OPEN ORDERS: {len(orders)} total")
    print(f"{'='*80}\n")

    if not orders:
        print("No open orders found!")
    else:
        for i, order in enumerate(orders, 1):
            print(f"Order {i}:")
            print(f"  Symbol: {order['symbol']}")
            print(f"  Type: {order['type']}")
            print(f"  Side: {order['side']}")
            print(f"  Price: {order.get('stopPrice') or order.get('price', 'N/A')}")
            print(f"  Quantity: {order['origQty']}")
            print(f"  Status: {order['status']}")
            print(f"  Order ID: {order['orderId']}")
            print()

    # Also check all positions
    print(f"\n{'='*80}")
    print("OPEN POSITIONS")
    print(f"{'='*80}\n")

    params = {}
    params = executor._sign_params(params)
    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v2/positionRisk",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    positions = resp.json()

    open_positions = [p for p in positions if float(p['positionAmt']) != 0]

    if not open_positions:
        print("No open positions found!")
    else:
        for pos in open_positions:
            print(f"Position: {pos['symbol']}")
            print(f"  Side: {'LONG' if float(pos['positionAmt']) > 0 else 'SHORT'}")
            print(f"  Size: {pos['positionAmt']}")
            print(f"  Entry Price: {pos['entryPrice']}")
            print(f"  Unrealized PnL: ${float(pos['unRealizedProfit']):.2f}")
            print()

finally:
    executor.close()
