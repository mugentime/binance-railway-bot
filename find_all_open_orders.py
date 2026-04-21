"""Find all open orders across all symbols"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("ALL OPEN ORDERS")
    print("="*80 + "\n")

    # Get ALL open orders (all symbols)
    params = {}
    params = executor._sign_params(params)

    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/openOrders",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    orders = resp.json()

    print(f"Total open orders: {len(orders)}\n")

    if not orders:
        print("No open orders found!")
    else:
        for i, order in enumerate(orders, 1):
            symbol = order.get('symbol')
            order_type = order.get('type')
            side = order.get('side')
            price = order.get('stopPrice') or order.get('price')
            qty = order.get('origQty')
            order_id = order.get('orderId')

            print(f"{i}. {symbol}")
            print(f"   Type: {order_type} {side}")
            print(f"   Price: {price}")
            print(f"   Quantity: {qty}")
            print(f"   Order ID: {order_id}")
            print()

finally:
    executor.close()
