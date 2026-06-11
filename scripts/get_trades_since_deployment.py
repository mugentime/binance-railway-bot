"""
Fetch all trades from Binance API since deployment
"""
import os
import sys
import time
import hmac
import hashlib
import httpx
import urllib.parse
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv()

# Deployment time: June 1, 2026 17:40:42 UTC
DEPLOYMENT_TIME_MS = 1780335642000

BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET')
BINANCE_BASE_URL = 'https://fapi.binance.com'

def sign_params(params):
    """Sign API request parameters"""
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        BINANCE_API_SECRET.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()
    params['signature'] = signature
    return params

def get_all_income():
    """Get all income/PnL records since deployment"""
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
            print(f'Error: {resp.status_code}')
            print(f'Response: {resp.text}')
            resp.raise_for_status()
        return resp.json()

def get_trades_since_deployment():
    """Get all trades/income since deployment using income API"""
    income_records = get_all_income()

    # Filter for REALIZED_PNL records (completed trades)
    realized_pnl_records = [
        r for r in income_records
        if r['incomeType'] in ['REALIZED_PNL', 'COMMISSION']
    ]

    return realized_pnl_records

def main():
    records = get_trades_since_deployment()

    print(f'\n{"="*120}')
    print(f'INCOME RECORDS SINCE DEPLOYMENT (June 1, 2026 17:40:42 UTC)')
    print(f'Total records: {len(records)}')
    print(f'{"="*120}\n')

    if not records:
        print("No income records found since deployment.")
        return

    # Group by symbol
    by_symbol = {}
    for record in records:
        symbol = record['symbol']
        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(record)

    # Print by symbol
    for symbol in sorted(by_symbol.keys()):
        symbol_records = by_symbol[symbol]
        print(f'\n{symbol} ({len(symbol_records)} records)')
        print(f'{"-"*120}')

        total_income = 0
        for record in symbol_records:
            dt = datetime.fromtimestamp(record['time']/1000, tz=timezone.utc)
            income_type = record['incomeType']
            income = float(record['income'])
            asset = record['asset']
            info = record.get('info', '')

            total_income += income

            print(f'  {dt.strftime("%Y-%m-%d %H:%M:%S")} UTC | '
                  f'{income_type:15} | '
                  f'Income: ${income:10.4f} {asset} | '
                  f'Info: {info}')

        print(f'  {"":20} Total: ${total_income:10.4f}')

    # Summary
    print(f'\n{"="*120}')
    print(f'SUMMARY')
    print(f'{"="*120}')
    pnl_records = [r for r in records if r['incomeType'] == 'REALIZED_PNL']
    commission_records = [r for r in records if r['incomeType'] == 'COMMISSION']

    total_realized_pnl = sum(float(r['income']) for r in pnl_records)
    total_commission = sum(float(r['income']) for r in commission_records)
    net_pnl = total_realized_pnl + total_commission

    print(f'Realized PnL: ${total_realized_pnl:.4f} ({len(pnl_records)} records)')
    print(f'Commission: ${total_commission:.4f} ({len(commission_records)} records)')
    print(f'Net PnL: ${net_pnl:.4f}')
    print(f'{"="*120}\n')

if __name__ == '__main__':
    main()
