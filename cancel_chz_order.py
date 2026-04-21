"""Cancel orphaned CHZUSDT conditional order"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("CANCELLING CHZUSDT CONDITIONAL ORDERS")
    print("="*80 + "\n")

    symbol = "CHZUSDT"

    # Cancel all algo orders for this symbol
    params = {"symbol": symbol}
    params = executor._sign_params(params)

    resp = executor.client.delete(
        f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    result = resp.json()
    print(f"[OK] Cancelled algo orders for {symbol}: {result}")

except Exception as e:
    print(f"[FAIL] {e}")

finally:
    executor.close()
