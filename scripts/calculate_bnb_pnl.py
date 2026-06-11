"""
Calculate exact BNB P&L for all positions
"""
import requests
import time
from datetime import datetime, timezone

def get_bnb_price_at_time(timestamp_ms):
    """Get BNB/USDT price at specific timestamp"""
    url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': 'BNBUSDT',
        'interval': '1m',
        'startTime': timestamp_ms,
        'limit': 1
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data:
            return float(data[0][4])  # Close price
    except:
        pass
    return None

# All 23 positions from Binance order history
positions = [
    {'symbol': 'IRYSUSDT', 'entry_time': '2026-06-01 22:12:35', 'exit_time': '2026-06-02 00:30:02', 'pnl_usd': 3.37},
    {'symbol': 'UAIUSDT', 'entry_time': '2026-06-02 00:32:35', 'exit_time': '2026-06-02 02:05:02', 'pnl_usd': -0.39},
    {'symbol': 'BASEDUSDT', 'entry_time': '2026-06-02 02:07:36', 'exit_time': '2026-06-02 02:12:32', 'pnl_usd': -0.48},
    {'symbol': 'INXUSDT', 'entry_time': '2026-06-02 02:15:06', 'exit_time': '2026-06-02 04:32:32', 'pnl_usd': 0.28},
    {'symbol': 'BIOUSDT', 'entry_time': '2026-06-02 04:35:05', 'exit_time': '2026-06-02 04:40:02', 'pnl_usd': -0.23},
    {'symbol': 'GENIUSUSDT', 'entry_time': '2026-06-02 04:42:35', 'exit_time': '2026-06-02 07:00:09', 'pnl_usd': 0.50},
    {'symbol': 'BIOUSDT', 'entry_time': '2026-06-02 07:02:35', 'exit_time': '2026-06-02 08:35:02', 'pnl_usd': -0.20},
    {'symbol': 'SPKUSDT', 'entry_time': '2026-06-02 08:37:35', 'exit_time': '2026-06-02 10:10:02', 'pnl_usd': -1.22},
    {'symbol': 'EDGEUSDT', 'entry_time': '2026-06-02 10:12:35', 'exit_time': '2026-06-02 12:07:32', 'pnl_usd': -0.19},
    {'symbol': 'RIVERUSDT', 'entry_time': '2026-06-02 12:10:06', 'exit_time': '2026-06-02 14:27:32', 'pnl_usd': 0.06},
    {'symbol': 'EDGEUSDT', 'entry_time': '2026-06-02 14:35:05', 'exit_time': '2026-06-02 16:52:32', 'pnl_usd': 0.99},
    {'symbol': 'STOUSDT', 'entry_time': '2026-06-02 16:55:05', 'exit_time': '2026-06-02 19:12:32', 'pnl_usd': 0.14},
    {'symbol': 'CUSDT', 'entry_time': '2026-06-02 19:15:05', 'exit_time': '2026-06-02 20:47:32', 'pnl_usd': -0.16},
    {'symbol': 'UAIUSDT', 'entry_time': '2026-06-02 20:52:35', 'exit_time': '2026-06-02 22:25:02', 'pnl_usd': -1.24},
    {'symbol': 'UBUSDT', 'entry_time': '2026-06-02 22:30:06', 'exit_time': '2026-06-03 00:32:32', 'pnl_usd': -0.12},
    {'symbol': 'CUSDT', 'entry_time': '2026-06-03 00:35:05', 'exit_time': '2026-06-03 01:33:45', 'pnl_usd': 8.38},
    {'symbol': 'NOMUSDT', 'entry_time': '2026-06-03 01:35:06', 'exit_time': '2026-06-03 03:40:02', 'pnl_usd': -0.11},
    {'symbol': 'SIRENUSDT', 'entry_time': '2026-06-03 03:42:35', 'exit_time': '2026-06-03 05:15:02', 'pnl_usd': -0.06},
    {'symbol': 'PRLUSDT', 'entry_time': '2026-06-03 05:17:35', 'exit_time': '2026-06-03 05:22:32', 'pnl_usd': -0.30},
    {'symbol': 'STABLEUSDT', 'entry_time': '2026-06-03 05:25:05', 'exit_time': '2026-06-03 05:30:02', 'pnl_usd': -0.11},
    {'symbol': 'NOMUSDT', 'entry_time': '2026-06-03 05:32:35', 'exit_time': '2026-06-03 05:37:32', 'pnl_usd': -0.17},
    {'symbol': 'BASEDUSDT', 'entry_time': '2026-06-03 05:40:07', 'exit_time': '2026-06-03 07:12:32', 'pnl_usd': -0.62},
    {'symbol': 'RIVERUSDT', 'entry_time': '2026-06-03 07:15:14', 'exit_time': '2026-06-03 08:55:04', 'pnl_usd': -0.13},
]

def parse_time(time_str):
    """Convert time string to timestamp"""
    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)

def main():
    print('=' * 100)
    print('BNB P&L CALCULATION - EXACT ANALYSIS')
    print('=' * 100)
    print()

    total_bnb_pnl = 0
    successful_calcs = 0

    for i, pos in enumerate(positions, 1):
        exit_ts = parse_time(pos['exit_time'])
        bnb_price = get_bnb_price_at_time(exit_ts)

        if bnb_price:
            pnl_bnb = pos['pnl_usd'] / bnb_price
            total_bnb_pnl += pnl_bnb
            successful_calcs += 1

            status = 'WIN' if pos['pnl_usd'] > 0 else 'LOSS'
            print(f'{i:2}. {pos["symbol"]:12} | USD: {pos["pnl_usd"]:+7.2f} | BNB: {pnl_bnb:+.8f} | @${bnb_price:.2f} | {status}')
            time.sleep(0.15)  # Rate limit

    print()
    print('=' * 100)
    print(f'TOTAL BNB P&L: {total_bnb_pnl:+.8f} BNB')
    print(f'Positions calculated: {successful_calcs}/23')
    print('=' * 100)
    print()

    # Calculate final BNB balance
    starting_bnb = 45.81 / 696.15  # Starting BNB amount
    ending_bnb = starting_bnb + total_bnb_pnl

    print('BALANCE COMPARISON:')
    print(f'Starting BNB: {starting_bnb:.8f} BNB (worth $45.81 @ $696.15)')
    print(f'Trading P&L:  {total_bnb_pnl:+.8f} BNB')
    print(f'Ending BNB:   {ending_bnb:.8f} BNB')
    print()
    print(f'At Jun 3 BNB price ($627.50):')
    print(f'  Ending value: ${ending_bnb * 627.50:.2f}')
    print()
    print(f'Actual balance shown: $42.96')
    print(f'Difference: ${42.96 - (ending_bnb * 627.50):.2f}')
    print('=' * 100)

if __name__ == '__main__':
    main()
