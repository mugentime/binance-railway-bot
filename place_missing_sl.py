"""
Emergency script to place missing SL order for TRADOORUSDT
"""
import sys
sys.path.insert(0, 'src')

from order_executor import OrderExecutor
import config
from utils import log

def main():
    print("="*80)
    print("EMERGENCY: Placing missing SL for TRADOORUSDT")
    print("="*80)

    executor = OrderExecutor()

    try:
        # Get current position
        symbol = "TRADOORUSDT"
        position = executor.get_position(symbol)

        if not position or float(position['positionAmt']) == 0:
            print(f"No open position for {symbol}")
            return

        # Parse position details
        position_amt = float(position['positionAmt'])
        entry_price = float(position['entryPrice'])
        direction = "LONG" if position_amt > 0 else "SHORT"
        quantity = abs(position_amt)

        print(f"\nCurrent position:")
        print(f"  Symbol: {symbol}")
        print(f"  Direction: {direction}")
        print(f"  Entry: {entry_price}")
        print(f"  Quantity: {quantity}")

        # Calculate SL price (4% from entry)
        if direction == "LONG":
            sl_price = entry_price * (1 - config.SL_PCT)
        else:  # SHORT
            sl_price = entry_price * (1 + config.SL_PCT)

        print(f"  Calculated SL: {sl_price:.6f} ({config.SL_PCT*100:.1f}% from entry)")

        # Check existing orders
        open_orders = executor.get_open_orders(symbol)
        print(f"\nExisting orders: {len(open_orders)}")

        has_sl = False
        for order in open_orders:
            order_type = order.get('type', '')
            print(f"  - {order_type} {order.get('side', '')} @ {order.get('price', order.get('stopPrice', 'N/A'))}")
            if order_type in ['STOP_MARKET', 'STOP']:
                has_sl = True

        if has_sl:
            print("\nOK: SL order already exists - no action needed")
            return

        # Place missing SL
        print(f"\nWARNING: MISSING SL DETECTED - Placing now...")
        print(f"Will place SL @ {sl_price:.6f} for {quantity} {symbol}")

        # Use the verify_and_place_missing_sl function
        tp_price = entry_price * (1 + config.TP_PCT) if direction == "LONG" else entry_price * (1 - config.TP_PCT)

        sl_ok = executor.verify_and_place_missing_sl(
            symbol=symbol,
            direction=direction,
            tp_price=tp_price,
            sl_price=sl_price,
            quantity=quantity
        )

        if sl_ok:
            print("\nSUCCESS: SL order placed successfully")
        else:
            print("\nFAILED: Could not place SL order")
            print("Check logs for details")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        executor.close()

if __name__ == "__main__":
    main()
