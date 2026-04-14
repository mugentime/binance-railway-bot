"""
Check trade history for AIOT to verify SL execution
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import hmac
import hashlib
import time
import urllib.parse
import httpx
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET")
BINANCE_BASE_URL = "https://fapi.binance.com"

def sign_params(params: dict) -> dict:
    """Sign parameters with HMAC-SHA256"""
    params["timestamp"] = int(time.time() * 1000)
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        BINANCE_API_SECRET.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params

def get_trade_history(symbol: str, start_time: int = None, end_time: int = None, limit: int = 20):
    """Get trade history for a symbol"""
    client = httpx.Client(timeout=30.0)
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}

    params = {
        "symbol": symbol,
        "limit": limit
    }

    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    params = sign_params(params)

    try:
        resp = client.get(
            f"{BINANCE_BASE_URL}/fapi/v1/userTrades",
            params=params,
            headers=headers
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, 'response'):
            try:
                print(f"Response: {e.response.text[:200]}")
            except:
                pass
        return None
    finally:
        client.close()

if __name__ == "__main__":
    print("=" * 80)
    print("CHECKING TRADE HISTORY FOR AIOT TRADE")
    print("=" * 80)
    print()

    # Trade details from logs:
    # Entry: 2026-04-12 16:30:08 @ 0.0563 LONG
    # SL placed: algoId 2000000768249755 @ 0.0540200
    # Loss recorded: 2026-04-12 17:00:04 @ 0.0528

    # Convert to Unix timestamps (milliseconds)
    # 2026-04-12 16:00:00 to 2026-04-12 18:00:00
    start_time = int(1776006000000)  # 2026-04-12 16:00:00 UTC
    end_time = int(1776013200000)    # 2026-04-12 18:00:00 UTC

    print(f"Querying trade history for AIOTUSDT")
    print(f"Time range: 2026-04-12 16:00:00 to 18:00:00 UTC")
    print()

    trades = get_trade_history("AIOTUSDT", start_time, end_time, limit=50)

    if trades:
        print(f"Found {len(trades)} trades:")
        print()

        entry_trade = None
        exit_trade = None

        for trade in trades:
            trade_id = trade.get("id")
            order_id = trade.get("orderId")
            price = float(trade.get("price"))
            qty = float(trade.get("qty"))
            commission = float(trade.get("commission"))
            commission_asset = trade.get("commissionAsset")
            realized_pnl = float(trade.get("realizedPnl"))
            side = trade.get("side")
            position_side = trade.get("positionSide")
            maker = trade.get("maker")
            timestamp = trade.get("time")

            dt = datetime.fromtimestamp(timestamp/1000)

            print(f"Trade ID: {trade_id} | Order ID: {order_id}")
            print(f"  Time: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Side: {side} | Position: {position_side}")
            print(f"  Price: {price:.6f} | Qty: {qty:.1f}")
            print(f"  Maker: {maker}")
            print(f"  Realized PnL: ${realized_pnl:.4f}")
            print(f"  Commission: {commission} {commission_asset}")

            # Identify entry and exit trades
            if side == "BUY" and abs(price - 0.05627) < 0.00001:
                entry_trade = trade
                print("  >> ENTRY TRADE DETECTED")
            elif side == "SELL" and abs(price - 0.0528) < 0.001:
                exit_trade = trade
                print("  >> EXIT TRADE DETECTED (LOSS)")

            print()

        print("=" * 80)
        print("ANALYSIS:")
        print("=" * 80)

        if entry_trade:
            entry_time = datetime.fromtimestamp(entry_trade['time']/1000)
            print(f"Entry: {entry_time.strftime('%H:%M:%S')} @ {float(entry_trade['price']):.6f}")

        if exit_trade:
            exit_time = datetime.fromtimestamp(exit_trade['time']/1000)
            exit_price = float(exit_trade['price'])
            print(f"Exit:  {exit_time.strftime('%H:%M:%S')} @ {exit_price:.6f}")
            print()
            print(f"SL trigger price was: 0.0540200")
            print(f"Actual exit price:    {exit_price:.6f}")
            print()

            if exit_price < 0.054:
                print("SLIPPAGE DETECTED!")
                slippage = ((0.054020 - exit_price) / 0.054020) * 100
                print(f"Slippage: {slippage:.2f}% worse than SL trigger")
                print()
                print("This suggests the SL WAS TRIGGERED but filled at a worse price")
                print("due to market conditions (fast dump / low liquidity).")
            else:
                print("Exit price is better than expected - unusual.")

            # Check if it was a maker or taker trade
            if exit_trade.get('maker'):
                print()
                print("WARNING: Exit was a MAKER trade (TP filled)")
                print("This suggests TP was hit, not SL!")
            else:
                print()
                print("EXIT was a TAKER trade - consistent with SL STOP_MARKET execution")
    else:
        print("No trades found or error occurred")
