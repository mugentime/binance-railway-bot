"""Fetch recent trade PnL from Binance to verify chain_pnl_history"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
import json
from datetime import datetime, timedelta

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("BINANCE INCOME HISTORY (Recent Realized PnL)")
    print("="*80 + "\n")

    # Fetch income history for last 7 days
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

    params = {
        "incomeType": "REALIZED_PNL",  # Only realized PnL from closed positions
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
    income_records = resp.json()

    # Load current chain PnL history
    with open('state.json', 'r') as f:
        state = json.load(f)
        chain_pnl = state.get('chain_pnl_history', [])
        level = state.get('level', 0)

    print(f"Current Level: {level}")
    print(f"Chain PnL History: {chain_pnl}")
    print(f"Cumulative Chain PnL: ${sum(chain_pnl):.4f}")
    print(f"\nNumber of trades in chain: {len(chain_pnl)}")
    print("\n" + "-"*80)
    print("Recent Binance Realized PnL (last 24 hours):")
    print("-"*80)

    if not income_records:
        print("No income records found in last 24 hours")
    else:
        total_realized = 0
        num_to_show = max(20, len(chain_pnl))  # Show at least as many as in chain
        for i, record in enumerate(reversed(income_records[-num_to_show:])):
            income = float(record['income'])
            symbol = record['symbol']
            timestamp = datetime.fromtimestamp(record['time'] / 1000)
            total_realized += income

            print(f"{i+1}. {timestamp.strftime('%H:%M:%S')} | {symbol:12s} | PnL: ${income:+.4f}")

        print("\n" + "-"*80)
        print(f"Total Realized PnL (last {num_to_show} trades): ${total_realized:.4f}")
        print(f"Chain PnL History Sum ({len(chain_pnl)} trades):  ${sum(chain_pnl):.4f}")

        # Compare
        if abs(total_realized - sum(chain_pnl)) < 0.01:
            print("[OK] Chain PnL matches Binance records!")
        else:
            print("[WARNING] Chain PnL doesn't match Binance exactly")
            print(f"   Difference: ${abs(total_realized - sum(chain_pnl)):.4f}")
            print(f"\n   This could mean:")
            print(f"   - Chain has more trades than shown (Binance limit=100)")
            print(f"   - Need to check full income history")

    print("\n" + "="*80)
    print("Current Position:")
    print("="*80)

    # Get current open positions
    params = {"timestamp": int(datetime.now().timestamp() * 1000)}
    params = executor._sign_params(params)
    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v2/positionRisk",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    positions = resp.json()

    open_positions = [p for p in positions if float(p['positionAmt']) != 0]

    if open_positions:
        for pos in open_positions:
            symbol = pos['symbol']
            entry = float(pos['entryPrice'])
            mark = float(pos['markPrice'])
            qty = float(pos['positionAmt'])
            unrealized = float(pos['unRealizedProfit'])

            print(f"\nSymbol: {symbol}")
            print(f"Entry Price: {entry}")
            print(f"Mark Price:  {mark}")
            print(f"Quantity:    {qty}")
            print(f"Unrealized PnL: ${unrealized:.4f}")
    else:
        print("\nNo open positions")

    print("\n" + "="*80)

finally:
    executor.close()
