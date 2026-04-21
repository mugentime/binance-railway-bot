"""Cancel orphaned BASEDUSDT orders"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("CANCELLING BASEDUSDT ORDERS")
    print("="*80 + "\n")

    symbol = "BASEDUSDT"

    # Cancel all regular orders
    try:
        params = {"symbol": symbol}
        params = executor._sign_params(params)
        resp = executor.client.delete(
            f"{config.BINANCE_BASE_URL}/fapi/v1/allOpenOrders",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        print(f"[OK] Cancelled regular orders for {symbol}")
    except Exception as e:
        print(f"[INFO] Regular orders: {e}")

    # Cancel all algo orders
    try:
        params = {"symbol": symbol}
        params = executor._sign_params(params)
        resp = executor.client.delete(
            f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        print(f"[OK] Cancelled algo orders for {symbol}")
    except Exception as e:
        print(f"[INFO] Algo orders: {e}")

    print("\n" + "="*80)
    print("DONE! BASEDUSDT should be clear now.")
    print("="*80)

finally:
    executor.close()
