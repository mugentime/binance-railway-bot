"""Check ALL orders including regular and algo orders"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    print(f"\n{'='*80}")
    print("REGULAR OPEN ORDERS")
    print(f"{'='*80}\n")

    # Get regular open orders
    params = {}
    params = executor._sign_params(params)
    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/openOrders",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    regular_orders = resp.json()

    if not regular_orders:
        print("No regular open orders!")
    else:
        for i, order in enumerate(regular_orders, 1):
            print(f"{i}. {order['symbol']} | {order['type']} | {order['side']} | Qty:{order['origQty']} | Price:{order.get('price', 'N/A')}")

    print(f"\n{'='*80}")
    print("ALGO OPEN ORDERS (STOP LOSS)")
    print(f"{'='*80}\n")

    # Get algo open orders
    params = {}
    params = executor._sign_params(params)
    try:
        resp = executor.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/openOrdersAlgo",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        algo_orders = resp.json()

        if 'data' in algo_orders:
            algo_orders = algo_orders['data']

        if not algo_orders:
            print("No algo orders!")
        else:
            for i, order in enumerate(algo_orders, 1):
                print(f"{i}. {order.get('symbol')} | {order.get('orderType')} | {order.get('side')} | Qty:{order.get('quantity')} | Trigger:{order.get('activatePrice')}")
    except Exception as e:
        print(f"Error getting algo orders: {e}")

    print(f"\n{'='*80}")
    print(f"TOTAL: {len(regular_orders)} regular + {len(algo_orders) if 'algo_orders' in locals() else 0} algo = {len(regular_orders) + (len(algo_orders) if 'algo_orders' in locals() else 0)} orders")
    print(f"{'='*80}\n")

finally:
    executor.close()
