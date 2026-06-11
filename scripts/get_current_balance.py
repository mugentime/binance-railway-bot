#!/usr/bin/env python3
"""Get current Binance Futures account balance."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor

def main():
    executor = OrderExecutor()
    try:
        # Get account information
        params = {}
        params = executor._sign_params(params)

        resp = executor.client.get(
            'https://fapi.binance.com/fapi/v2/account',
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        account = resp.json()

        # Get total wallet balance
        total_balance = float(account['totalWalletBalance'])
        total_unrealized_pnl = float(account['totalUnrealizedProfit'])
        total_margin_balance = float(account['totalMarginBalance'])
        available_balance = float(account['availableBalance'])

        print('=' * 80)
        print('CURRENT BINANCE FUTURES ACCOUNT STATUS')
        print('=' * 80)
        print(f'Total Wallet Balance: ${total_balance:.2f}')
        print(f'Unrealized P&L: ${total_unrealized_pnl:.2f}')
        print(f'Total Margin Balance: ${total_margin_balance:.2f} (wallet + unrealized)')
        print(f'Available Balance: ${available_balance:.2f}')
        print('=' * 80)

        # Show open positions if any
        positions = [p for p in account.get('positions', []) if float(p.get('positionAmt', 0)) != 0]
        if positions:
            print('\nOPEN POSITIONS:')
            print('-' * 80)
            for pos in positions:
                symbol = pos['symbol']
                amt = float(pos['positionAmt'])
                entry_price = float(pos['entryPrice'])
                mark_price = float(pos['markPrice'])
                unrealized = float(pos['unRealizedProfit'])
                side = 'LONG' if amt > 0 else 'SHORT'
                print(f'{symbol:15} {side:6} | Qty: {abs(amt):12.4f} | Entry: ${entry_price:10.4f} | Mark: ${mark_price:10.4f} | Unrealized: ${unrealized:+8.2f}')
            print('-' * 80)
        else:
            print('\nNo open positions')

    finally:
        executor.close()

if __name__ == '__main__':
    main()
