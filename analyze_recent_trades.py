#!/usr/bin/env python3
"""
Analyze recent trades to see actual TP percentages
"""
import sys
sys.path.insert(0, 'src')

from order_executor import OrderExecutor
import time

def main():
    executor = OrderExecutor()

    try:
        # Get list of all symbols with recent activity
        print("\n" + "="*80)
        print("ANALYZING RECENT TRADES (Last 24 hours)")
        print("="*80)

        # Fetch account trades for last 24 hours
        end_time = int(time.time() * 1000)
        start_time = end_time - (24 * 3600 * 1000)  # 24 hours ago

        # Get recent positions
        positions = executor.get_all_open_positions()

        # Also need to check recently closed positions
        # We'll get this from user trades
        params = {
            "startTime": start_time,
            "endTime": end_time,
            "limit": 1000  # Get last 1000 trades
        }
        params = executor._sign_params(params)

        resp = executor.client.get(
            f"https://fapi.binance.com/fapi/v1/userTrades",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        trades = resp.json()

        if not trades:
            print("\n[OK] No trades in last 24 hours")
            return

        print(f"\n[INFO] Found {len(trades)} trades in last 24 hours")
        print("\nAnalyzing closing trades (position reduces to 0)...")

        # Group trades by symbol to find position opens/closes
        from collections import defaultdict
        symbol_trades = defaultdict(list)

        for trade in trades:
            symbol_trades[trade['symbol']].append(trade)

        # Analyze each symbol
        for symbol, symbol_trade_list in symbol_trades.items():
            # Sort by time
            symbol_trade_list.sort(key=lambda x: x['time'])

            print(f"\n{'-'*60}")
            print(f"Symbol: {symbol}")

            position_qty = 0.0
            entry_price = None
            entry_qty = 0.0

            for i, trade in enumerate(symbol_trade_list):
                side = trade['side']
                price = float(trade['price'])
                qty = float(trade['qty'])
                realized_pnl = float(trade['realizedPnl'])
                is_buyer = trade['buyer']

                # Update position
                if side == 'BUY':
                    position_qty += qty
                else:  # SELL
                    position_qty -= qty

                # Track entry
                if abs(position_qty) > abs(entry_qty):
                    entry_price = price
                    entry_qty = position_qty

                # Check if position closed
                if abs(position_qty) < 0.001 and abs(entry_qty) > 0.001:
                    # Position was closed
                    direction = "LONG" if entry_qty > 0 else "SHORT"

                    # Calculate actual TP percentage
                    if direction == "LONG":
                        pct = ((price - entry_price) / entry_price * 100)
                    else:
                        pct = ((entry_price - price) / entry_price * 100)

                    status = "WIN" if realized_pnl > 0 else "LOSS"

                    print(f"  Trade {i+1}:")
                    print(f"    Direction: {direction}")
                    print(f"    Entry: {entry_price:.6f}")
                    print(f"    Exit: {price:.6f}")
                    print(f"    TP%: {pct:+.2f}%")
                    print(f"    Realized PnL: ${realized_pnl:.4f}")
                    print(f"    Status: {status}")

                    if status == "WIN" and abs(pct) < 9.0:
                        print(f"    [ALERT] Position closed with profit BELOW 10% TP!")

                    # Reset for next position
                    entry_price = None
                    entry_qty = 0.0

        print("\n" + "="*80)
        print("DIAGNOSIS:")
        print("="*80)
        print("If you see positions closing below 10% TP, the causes could be:")
        print("1. Old 0.4% TP orders still active (check Binance manually)")
        print("2. Timeout closes (after 54 candles / 2.25 hours)")
        print("3. Break-even protection (after 12 candles if negative)")
        print("4. Manual intervention")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        executor.close()

if __name__ == "__main__":
    main()
