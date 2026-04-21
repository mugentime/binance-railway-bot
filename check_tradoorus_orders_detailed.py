"""Check all order types for TRADOORUSDT"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
import json

executor = OrderExecutor()

try:
    symbol = "TRADOORUSDT"

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

        print(f"   Found {len(orders)} order(s):")
        for order in orders:
            print(f"     Type: {order['type']}, Side: {order['side']}, "
                  f"Price: {order.get('price', 'N/A')}, Stop: {order.get('stopPrice', 'N/A')}")
    except Exception as e:
        print(f"   Error: {e}")

    # Try conditional orders endpoint
    print("\n2. Conditional/Algo orders (/fapi/v1/algoOpenOrders):")
    try:
        params = {"symbol": symbol}
        params = executor._sign_params(params)
        resp = executor.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        result = resp.json()

        # Handle different response formats
        if isinstance(result, dict) and 'data' in result:
            orders = result['data']
        else:
            orders = result if isinstance(result, list) else []

        print(f"   Found {len(orders)} conditional order(s):")
        for order in orders:
            print(f"     {json.dumps(order, indent=6)}")
    except Exception as e:
        print(f"   Error: {e}")

    # Try openOrders endpoint (all types)
    print("\n3. All open orders (/fapi/v1/allOpenOrders - deprecated?):")
    try:
        params = {"symbol": symbol}
        params = executor._sign_params(params)
        resp = executor.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/allOpenOrders",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        orders = resp.json()

        print(f"   Found {len(orders)} order(s)")
    except Exception as e:
        print(f"   Error (likely 404 - endpoint deprecated): {e}")

    print("\n" + "="*80)

finally:
    executor.close()
