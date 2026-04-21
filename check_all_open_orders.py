#!/usr/bin/env python3
"""
Check ALL open orders across ALL symbols (including orphaned orders)
"""
import sys
sys.path.insert(0, 'src')

from order_executor import OrderExecutor

def main():
    executor = OrderExecutor()

    try:
        print("\n" + "="*80)
        print("CHECKING ALL OPEN ORDERS (Including orphaned orders)")
        print("="*80)

        # Get ALL open orders (no symbol filter)
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
            print("\n[OK] No open orders found")
        else:
            print(f"\n[ALERT] Found {len(all_orders)} open order(s):")

            for order in all_orders:
                symbol = order.get('symbol')
                order_type = order.get('type')
                side = order.get('side')
                price = float(order.get('price', 0))
                stop_price = float(order.get('stopPrice', 0))
                qty = float(order.get('origQty', 0))
                order_id = order.get('orderId')

                print(f"\n  Symbol: {symbol}")
                print(f"    Type: {order_type} {side}")
                print(f"    Price: {price if price else stop_price:.6f}")
                print(f"    Quantity: {qty}")
                print(f"    Order ID: {order_id}")

                if order_type == 'LIMIT' and side in ['SELL', 'BUY']:
                    print(f"    [INFO] This is likely a TP order")

        print("\n" + "="*80)
        print("ACTION REQUIRED:")
        print("="*80)
        if all_orders:
            print("Run: python cancel_all_open_orders.py")
            print("This will cancel ALL open orders across ALL symbols")
        else:
            print("No action needed - no open orders found")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        executor.close()

if __name__ == "__main__":
    main()
