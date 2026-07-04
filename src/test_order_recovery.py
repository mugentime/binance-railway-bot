"""
Test the new verify_and_place_missing_orders function
"""
import sys
sys.path.insert(0, '.')

from order_executor import OrderExecutor
from utils import log
import config

def main():
    executor = OrderExecutor()

    try:
        # Get current position
        positions = executor.get_all_open_positions()
        if len(positions) == 0:
            log("No open positions to test")
            return

        pos = positions[0]
        symbol = pos.get('symbol')
        amt = float(pos.get('positionAmt'))
        entry = float(pos.get('entryPrice'))

        direction = "LONG" if amt > 0 else "SHORT"
        quantity = abs(amt)

        log(f"Testing verify_and_place_missing_orders for {symbol}")
        log(f"Direction: {direction}, Entry: {entry}, Qty: {quantity}")

        # Calculate TP/SL prices (using config percentages)
        if direction == "LONG":
            tp_price = entry * (1 + config.TP_PCT)
            sl_price = entry * (1 - config.SL_PCT)
        else:
            tp_price = entry * (1 - config.TP_PCT)
            sl_price = entry * (1 + config.SL_PCT)

        log(f"TP price: {tp_price:.8f}")
        log(f"SL price: {sl_price:.8f}")

        # Call the new recovery function
        log("\nCalling verify_and_place_missing_orders...")
        tp_ok, sl_ok = executor.verify_and_place_missing_orders(
            symbol=symbol,
            direction=direction,
            tp_price=tp_price,
            sl_price=sl_price,
            quantity=quantity
        )

        log(f"\n{'='*80}")
        log(f"RESULTS:")
        log(f"  TP Order: {'✓ OK' if tp_ok else '✗ FAILED'}")
        log(f"  SL Order: {'✓ OK' if sl_ok else '✗ FAILED'}")
        log(f"{'='*80}")

        if tp_ok and sl_ok:
            log("\n✅ SUCCESS: Both TP and SL are present or were placed")
        else:
            log(f"\n⚠️  WARNING: Missing orders detected!")
            if not tp_ok:
                log("  - TP order is missing")
            if not sl_ok:
                log("  - SL order is missing")

    except Exception as e:
        log(f"Error: {e}", "error")
        import traceback
        traceback.print_exc()

    finally:
        executor.close()

if __name__ == "__main__":
    main()
