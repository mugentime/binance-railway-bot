"""
Fetch detailed trade information from Binance API
"""
import os
import sys
import time
import hmac
import hashlib
import httpx
import urllib.parse
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv()

DEPLOYMENT_TIME_MS = 1780335642000
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET')
BINANCE_BASE_URL = 'https://fapi.binance.com'

def sign_params(params):
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        BINANCE_API_SECRET.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()
    params['signature'] = signature
    return params

def get_trades_for_symbol(symbol):
    """Get all trades for a specific symbol"""
    params = {
        'symbol': symbol,
        'timestamp': int(time.time() * 1000),
        'recvWindow': 20000,
        'limit': 1000
    }
    params = sign_params(params)
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}

    with httpx.Client() as client:
        resp = client.get(
            f'{BINANCE_BASE_URL}/fapi/v1/userTrades',
            params=params,
            headers=headers,
            timeout=30.0
        )
        if resp.status_code != 200:
            print(f'Error getting trades for {symbol}: {resp.text}')
            return []
        return resp.json()

def get_all_income():
    """Get income records to find which symbols traded"""
    params = {
        'timestamp': int(time.time() * 1000),
        'recvWindow': 20000,
        'startTime': DEPLOYMENT_TIME_MS,
        'limit': 1000
    }
    params = sign_params(params)
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}

    with httpx.Client() as client:
        resp = client.get(
            f'{BINANCE_BASE_URL}/fapi/v1/income',
            params=params,
            headers=headers,
            timeout=30.0
        )
        if resp.status_code != 200:
            return []
        return resp.json()

def main():
    # Get income records to find symbols
    income_records = get_all_income()
    symbols = set(r['symbol'] for r in income_records)

    print(f'\n{"="*140}')
    print(f'DETAILED TRADES SINCE DEPLOYMENT (June 1, 2026 17:40:42 UTC)')
    print(f'Symbols traded: {len(symbols)}')
    print(f'{"="*140}\n')

    all_positions = []

    for symbol in sorted(symbols):
        # Get all trade fills for this symbol
        trades = get_trades_for_symbol(symbol)

        # Filter trades since deployment
        trades = [t for t in trades if t['time'] >= DEPLOYMENT_TIME_MS]

        if not trades:
            continue

        # Group trades into positions (entry + exit fills)
        positions = []
        current_position = None

        for trade in trades:
            is_buyer = trade['buyer']
            qty = float(trade['qty'])
            price = float(trade['price'])
            time_ms = trade['time']
            realized_pnl = float(trade['realizedPnl'])

            # Determine if this is entry or exit
            if realized_pnl == 0:
                # Entry trade
                if current_position is None:
                    current_position = {
                        'symbol': symbol,
                        'entry_time': time_ms,
                        'entry_price': price,
                        'entry_qty': qty,
                        'direction': 'LONG' if is_buyer else 'SHORT',
                        'entry_value_usd': price * qty,
                        'exit_time': None,
                        'exit_price': None,
                        'realized_pnl': 0,
                        'fills': [trade]
                    }
                else:
                    # Add to existing position
                    current_position['fills'].append(trade)
            else:
                # Exit trade
                if current_position:
                    current_position['exit_time'] = time_ms
                    current_position['exit_price'] = price
                    current_position['realized_pnl'] += realized_pnl
                    current_position['fills'].append(trade)

                    # Check if position fully closed (remaining position is 0)
                    if abs(realized_pnl) > 0.0001:  # Has realized PnL, position closed
                        positions.append(current_position)
                        all_positions.append(current_position)
                        current_position = None

        # Print this symbol's positions
        if positions:
            print(f'\n{symbol} - {len(positions)} position(s)')
            print(f'{"-"*140}')

            for i, pos in enumerate(positions, 1):
                entry_dt = datetime.fromtimestamp(pos['entry_time']/1000, tz=timezone.utc)
                exit_dt = datetime.fromtimestamp(pos['exit_time']/1000, tz=timezone.utc) if pos['exit_time'] else None
                duration = (pos['exit_time'] - pos['entry_time']) / 1000 / 60 if pos['exit_time'] else 0

                print(f'  Position #{i}')
                print(f'    Entry:  {entry_dt.strftime("%Y-%m-%d %H:%M:%S")} UTC | '
                      f'{pos["direction"]:5} | '
                      f'Price: ${pos["entry_price"]:.6f} | '
                      f'Qty: {pos["entry_qty"]:.1f} | '
                      f'Value: ${pos["entry_value_usd"]:.2f}')
                if exit_dt:
                    print(f'    Exit:   {exit_dt.strftime("%Y-%m-%d %H:%M:%S")} UTC | '
                          f'Price: ${pos["exit_price"]:.6f} | '
                          f'PnL: ${pos["realized_pnl"]:.4f} | '
                          f'Duration: {duration:.1f} min')
                print()

    # Summary
    print(f'\n{"="*140}')
    print(f'SUMMARY')
    print(f'{"="*140}')

    total_entry_value = sum(p['entry_value_usd'] for p in all_positions)
    total_pnl = sum(p['realized_pnl'] for p in all_positions)
    wins = [p for p in all_positions if p['realized_pnl'] > 0]
    losses = [p for p in all_positions if p['realized_pnl'] < 0]

    print(f'Total Positions: {len(all_positions)}')
    print(f'Wins: {len(wins)} ({len(wins)/len(all_positions)*100:.1f}%)')
    print(f'Losses: {len(losses)} ({len(losses)/len(all_positions)*100:.1f}%)')
    print(f'Total Entry Value: ${total_entry_value:.2f}')
    print(f'Total Realized PnL: ${total_pnl:.4f}')
    print(f'{"="*140}\n')

if __name__ == '__main__':
    main()
