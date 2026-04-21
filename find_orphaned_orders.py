"""Find orphaned conditional orders by checking recent symbols"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config

executor = OrderExecutor()

# Symbols that had positions recently (from logs)
recent_symbols = [
    "AAVEUSDT", "BIOUSDT", "SIRENUSDT", "STRKUSDT",
    "XMRUSDT", "ENJUSDT", "LDOUSDT", "NEIROUSDT",
    "RIVERUSDT", "WLDUSDT", "STOUSDT", "COMPUSDT"
]

try:
    print("\n" + "="*80)
    print("SEARCHING FOR ORPHANED CONDITIONAL ORDERS")
    print("="*80 + "\n")

    all_found_orders = []

    for symbol in recent_symbols:
        try:
            # Get all open orders for this symbol (includes regular + conditional)
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
                print(f"\n{symbol}: {len(orders)} open orders")
                for order in orders:
                    order_type = order.get('type')
                    side = order.get('side')
                    price = order.get('stopPrice') or order.get('price')
                    qty = order.get('origQty')
                    order_id = order.get('orderId')

                    print(f"  - {order_type} {side} @ {price} qty={qty} (ID: {order_id})")
                    all_found_orders.append({
                        'symbol': symbol,
                        'order': order
                    })

        except Exception as e:
            # Skip symbols with no orders
            pass

    print(f"\n" + "="*80)
    print(f"TOTAL ORDERS FOUND: {len(all_found_orders)}")
    print("="*80 + "\n")

    if all_found_orders:
        print("Do you want to CANCEL all these orders? (y/n): ", end="")
        choice = input().strip().lower()

        if choice == 'y':
            print("\nCancelling orders...")
            for item in all_found_orders:
                symbol = item['symbol']
                order = item['order']
                order_id = order.get('orderId')

                try:
                    params = {"symbol": symbol, "orderId": order_id}
                    params = executor._sign_params(params)

                    resp = executor.client.delete(
                        f"{config.BINANCE_BASE_URL}/fapi/v1/order",
                        params=params,
                        headers=executor._headers()
                    )
                    resp.raise_for_status()
                    print(f"  Cancelled: {symbol} order {order_id}")

                except Exception as e:
                    print(f"  Failed: {symbol} - {e}")

            print("\nDone!")
        else:
            print("No orders cancelled.")
    else:
        print("No open orders found on any recent symbols.")

finally:
    executor.close()
