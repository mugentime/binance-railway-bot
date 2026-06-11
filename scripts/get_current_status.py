#!/usr/bin/env python3
"""Get current BNB price and calculate balance update."""

import requests
from datetime import datetime

def get_bnb_price():
    """Get current BNB/USDT price."""
    url = 'https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT'
    resp = requests.get(url, timeout=10)
    return float(resp.json()['price'])

def main():
    # Last checkpoint: Jun 4, 17:00 UTC
    last_balance_usd = 46.61
    last_balance_bnb = 0.07747
    last_bnb_price = 601.73

    print("=" * 80)
    print("BALANCE UPDATE - JUNE 5, 2026")
    print("=" * 80)
    print()

    print("LAST CHECKPOINT (Jun 4, 17:00 UTC):")
    print(f"  Balance: ${last_balance_usd:.2f} = {last_balance_bnb:.5f} BNB @ ${last_bnb_price:.2f}/BNB")
    print()

    # New completed positions since Jun 4, 17:00 UTC
    print("NEW COMPLETED POSITIONS:")
    print("-" * 80)
    positions = [
        {'symbol': 'STABLEUSDT', 'exit_time': '2026-06-04 18:32:32 UTC', 'pnl': -0.1861, 'result': 'LOSS'},
        {'symbol': 'STABLEUSDT', 'exit_time': '2026-06-04 23:12:32 UTC', 'pnl': 1.1726, 'result': 'WIN'},
        {'symbol': 'STOUSDT', 'exit_time': '2026-06-05 00:47:32 UTC', 'pnl': -0.8105, 'result': 'LOSS'},
        {'symbol': 'UAIUSDT', 'exit_time': '2026-06-05 01:11:41 UTC', 'pnl': 3.5787, 'result': 'WIN'},
        {'symbol': 'UAIUSDT', 'exit_time': '2026-06-05 01:17:53 UTC', 'pnl': -1.0032, 'result': 'LOSS'},
    ]

    total_realized_pnl = 0
    wins = 0
    losses = 0

    for i, pos in enumerate(positions, 1):
        print(f"{i}. {pos['symbol']:12} | Exit: {pos['exit_time']} | P&L: ${pos['pnl']:+8.4f} | {pos['result']}")
        total_realized_pnl += pos['pnl']
        if pos['result'] == 'WIN':
            wins += 1
        else:
            losses += 1

    print("-" * 80)
    print(f"Total: {len(positions)} positions | {wins} wins ({wins/len(positions)*100:.1f}%), {losses} losses ({losses/len(positions)*100:.1f}%)")
    print(f"Total Realized P&L: ${total_realized_pnl:+.4f}")
    print()

    # Current BNB price
    current_bnb_price = get_bnb_price()
    print(f"CURRENT BNB PRICE: ${current_bnb_price:.2f}")
    bnb_price_change = ((current_bnb_price - last_bnb_price) / last_bnb_price) * 100
    print(f"BNB Price Change: {bnb_price_change:+.2f}% (from ${last_bnb_price:.2f})")
    print()

    # Calculate BNB P&L (approximate, using average BNB price)
    avg_bnb_price = (last_bnb_price + current_bnb_price) / 2
    realized_pnl_bnb = total_realized_pnl / avg_bnb_price

    # Updated balance
    new_balance_bnb = last_balance_bnb + realized_pnl_bnb
    new_balance_usd = new_balance_bnb * current_bnb_price

    print("CALCULATED NEW BALANCE (excluding unrealized P&L):")
    print(f"  Balance: ${new_balance_usd:.2f} = {new_balance_bnb:.5f} BNB @ ${current_bnb_price:.2f}/BNB")
    print()

    # Current unrealized position
    print("ACTIVE POSITION (from Railway logs):")
    print("  CHIPUSDT LONG | Level 6 | Unrealized P&L: +$1.85 (41 candles held)")
    print()

    # Total including unrealized
    unrealized_pnl = 1.85
    total_balance_usd = new_balance_usd + unrealized_pnl

    print("=" * 80)
    print("CURRENT TOTAL VALUE (with unrealized P&L):")
    print(f"  ${total_balance_usd:.2f} = {new_balance_bnb:.5f} BNB + ${unrealized_pnl:.2f} unrealized")
    print()

    # Changes since last checkpoint
    usd_change = total_balance_usd - last_balance_usd
    usd_change_pct = (usd_change / last_balance_usd) * 100
    bnb_change = new_balance_bnb - last_balance_bnb
    bnb_change_pct = (bnb_change / last_balance_bnb) * 100

    print("CHANGES SINCE LAST CHECKPOINT (Jun 4, 17:00 UTC):")
    print(f"  USD Change: ${usd_change:+.2f} ({usd_change_pct:+.2f}%)")
    print(f"  BNB Change: {bnb_change:+.5f} BNB ({bnb_change_pct:+.2f}%)")
    print(f"  Realized Trading P&L: ${total_realized_pnl:+.4f}")
    print(f"  Unrealized P&L: ${unrealized_pnl:+.2f}")
    print(f"  BNB Price Impact: {bnb_price_change:+.2f}%")
    print("=" * 80)

if __name__ == '__main__':
    main()
