"""
Get all trades since CHAIN_6 started
"""
import os
import sys
import time
import hmac
import hashlib
import httpx
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv()

# CHAIN_6 started: June 2, 2026 13:03 UTC
CHAIN_6_START_MS = 1780411380000

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

def get_all_income():
    """Get income records since CHAIN_6"""
    params = {
        'timestamp': int(time.time() * 1000),
        'recvWindow': 20000,
        'startTime': CHAIN_6_START_MS,
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
            print(f'Error: {resp.status_code}')
            print(f'Response: {resp.text}')
            return []
        return resp.json()

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
            return []
        return resp.json()

def main():
    income_records = get_all_income()

    print(f'\n{"="*120}')
    print(f'ALL POSITIONS SINCE CHAIN_6 (June 2, 2026 13:03 UTC)')
    print(f'Total income records: {len(income_records)}')
    print(f'{"="*120}\n')

    # Get unique symbols
    symbols = set(r['symbol'] for r in income_records if r['incomeType'] in ['REALIZED_PNL', 'COMMISSION'])

    all_positions = []

    for symbol in sorted(symbols):
        trades = get_trades_for_symbol(symbol)
        trades = [t for t in trades if t['time'] >= CHAIN_6_START_MS]

        if not trades:
            continue

        # Group into positions
        positions = []
        current_position = None

        for trade in trades:
            is_buyer = trade['buyer']
            qty = float(trade['qty'])
            price = float(trade['price'])
            time_ms = trade['time']
            realized_pnl = float(trade['realizedPnl'])

            if realized_pnl == 0:  # Entry
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
                        'realized_pnl': 0
                    }
            else:  # Exit
                if current_position:
                    current_position['exit_time'] = time_ms
                    current_position['exit_price'] = price
                    current_position['realized_pnl'] += realized_pnl

                    if abs(realized_pnl) > 0.0001:
                        positions.append(current_position)
                        all_positions.append(current_position)
                        current_position = None

        # Add active position if exists
        if current_position:
            all_positions.append(current_position)

    # Sort by entry time
    all_positions.sort(key=lambda x: x['entry_time'])

    # Print positions
    position_num = 13  # Starting from #13 (BIOUSDT in CHAIN_6)

    for pos in all_positions:
        position_num += 1
        entry_dt = datetime.fromtimestamp(pos['entry_time']/1000, tz=timezone.utc)

        print(f'Position #{position_num}: {pos["symbol"]}')
        print(f'  Entry: {entry_dt.strftime("%Y-%m-%d %H:%M:%S")} UTC')
        print(f'  Direction: {pos["direction"]}')
        print(f'  Entry Price: ${pos["entry_price"]:.6f}')
        print(f'  Entry Value: ${pos["entry_value_usd"]:.2f}')

        if pos['exit_time']:
            exit_dt = datetime.fromtimestamp(pos['exit_time']/1000, tz=timezone.utc)
            duration = (pos['exit_time'] - pos['entry_time']) / 1000 / 60
            status = "WIN" if pos['realized_pnl'] > 0 else "LOSS"

            print(f'  Exit: {exit_dt.strftime("%Y-%m-%d %H:%M:%S")} UTC')
            print(f'  Exit Price: ${pos["exit_price"]:.6f}')
            print(f'  Duration: {duration:.1f} min')
            print(f'  Realized PnL: ${pos["realized_pnl"]:.4f}')
            print(f'  Status: {status}')
        else:
            print(f'  Status: ACTIVE (still open)')

        print()

    # Summary
    print(f'{"="*120}')
    print(f'SUMMARY SINCE CHAIN_6')
    print(f'{"="*120}')

    closed = [p for p in all_positions if p['exit_time'] is not None]
    active = [p for p in all_positions if p['exit_time'] is None]

    total_pnl = sum(p['realized_pnl'] for p in closed)
    wins = [p for p in closed if p['realized_pnl'] > 0]
    losses = [p for p in closed if p['realized_pnl'] < 0]

    print(f'Total Positions: {len(all_positions)}')
    print(f'Closed: {len(closed)} (Wins: {len(wins)}, Losses: {len(losses)})')
    print(f'Active: {len(active)}')
    print(f'Win Rate: {len(wins)/len(closed)*100:.1f}%' if closed else 'Win Rate: N/A')
    print(f'Net Realized PnL: ${total_pnl:.4f}')
    print(f'{"="*120}\n')

if __name__ == '__main__':
    main()
