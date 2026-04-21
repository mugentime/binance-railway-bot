"""Cancel orphaned Stop Loss orders for specific symbols"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

# Symbols with orphaned SL orders (from user)
symbols_to_clean = [
    "RIVERUSDT",
    "NEIROUSDT",
    "LDOUSDT",
    "XMRUSDT",
    "STRKUSDT",
    "ENJUSDT"  # Assuming 6th one is ENJUSDT
]

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("CANCELLING ORPHANED STOP LOSS ORDERS")
    print("="*80 + "\n")

    for symbol in symbols_to_clean:
        try:
            print(f"Checking {symbol}...")

            # Cancel all regular orders for this symbol
            params = {"symbol": symbol}
            params = executor._sign_params(params)

            resp = executor.client.delete(
                f"{config.BINANCE_BASE_URL}/fapi/v1/allOpenOrders",
                params=params,
                headers=executor._headers()
            )
            resp.raise_for_status()
            result = resp.json()
            print(f"  [OK] Cancelled regular orders for {symbol}: {result}")

        except Exception as e:
            print(f"  [FAIL] Regular orders: {e}")

        try:
            # Cancel all algo orders (Stop Loss) for this symbol
            params = {"symbol": symbol}
            params = executor._sign_params(params)

            resp = executor.client.delete(
                f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
                params=params,
                headers=executor._headers()
            )
            resp.raise_for_status()
            result = resp.json()
            print(f"  [OK] Cancelled algo orders for {symbol}: {result}")

        except Exception as e:
            print(f"  [FAIL] Algo orders: {e}")

        print()

    print("="*80)
    print("DONE! All orphaned orders should be cancelled.")
    print("="*80)

finally:
    executor.close()
