"""
Debug SIRENUSDT trade to understand P&L discrepancy
"""
import sys
import os
import json
from datetime import datetime
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor
import config


def ms_to_cst_string(timestamp_ms: int) -> str:
    """Convert Unix milliseconds to CST datetime string"""
    utc_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
    cst = pytz.timezone('US/Central')
    cst_time = utc_time.astimezone(cst)
    return cst_time.strftime('%Y-%m-%d %H:%M:%S CST')


def cst_to_utc_milliseconds(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Convert CST datetime to UTC Unix milliseconds"""
    cst = pytz.timezone('US/Central')
    target_time_cst = cst.localize(datetime(year, month, day, hour, minute, 0))
    target_time_utc = target_time_cst.astimezone(pytz.UTC)
    return int(target_time_utc.timestamp() * 1000)


def main():
    print("="*80)
    print("DEBUG SIRENUSDT TRADE")
    print("="*80)

    # June 1, 2026 - wider search window
    start_time_ms = cst_to_utc_milliseconds(2026, 6, 1, 6, 0)
    end_time_ms = cst_to_utc_milliseconds(2026, 6, 1, 10, 0)

    print(f"\nSearching for SIRENUSDT trades from {ms_to_cst_string(start_time_ms)} to {ms_to_cst_string(end_time_ms)}")

    executor = OrderExecutor()

    try:
        params = {
            "symbol": "SIRENUSDT",
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "limit": 1000
        }
        params = executor._sign_params(params)

        resp = executor.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/userTrades",
            params=params,
            headers=executor._headers()
        )
        resp.raise_for_status()
        trades = resp.json()

        print(f"\nFound {len(trades)} trades\n")

        for i, trade in enumerate(trades, 1):
            print(f"Trade {i}:")
            print(f"  Time: {ms_to_cst_string(int(trade['time']))}")
            print(f"  Side: {trade['side']}")
            print(f"  Qty: {trade['qty']}")
            print(f"  Price: {trade['price']}")
            print(f"  Realized PNL: {trade.get('realizedPnl', 'N/A')}")
            print(f"  Commission: {trade.get('commission', 'N/A')}")
            print(f"  Position Side: {trade.get('positionSide', 'N/A')}")
            print(f"  Buyer: {trade.get('buyer', 'N/A')}")
            print()

        # Save raw data
        with open('docs/trades_export/siren_debug.json', 'w') as f:
            json.dump(trades, f, indent=2)

        print("Raw trade data saved to: docs/trades_export/siren_debug.json")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        executor.close()


if __name__ == "__main__":
    main()
