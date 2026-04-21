"""Diagnose position sizing calculation vs actual Binance"""
import sys
sys.path.insert(0, 'src')
from order_executor import OrderExecutor
import config
import json

executor = OrderExecutor()

try:
    print("\n" + "="*80)
    print("POSITION SIZE DIAGNOSTIC")
    print("="*80 + "\n")

    # Get account balance
    balance = executor.get_account_balance()
    print(f"Account Balance: ${balance:.2f}")

    # Calculate what bot thinks position sizes should be
    base_margin = balance * config.BASE_SIZE_PCT
    base_notional = base_margin * config.LEVERAGE

    print(f"\nBot's Position Size Calculation:")
    print(f"  BASE_SIZE_PCT: {config.BASE_SIZE_PCT} ({config.BASE_SIZE_PCT*100:.1f}%)")
    print(f"  LEVERAGE: {config.LEVERAGE}x")
    print(f"  Base Margin (Level 0): ${base_margin:.2f}")
    print(f"  Base Notional (Level 0): ${base_notional:.2f}")

    print(f"\n  Martingale Levels:")
    for level in range(0, min(config.MAX_LEVEL + 1, 5)):
        margin = base_margin * (1.5 ** level)
        notional = margin * config.LEVERAGE
        print(f"    Level {level}: Margin=${margin:.2f}, Notional=${notional:.2f}")

    # Check recent positions from Binance
    print(f"\n" + "="*80)
    print("RECENT ACTUAL POSITIONS FROM BINANCE:")
    print("="*80 + "\n")

    from datetime import datetime, timedelta
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(hours=6)).timestamp() * 1000)

    params = {
        "incomeType": "REALIZED_PNL",
        "startTime": start_time,
        "endTime": end_time,
        "limit": 10
    }
    params = executor._sign_params(params)

    resp = executor.client.get(
        f"{config.BINANCE_BASE_URL}/fapi/v1/income",
        params=params,
        headers=executor._headers()
    )
    resp.raise_for_status()
    income_records = resp.json()

    if income_records:
        print("Last 5 closed positions:")
        for record in reversed(income_records[-5:]):
            symbol = record['symbol']
            pnl = float(record['income'])
            timestamp = datetime.fromtimestamp(record['time'] / 1000)

            # Try to estimate position size from PnL
            # For small price moves (~0.4%), position ≈ PnL / 0.004
            estimated_notional = abs(pnl) / 0.004

            print(f"\n  {symbol:12s} @ {timestamp.strftime('%H:%M:%S')}")
            print(f"    Realized PnL: ${pnl:+.4f}")
            print(f"    Est. Notional: ${estimated_notional:.2f} (rough estimate)")

    # Load state to see what bot recorded
    print(f"\n" + "="*80)
    print("BOT STATE:")
    print("="*80 + "\n")

    with open('state.json', 'r') as f:
        state = json.load(f)

    print(f"  Level: {state.get('level', 'N/A')}")
    print(f"  In Position: {state.get('in_position', False)}")
    if state.get('in_position'):
        print(f"  Symbol: {state.get('current_symbol', 'N/A')}")
        print(f"  Entry Price: {state.get('entry_price', 'N/A')}")
        print(f"  Entry Quantity: {state.get('entry_quantity', 'N/A')}")
        print(f"  current_size_usd: ${state.get('current_size_usd', 0):.2f}")

    print("\n" + "="*80)

finally:
    executor.close()
