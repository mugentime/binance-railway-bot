"""List and optionally cancel all conditional/algo orders"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("CONDITIONAL/ALGO ORDERS")
    print("="*80 + "\n")

    # Use the endpoint that works for cancelling (should also work for listing)
    params = {}
    params = executor._sign_params(params)

    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    result = resp.json()

    # The response might be wrapped in a "data" field
    if isinstance(result, dict) and 'data' in result:
        orders = result['data']
    else:
        orders = result

    print(f"Total conditional orders: {len(orders)}\n")

    if not orders:
        print("No conditional orders found!")
    else:
        for i, order in enumerate(orders, 1):
            print(f"Order {i}:")
            print(f"  Symbol: {order.get('symbol')}")
            print(f"  Side: {order.get('side')}")
            print(f"  Activate Price: {order.get('activatePrice')}")
            print(f"  Quantity: {order.get('quantity')}")
            print(f"  Algo ID: {order.get('algoId')}")
            print(f"  Time: {order.get('activationTime', order.get('time', 'N/A'))}")
            print()

        # Ask if user wants to cancel all
        print("\n" + "="*80)
        print("Would you like to CANCEL all these orders? (y/n): ", end="")
        choice = input().strip().lower()

        if choice == 'y':
            print("\nCancelling all conditional orders...")
            for order in orders:
                try:
                    symbol = order.get('symbol')
                    algo_id = order.get('algoId')

                    params = {"symbol": symbol, "algoId": algo_id}
                    params = executor._sign_params(params)

                    resp = executor.client.delete(
                        f"{config.BINANCE_BASE_URL}/fapi/v1/algoOrder",
                        params=params,
                        headers=executor._headers()
                    )
                    resp.raise_for_status()
                    print(f"  Cancelled: {symbol} (algoId: {algo_id})")
                except Exception as e:
                    print(f"  Failed to cancel {symbol}: {e}")

            print("\nAll orders cancelled!")
        else:
            print("\nNo orders cancelled.")

finally:
    executor.close()
