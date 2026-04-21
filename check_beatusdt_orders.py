"""Check BEATUSDT orders"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("BEATUSDT ORDERS CHECK")
    print("="*80 + "\n")

    symbol = "BEATUSDT"

    # Check regular orders
    print("Regular Orders:")
    try:
        params = {"symbol": symbol}
        params = executor._sign_params(params)
        resp = executor.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/openOrders",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        regular_orders = resp.json()

        if regular_orders:
            for order in regular_orders:
                print(f"  Order ID: {order['orderId']}")
                print(f"  Type: {order['type']}")
                print(f"  Side: {order['side']}")
                print(f"  Price: {order.get('price', 'N/A')}")
                print(f"  Stop Price: {order.get('stopPrice', 'N/A')}")
                print(f"  Status: {order['status']}")
                print()
        else:
            print("  None\n")
    except Exception as e:
        print(f"  Error: {e}\n")

    # Check algo orders
    print("Algo Orders (Conditional):")
    try:
        params = {"symbol": symbol}
        params = executor._sign_params(params)
        resp = executor.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()

        # Response might be {"algoOrders": [...]} or just [...]
        data = resp.json()
        if isinstance(data, dict):
            algo_orders = data.get('algoOrders', [])
        else:
            algo_orders = data

        if algo_orders:
            for order in algo_orders:
                print(f"  Algo ID: {order.get('algoId', 'N/A')}")
                print(f"  Type: {order.get('algoType', 'N/A')}")
                print(f"  Side: {order['side']}")
                print(f"  Activation Price: {order.get('activationPrice', 'N/A')}")
                print(f"  Callback Rate: {order.get('callbackRate', 'N/A')}")
                print(f"  Status: {order.get('algoStatus', 'N/A')}")
                print()
        else:
            print("  None\n")
    except Exception as e:
        print(f"  Error: {e}\n")

    print("="*80)

finally:
    executor.close()
