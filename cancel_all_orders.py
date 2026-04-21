#!/usr/bin/env python3
"""
Cancel ALL open orders across ALL symbols
Use this after config changes to remove old TP/SL orders
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
        print("CANCELLING ALL OPEN ORDERS")
        print("="*80)

        if not positions:
            print("\n✓ No open positions found - no orders to cancel")
            return

        print(f"\nFound {len(positions)} open position(s), cancelling all orders...")

        for pos in positions:
            symbol = pos['symbol']
            print(f"\n→ Cancelling orders for {symbol}...")

            try:
                executor.cancel_all_orders(symbol)
                print(f"  ✓ All orders cancelled for {symbol}")
            except Exception as e:
                print(f"  ✗ Error cancelling orders for {symbol}: {e}")

        print("\n" + "="*80)
        print("✓ DONE - All orders cancelled")
        print("="*80)
        print("\nNext steps:")
        print("1. Restart the bot to place new TP/SL orders with updated config")
        print("2. Or manually close positions on Binance if you want to reset")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        executor.close()

if __name__ == "__main__":
    main()
