"""Check SIRENUSDT actual PnL from Binance"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
from datetime import datetime, timedelta

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("SIRENUSDT INCOME HISTORY FROM BINANCE")
    print("="*80 + "\n")

    # Fetch income for last 7 days
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

    params = {
        "symbol": "SIRENUSDT",
        "incomeType": "REALIZED_PNL",
        "startTime": start_time,
        "endTime": end_time,
        "limit": 100
    }
    params = executor._sign_params(params)

    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/income",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    records = resp.json()

    print(f"Found {len(records)} SIRENUSDT income records:\n")

    total = 0
    for record in reversed(records):
        income = float(record['income'])
        timestamp = datetime.fromtimestamp(record['time'] / 1000)
        total += income

        print(f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')} | "
              f"PnL: ${income:+.4f} | "
              f"Asset: {record['asset']}")

    print(f"\n" + "="*80)
    print(f"Total SIRENUSDT Realized PnL (last 7 days): ${total:.4f}")
    print("="*80)

    # Show most recent
    if records:
        latest = records[-1]
        latest_time = datetime.fromtimestamp(latest['time'] / 1000)
        latest_pnl = float(latest['income'])

        print(f"\nMost Recent SIRENUSDT Trade:")
        print(f"  Time: {latest_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  PnL:  ${latest_pnl:.4f}")

        # Compare with bot log
        print(f"\nBot Log Shows (01:10:04 on 2026-04-17):")
        print(f"  SIRENUSDT SHORT @ 2.0716 | PnL: $-0.05")

        if abs(latest_pnl - (-0.05)) > 0.01:
            print(f"\n[MISMATCH!] Binance: ${latest_pnl:.4f} vs Bot: $-0.05")
            print(f"Difference: ${abs(latest_pnl - (-0.05)):.4f}")

finally:
    executor.close()
