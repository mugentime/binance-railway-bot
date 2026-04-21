"""Check all SIRENUSDT fills around the time of the trade"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
from datetime import datetime, timedelta

executor = OrderExecutor()

try:
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(hours=12)).timestamp() * 1000)

    params = {
        'symbol': 'SIRENUSDT',
        'incomeType': 'REALIZED_PNL',
        'startTime': start_time,
        'endTime': end_time,
        'limit': 100
    }
    params = executor._sign_params(params)

    resp = executor.client.get(
        f'{config.BINANCE_BASE_URL}/fapi/v1/income',
        params=params,
        headers=executor._headers()
    )
    records = resp.json()

    print('\nSIRENUSDT Income Records (last 12 hours):')
    print('='*70)
    total = 0
    for r in reversed(records):
        dt = datetime.fromtimestamp(r['time']/1000)
        pnl = float(r['income'])
        total += pnl
        print(f"{dt.strftime('%Y-%m-%d %H:%M:%S')} | "
              f"PnL: ${pnl:+.4f} | "
              f"TranID: {r['tranId']}")

    print('='*70)
    print(f"Total: ${total:.4f}")
    print(f"\nBot recorded at 01:10:04: PnL = -$0.05")
    print(f"Binance shows single trade at 18:07:42: PnL = -$0.4620")
    print(f"MISMATCH: ${abs(total - (-0.05)):.4f}")

finally:
    executor.close()
