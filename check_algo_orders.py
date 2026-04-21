"""Check algo orders (stop loss orders)"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    # Get all algo orders
    params = {}
    params = executor._sign_params(params)
    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/allOpenOrders",  # All types of orders
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    orders = resp.json()

    print(f"\n{'='*80}")
    print(f"ALL OPEN ORDERS (INCLUDING ALGO): {len(orders)} total")
    print(f"{'='*80}\n")

    if not orders:
        print("No open orders found!")
    else:
        for i, order in enumerate(orders, 1):
            print(f"Order {i}:")
            print(f"  Symbol: {order['symbol']}")
            print(f"  Type: {order['type']}")
            print(f"  Side: {order['side']}")
            stop_price = order.get('stopPrice', 'N/A')
            price = order.get('price', 'N/A')
            print(f"  Price: {price}")
            print(f"  Stop Price: {stop_price}")
            print(f"  Quantity: {order['origQty']}")
            print(f"  Status: {order['status']}")
            print(f"  Time: {order['time']}")
            print()

finally:
    executor.close()
