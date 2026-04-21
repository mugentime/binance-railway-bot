"""Check BIOUSDT trade details"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
from datetime import datetime, timedelta

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("BIOUSDT TRADE VERIFICATION")
    print("="*80 + "\n")

    # Get recent trades
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(hours=6)).timestamp() * 1000)

    params = {
        'symbol': 'BIOUSDT',
        'startTime': start_time,
        'endTime': end_time,
        'limit': 100
    }
    params = executor._sign_params(params)

    resp = executor.client.get(
        f'{config.BINANCE_BASE_URL}/fapi/v1/userTrades',
        params=params,
        headers=executor._headers()
    )
    trades = resp.json()

    print(f'Found {len(trades)} BIOUSDT fills:\n')

    for trade in trades:
        dt = datetime.fromtimestamp(trade['time']/1000)
        side = trade['side']
        qty = float(trade['qty'])
        price = float(trade['price'])
        quote = float(trade['quoteQty'])
        pnl = float(trade['realizedPnl'])

        print(f"{dt.strftime('%H:%M:%S')} | "
              f"{side:4s} | "
              f"Qty: {qty:7.1f} | "
              f"Price: {price:.4f} | "
              f"Quote: ${quote:7.2f} | "
              f"PnL: ${pnl:+.4f}")

    # Get income records
    params2 = {
        'symbol': 'BIOUSDT',
        'incomeType': 'REALIZED_PNL',
        'startTime': start_time,
        'endTime': end_time,
        'limit': 100
    }
    params2 = executor._sign_params(params2)

    resp2 = executor.client.get(
        f'{config.BINANCE_BASE_URL}/fapi/v1/income',
        params=params2,
        headers=executor._headers()
    )
    income = resp2.json()

    print("\n" + "="*80)
    print("BIOUSDT INCOME (Realized PnL):")
    print("="*80 + "\n")

    total_pnl = 0
    for rec in reversed(income):
        dt = datetime.fromtimestamp(rec['time']/1000)
        pnl = float(rec['income'])
        total_pnl += pnl
        print(f"{dt.strftime('%H:%M:%S')} | PnL: ${pnl:+.4f}")

    print(f"\nTotal BIOUSDT PnL: ${total_pnl:.4f}")

    print("\n" + "="*80)
    print("COMPARISON:")
    print("="*80)
    print(f"Bot logged (03:32:34): LOSS @ 0.0331 | PnL: -$0.79")
    print(f"Binance actual PnL:     ${total_pnl:.4f}")

    if abs(total_pnl - (-0.79)) < 0.01:
        print("\n[OK] Bot PnL matches Binance!")
    else:
        print(f"\n[MISMATCH] Difference: ${abs(total_pnl - (-0.79)):.4f}")

finally:
    executor.close()
