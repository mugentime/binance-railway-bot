"""Check actual SIRENUSDT orders/fills from Binance"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
from datetime import datetime, timedelta

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("SIRENUSDT ORDER HISTORY")
    print("="*80 + "\n")

    # Get recent trades for SIRENUSDT
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(hours=12)).timestamp() * 1000)

    params = {
        'symbol': 'SIRENUSDT',
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
    resp.raise_for_status()
    trades = resp.json()

    if not trades:
        print("No SIRENUSDT trades found in last 12 hours")
    else:
        print(f"Found {len(trades)} SIRENUSDT fills:\n")

        total_qty = 0
        total_quote = 0
        total_realized_pnl = 0

        for trade in trades:
            dt = datetime.fromtimestamp(trade['time']/1000)
            qty = float(trade['qty'])
            price = float(trade['price'])
            quote_qty = float(trade['quoteQty'])
            side = trade['side']
            realized_pnl = float(trade['realizedPnl'])
            commission = float(trade['commission'])

            total_qty += abs(qty) if side == 'SELL' else -abs(qty)
            total_quote += quote_qty
            total_realized_pnl += realized_pnl

            print(f"{dt.strftime('%H:%M:%S')} | "
                  f"{side:4s} | "
                  f"Qty: {qty:8.2f} | "
                  f"Price: {price:.4f} | "
                  f"Quote: ${quote_qty:7.2f} | "
                  f"PnL: ${realized_pnl:+.4f} | "
                  f"Fee: ${commission:.4f}")

        print("\n" + "-"*80)
        print(f"Total Realized PnL: ${total_realized_pnl:.4f}")
        print(f"Total Quote (USD value): ${total_quote:.2f}")

        print("\n" + "="*80)
        print("COMPARISON:")
        print("="*80)
        print(f"Bot entered: Size=$14.33, Qty=6.0")
        print(f"Binance shows: Total fills quote=${total_quote:.2f}")
        print(f"\nBot calculated PnL: -$0.05")
        print(f"Binance actual PnL:  ${total_realized_pnl:.4f}")
        print(f"DIFFERENCE: ${abs(total_realized_pnl - (-0.05)):.4f}")

finally:
    executor.close()
