"""Analyze chain PnL by grouping Binance fills into trades"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
import json
from datetime import datetime, timedelta
from collections import defaultdict

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("CHAIN PNL ANALYSIS - Grouped by Trade")
    print("="*80 + "\n")

    # Load chain PnL history from state
    with open('state.json', 'r') as f:
        state = json.load(f)
        chain_pnl = state.get('chain_pnl_history', [])
        level = state.get('level', 0)

    print(f"Bot State:")
    print(f"  Current Level: {level}")
    print(f"  Trades in chain: {len(chain_pnl)}")
    print(f"  Chain PnL values: {[f'${x:.2f}' for x in chain_pnl]}")
    print(f"  Cumulative: ${sum(chain_pnl):.4f}")

    # Fetch Binance income history
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=2)).timestamp() * 1000)  # 2 days

    params = {
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
    income_records = resp.json()

    print(f"\n" + "="*80)
    print(f"Binance Income Records (last 2 days): {len(income_records)} fills")
    print("="*80 + "\n")

    # Group fills by symbol and time window (same trade closes within 1 minute)
    trades = []
    current_trade = None

    for record in reversed(income_records):
        income = float(record['income'])
        symbol = record['symbol']
        timestamp = record['time'] / 1000

        # Group fills within 1 minute window and same symbol as one trade
        if current_trade is None or \
           symbol != current_trade['symbol'] or \
           abs(timestamp - current_trade['timestamp']) > 60:
            # New trade
            if current_trade:
                trades.append(current_trade)
            current_trade = {
                'symbol': symbol,
                'timestamp': timestamp,
                'pnl': income,
                'fills': 1
            }
        else:
            # Same trade, accumulate PnL
            current_trade['pnl'] += income
            current_trade['fills'] += 1

    if current_trade:
        trades.append(current_trade)

    # Show grouped trades
    print("Grouped Trades (Binance fills combined):")
    print("-"*80)

    total_binance_pnl = 0
    for i, trade in enumerate(trades[-20:]):  # Last 20 trades
        dt = datetime.fromtimestamp(trade['timestamp'])
        pnl = trade['pnl']
        total_binance_pnl += pnl
        fills = trade['fills']

        status = "WIN" if pnl > 0 else "LOSS"
        print(f"{i+1:2d}. {dt.strftime('%m-%d %H:%M')} | {trade['symbol']:12s} | "
              f"{status:4s} | ${pnl:+7.4f} | ({fills} fills)")

    print("\n" + "="*80)
    print("COMPARISON:")
    print("="*80)
    print(f"Binance Total (last {len(trades[-20:])} trades): ${total_binance_pnl:.4f}")
    print(f"Bot Chain PnL ({len(chain_pnl)} trades):        ${sum(chain_pnl):.4f}")
    print(f"Difference:                              ${abs(total_binance_pnl - sum(chain_pnl)):.4f}")

    if len(trades) < len(chain_pnl):
        print(f"\n[INFO] Bot chain has MORE trades ({len(chain_pnl)}) than Binance shows ({len(trades)})")
        print(f"       This means chain started before the Binance fetch window")
        print(f"       Need to fetch older history or the chain is very long")

    # Show last N trades side by side
    n = min(len(chain_pnl), len(trades))
    if n > 0:
        print(f"\n" + "="*80)
        print(f"Last {n} Trades Comparison:")
        print("="*80)
        print(f"{'#':<4} {'Bot Chain PnL':<15} {'Binance PnL':<15} {'Match?'}")
        print("-"*80)

        for i in range(n):
            bot_pnl = chain_pnl[-(n-i)]
            binance_pnl = trades[-(n-i)]['pnl']
            match = "OK" if abs(bot_pnl - binance_pnl) < 0.01 else "MISMATCH"
            print(f"{i+1:<4} ${bot_pnl:+7.4f}        ${binance_pnl:+7.4f}        {match}")

    print("\n" + "="*80)

finally:
    executor.close()
