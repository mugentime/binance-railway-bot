#!/usr/bin/env python3
"""
Cancel ALL open orders across ALL symbols
WARNING: This will cancel EVERYTHING
"""
import sys
sys.path.insert(0, 'src')

from order_executor import OrderExecutor

def main():
    executor = OrderExecutor()

    try:
        print("\n" + "="*80)
        print("WARNING: CANCELLING ALL OPEN ORDERS")
        print("="*80)

        # Get ALL open orders
        params = {}
        params = executor._sign_params(params)

        resp = executor.client.get(
            f"https://fapi.binance.com/fapi/v1/openOrders",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        all_orders = resp.json()

        if not all_orders:
            print("\n[OK] No open orders to cancel")
            return

        print(f"\n[INFO] Found {len(all_orders)} open order(s)")

        # Group by symbol
        from collections import defaultdict
        symbol_orders = defaultdict(list)

        for order in all_orders:
            symbol_orders[order['symbol']].append(order)

        # Cancel orders for each symbol
        for symbol, orders in symbol_orders.items():
            print(f"\n→ Cancelling {len(orders)} order(s) for {symbol}...")

            try:
                executor.cancel_all_orders(symbol)
                print(f"  [OK] Cancelled all orders for {symbol}")
            except Exception as e:
                print(f"  [ERROR] Failed to cancel orders for {symbol}: {e}")

        print("\n" + "="*80)
        print("[SUCCESS] All open orders cancelled")
        print("="*80)
        print("\nNext step: Restart the bot to place new 10% TP orders")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        executor.close()

if __name__ == "__main__":
    main()
