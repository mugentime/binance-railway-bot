#!/usr/bin/env python3
"""
Check all open orders across all symbols
"""
import sys
sys.path.insert(0, 'src')

from order_executor import OrderExecutor
from utils import log

def main():
    executor = OrderExecutor()

    try:
        # Get all open positions
        positions = executor.get_all_open_positions()

        print("\n" + "="*80)
        print("CHECKING FOR OLD TP/SL ORDERS")
        print("="*80)

        if not positions:
            print("\n[OK] No open positions found")
        else:
            print(f"\n[WARNING] Found {len(positions)} open position(s):")
            for pos in positions:
                symbol = pos['symbol']
                qty = float(pos['positionAmt'])
                direction = "LONG" if qty > 0 else "SHORT"
                entry = float(pos['entryPrice'])

                print(f"\n{'='*60}")
                print(f"Symbol: {symbol}")
                print(f"Direction: {direction}")
                print(f"Entry Price: {entry:.6f}")
                print(f"Position Size: {abs(qty)}")

                # Check for open orders on this symbol
                try:
                    orders = executor.get_open_orders(symbol)

                    if not orders:
                        print("  [OK] No open orders (TP/SL might have been removed!)")
                    else:
                        print(f"  [WARNING] Found {len(orders)} open order(s):")
                        for order in orders:
                            order_type = order.get('type', 'UNKNOWN')
                            side = order.get('side', 'UNKNOWN')
                            price = float(order.get('price', 0))
                            stop_price = float(order.get('stopPrice', 0))

                            # Calculate TP percentage
                            if order_type == 'LIMIT':
                                pct = ((price - entry) / entry * 100) if direction == "LONG" else ((entry - price) / entry * 100)
                                print(f"    - {order_type} {side} @ {price:.6f} ({pct:+.2f}%)")

                                if abs(pct - 0.4) < 0.1:
                                    print(f"      [ALERT] OLD 0.4% TP ORDER FOUND!")
                                elif abs(pct - 10.0) < 0.5:
                                    print(f"      [OK] Correct 10% TP order")
                            elif order_type == 'STOP_MARKET':
                                pct = ((stop_price - entry) / entry * 100) if direction == "LONG" else ((entry - stop_price) / entry * 100)
                                print(f"    - {order_type} {side} trigger={stop_price:.6f} ({pct:+.2f}%)")
                            else:
                                print(f"    - {order_type} {side} @ {price if price else stop_price:.6f}")

                except Exception as e:
                    print(f"  [ERROR] Error checking orders: {e}")

        print("\n" + "="*80)
        print("RECOMMENDATION:")
        print("="*80)
        print("If you found old 0.4% TP orders above:")
        print("1. Cancel all orders: python cancel_all_orders.py")
        print("2. Or manually cancel them on Binance")
        print("3. Then restart the bot to place new 10% TP orders")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        executor.close()

if __name__ == "__main__":
    main()
