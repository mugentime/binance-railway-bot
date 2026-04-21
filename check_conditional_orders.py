"""Check and list all conditional/algo orders"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    print(f"\n{'='*80}")
    print("CONDITIONAL/ALGO ORDERS (STOP LOSS)")
    print(f"{'='*80}\n")

    # Try different endpoints for algo orders
    endpoints = [
        "/fapi/v1/openOrders/algo",  # Try this first
        "/fapi/v2/openOrders",         # Try v2
    ]

    for endpoint in endpoints:
        try:
            params = {"symbol": None}  # Get all symbols
            params = executor._sign_params(params)
            if params.get("symbol") is None:
                del params["symbol"]

            resp = executor.client.get(
                f"{config.BINANCE_BASE_URL}{endpoint}",
                params=params,
                headers=executor._headers()
            )
            resp.raise_for_status()
            orders = resp.json()

            print(f"✓ Found endpoint: {endpoint}")
            print(f"Total conditional orders: {len(orders)}\n")

            for i, order in enumerate(orders, 1):
                print(f"Order {i}:")
                print(f"  Symbol: {order.get('symbol')}")
                print(f"  Type: {order.get('orderType', order.get('type'))}")
                print(f"  Side: {order.get('side')}")
                print(f"  Activate Price: {order.get('activatePrice', order.get('stopPrice'))}")
                print(f"  Quantity: {order.get('quantity', order.get('origQty'))}")
                print(f"  Algo ID: {order.get('algoId', order.get('orderId'))}")
                print()

            break

        except Exception as e:
            print(f"✗ Endpoint {endpoint} failed: {e}")
            continue
    else:
        print("\nAll endpoints failed. Let me try the working endpoint from the code...")

        # This is what the bot uses to query - let's try it
        # Based on the cancellation code that works
        print("\nTrying to get open orders for each recent symbol...")

        recent_symbols = ["ENJUSDT", "RIVERUSDT", "NEIROUSDT", "LDOUSDT", "XMRUSDT", "STRKUSDT"]

        for symbol in recent_symbols:
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
                    print(f"\n{symbol}: {len(orders)} orders")
                    for order in orders:
                        print(f"  - {order['type']} {order['side']} @ {order.get('stopPrice', order.get('price'))}")

            except Exception as e:
                pass

finally:
    executor.close()
