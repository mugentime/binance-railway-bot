"""
Binance Trade Retrieval Script
Fetches all trades from a specific date onwards and exports to multiple formats
"""
import sys
import os
import json
import csv
import time
from datetime import datetime
from typing import List, Dict, Optional
import pytz

# Add src directory to path to import OrderExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor
import config


def cst_to_utc_milliseconds(year: int, month: int, day: int, hour: int, minute: int) -> int:
    """
    Convert CST datetime to UTC Unix milliseconds

    Args:
        year, month, day, hour, minute: CST datetime components

    Returns:
        Unix timestamp in milliseconds (UTC)
    """
    cst = pytz.timezone('US/Central')

    # Create CST datetime (localize handles DST automatically)
    target_time_cst = cst.localize(datetime(year, month, day, hour, minute, 0))

    # Convert to UTC
    target_time_utc = target_time_cst.astimezone(pytz.UTC)

    # Convert to Unix milliseconds
    start_time_ms = int(target_time_utc.timestamp() * 1000)

    print(f"\n{'='*80}")
    print(f"TIMESTAMP CONVERSION")
    print(f"{'='*80}")
    print(f"Input (CST):  {target_time_cst.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"UTC:          {target_time_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Unix (ms):    {start_time_ms}")
    print(f"{'='*80}\n")

    return start_time_ms


def ms_to_cst_string(timestamp_ms: int) -> str:
    """
    Convert Unix milliseconds to CST datetime string

    Args:
        timestamp_ms: Unix timestamp in milliseconds

    Returns:
        Formatted CST datetime string (YYYY-MM-DD HH:MM:SS CST)
    """
    utc_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
    cst = pytz.timezone('US/Central')
    cst_time = utc_time.astimezone(cst)

    return cst_time.strftime('%Y-%m-%d %H:%M:%S CST')


def fetch_all_trades(executor: OrderExecutor, start_time_ms: int, symbol: Optional[str] = None) -> List[Dict]:
    """
    Fetch all trades from Binance API with pagination

    Args:
        executor: OrderExecutor instance
        start_time_ms: Start time in Unix milliseconds
        symbol: Optional symbol filter (e.g., "BTCUSDT"). If None, fetches all symbols.

    Returns:
        List of trade dictionaries
    """
    all_trades = []
    current_start_time = start_time_ms
    batch_num = 1

    print(f"\n{'='*80}")
    print(f"FETCHING TRADES FROM BINANCE API")
    print(f"{'='*80}")

    while True:
        try:
            # Build params
            params = {
                "startTime": current_start_time,
                "limit": 1000
            }

            # Add symbol if specified
            if symbol:
                params["symbol"] = symbol

            # Sign params
            params = executor._sign_params(params)

            # Fetch trades
            print(f"Batch {batch_num}: Fetching trades (startTime={current_start_time})...", end=" ")

            resp = executor.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/userTrades",
                params=params,
                headers=executor._headers()
            )

            resp.raise_for_status()
            trades = resp.json()

            if not trades:
                print("No more trades found.")
                break

            print(f"{len(trades)} trades retrieved")
            all_trades.extend(trades)

            # If we got less than 1000 trades, we've reached the end
            if len(trades) < 1000:
                print(f"Last batch retrieved (< 1000 trades).")
                break

            # Update start time to last trade's time + 1ms to avoid duplicates
            current_start_time = trades[-1]["time"] + 1
            batch_num += 1

            # Small delay to avoid rate limiting
            time.sleep(0.1)

        except Exception as e:
            print(f"\nERROR fetching trades: {e}")
            import traceback
            traceback.print_exc()
            break

    print(f"\n{'='*80}")
    print(f"TOTAL TRADES RETRIEVED: {len(all_trades)}")
    print(f"{'='*80}\n")

    return all_trades


def enrich_trade_data(trades: List[Dict]) -> List[Dict]:
    """
    Enrich trades with CST timestamps and cumulative P&L

    Args:
        trades: List of trade dictionaries from Binance

    Returns:
        List of enriched trade dictionaries
    """
    print(f"\n{'='*80}")
    print(f"ENRICHING TRADE DATA")
    print(f"{'='*80}")

    cumulative_pnl = 0.0
    enriched_trades = []

    for i, trade in enumerate(trades):
        # Convert timestamp to CST
        time_cst = ms_to_cst_string(int(trade["time"]))

        # Calculate cumulative P&L
        realized_pnl = float(trade.get("realizedPnl", 0))
        cumulative_pnl += realized_pnl

        # Create enriched trade
        enriched_trade = {
            **trade,  # Keep all original fields
            "time_cst": time_cst,
            "cumulative_pnl": round(cumulative_pnl, 4),
            "fee_usdt": float(trade.get("commission", 0)) if trade.get("commissionAsset") == "USDT" else 0.0
        }

        enriched_trades.append(enriched_trade)

        if (i + 1) % 100 == 0:
            print(f"Processed {i + 1}/{len(trades)} trades...")

    print(f"OK: Enriched {len(enriched_trades)} trades with CST timestamps and cumulative P&L")
    print(f"{'='*80}\n")

    return enriched_trades


def export_to_csv(trades: List[Dict], output_path: str):
    """
    Export trades to CSV format

    Args:
        trades: List of enriched trade dictionaries
        output_path: Path to save CSV file
    """
    print(f"Exporting to CSV: {output_path}...", end=" ")

    # Define columns for CSV (key fields only)
    columns = [
        "time_cst", "symbol", "side", "price", "qty",
        "realizedPnl", "cumulative_pnl", "commission", "commissionAsset"
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(trades)

    print("OK")


def export_to_json(trades: List[Dict], output_path: str):
    """
    Export trades to JSON format (complete data)

    Args:
        trades: List of enriched trade dictionaries
        output_path: Path to save JSON file
    """
    print(f"Exporting to JSON: {output_path}...", end=" ")

    with open(output_path, 'w', encoding='utf-8') as jsonfile:
        json.dump(trades, jsonfile, indent=2, ensure_ascii=False)

    print("OK")


def generate_markdown_summary(trades: List[Dict], output_path: str, start_date_str: str):
    """
    Generate Markdown summary report

    Args:
        trades: List of enriched trade dictionaries
        output_path: Path to save Markdown file
        start_date_str: Start date string for report header
    """
    print(f"Generating Markdown summary: {output_path}...", end=" ")

    if not trades:
        with open(output_path, 'w', encoding='utf-8') as mdfile:
            mdfile.write(f"# Trade Summary: {start_date_str}\n\n")
            mdfile.write("**No trades found in this period.**\n")
        print("OK")
        return

    # Calculate statistics
    total_trades = len(trades)
    symbols_traded = set(trade["symbol"] for trade in trades)
    total_pnl = sum(float(trade.get("realizedPnl", 0)) for trade in trades)
    total_fees = sum(float(trade.get("commission", 0)) for trade in trades if trade.get("commissionAsset") == "USDT")

    # Win/loss analysis (simplified - assumes side determines win/loss direction)
    winning_trades = [t for t in trades if float(t.get("realizedPnl", 0)) > 0]
    losing_trades = [t for t in trades if float(t.get("realizedPnl", 0)) < 0]
    neutral_trades = [t for t in trades if float(t.get("realizedPnl", 0)) == 0]

    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0

    # Get date range
    first_trade_time = ms_to_cst_string(int(trades[0]["time"]))
    last_trade_time = ms_to_cst_string(int(trades[-1]["time"]))

    # Top 10 most profitable trades
    sorted_by_pnl = sorted(trades, key=lambda t: float(t.get("realizedPnl", 0)), reverse=True)
    top_wins = sorted_by_pnl[:10]
    top_losses = sorted_by_pnl[-10:][::-1]  # Bottom 10, reversed

    # Symbol breakdown
    symbol_stats = {}
    for trade in trades:
        symbol = trade["symbol"]
        pnl = float(trade.get("realizedPnl", 0))

        if symbol not in symbol_stats:
            symbol_stats[symbol] = {"count": 0, "pnl": 0.0}

        symbol_stats[symbol]["count"] += 1
        symbol_stats[symbol]["pnl"] += pnl

    # Sort symbols by total P&L
    sorted_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)

    # Write Markdown report
    with open(output_path, 'w', encoding='utf-8') as mdfile:
        mdfile.write(f"# Trade Summary: {start_date_str}\n\n")

        mdfile.write("## Overview\n\n")
        mdfile.write(f"- **Total Trades:** {total_trades:,}\n")
        mdfile.write(f"- **Total P&L:** ${total_pnl:,.2f} USDT\n")
        mdfile.write(f"- **Total Fees:** ${total_fees:,.2f} USDT\n")
        mdfile.write(f"- **Net P&L (after fees):** ${total_pnl - total_fees:,.2f} USDT\n")
        mdfile.write(f"- **Symbols Traded:** {len(symbols_traded)}\n")
        mdfile.write(f"- **Date Range:** {first_trade_time} to {last_trade_time}\n\n")

        mdfile.write("## Performance\n\n")
        mdfile.write(f"- **Winning Trades:** {len(winning_trades)} ({win_rate:.1f}%)\n")
        mdfile.write(f"- **Losing Trades:** {len(losing_trades)} ({len(losing_trades)/total_trades*100:.1f}%)\n")
        mdfile.write(f"- **Neutral Trades:** {len(neutral_trades)} ({len(neutral_trades)/total_trades*100:.1f}%)\n\n")

        if winning_trades:
            avg_win = sum(float(t.get("realizedPnl", 0)) for t in winning_trades) / len(winning_trades)
            mdfile.write(f"- **Average Win:** ${avg_win:.2f}\n")

        if losing_trades:
            avg_loss = sum(float(t.get("realizedPnl", 0)) for t in losing_trades) / len(losing_trades)
            mdfile.write(f"- **Average Loss:** ${avg_loss:.2f}\n")

        mdfile.write("\n")

        mdfile.write("## Top 10 Most Profitable Trades\n\n")
        mdfile.write("| Time (CST) | Symbol | Side | Price | Qty | P&L (USDT) |\n")
        mdfile.write("|------------|--------|------|-------|-----|------------|\n")
        for trade in top_wins:
            mdfile.write(f"| {trade['time_cst']} | {trade['symbol']} | {trade['side']} | "
                        f"{float(trade['price']):.6f} | {float(trade['qty']):.4f} | "
                        f"${float(trade.get('realizedPnl', 0)):.2f} |\n")
        mdfile.write("\n")

        mdfile.write("## Top 10 Worst Trades\n\n")
        mdfile.write("| Time (CST) | Symbol | Side | Price | Qty | P&L (USDT) |\n")
        mdfile.write("|------------|--------|------|-------|-----|------------|\n")
        for trade in top_losses:
            mdfile.write(f"| {trade['time_cst']} | {trade['symbol']} | {trade['side']} | "
                        f"{float(trade['price']):.6f} | {float(trade['qty']):.4f} | "
                        f"${float(trade.get('realizedPnl', 0)):.2f} |\n")
        mdfile.write("\n")

        mdfile.write("## Symbol Breakdown\n\n")
        mdfile.write("| Symbol | Trades | Total P&L (USDT) | Avg P&L per Trade |\n")
        mdfile.write("|--------|--------|------------------|-------------------|\n")
        for symbol, stats in sorted_symbols:
            avg_pnl = stats["pnl"] / stats["count"]
            mdfile.write(f"| {symbol} | {stats['count']} | ${stats['pnl']:.2f} | ${avg_pnl:.2f} |\n")
        mdfile.write("\n")

        mdfile.write("---\n\n")
        mdfile.write(f"*Report generated on {datetime.now(pytz.timezone('US/Central')).strftime('%Y-%m-%d %H:%M:%S CST')}*\n")

    print("OK")


def main():
    """
    Main execution function
    """
    print(f"\n{'='*80}")
    print(f"BINANCE TRADE RETRIEVAL SCRIPT")
    print(f"{'='*80}\n")

    # Define start time: May 4, 2026, 2:26 PM CST
    START_YEAR = 2026
    START_MONTH = 5
    START_DAY = 4
    START_HOUR = 14  # 2 PM in 24-hour format
    START_MINUTE = 26

    # Convert to UTC milliseconds
    start_time_ms = cst_to_utc_milliseconds(START_YEAR, START_MONTH, START_DAY, START_HOUR, START_MINUTE)

    # Initialize OrderExecutor
    print("Initializing Binance API client...")
    executor = OrderExecutor()

    try:
        # Fetch all trades
        trades = fetch_all_trades(executor, start_time_ms, symbol=None)  # None = all symbols

        if not trades:
            print("\nWARNING: No trades found from the specified date.")
            return

        # Enrich data
        enriched_trades = enrich_trade_data(trades)

        # Create output directory if it doesn't exist
        output_dir = os.path.join("docs", "trades_export")
        os.makedirs(output_dir, exist_ok=True)

        # Generate file names
        date_str = f"{START_YEAR}-{START_MONTH:02d}-{START_DAY:02d}"
        csv_path = os.path.join(output_dir, f"trades_from_{date_str}.csv")
        json_path = os.path.join(output_dir, f"trades_from_{date_str}.json")
        md_path = os.path.join(output_dir, f"trades_from_{date_str}.md")

        # Export to files
        print(f"\n{'='*80}")
        print(f"EXPORTING DATA")
        print(f"{'='*80}")
        export_to_csv(enriched_trades, csv_path)
        export_to_json(enriched_trades, json_path)
        generate_markdown_summary(enriched_trades, md_path, f"{date_str} onwards")

        print(f"\n{'='*80}")
        print(f"EXPORT COMPLETE")
        print(f"{'='*80}")
        print(f"Files saved to: {output_dir}/")
        print(f"  - {os.path.basename(csv_path)}")
        print(f"  - {os.path.basename(json_path)}")
        print(f"  - {os.path.basename(md_path)}")
        print(f"{'='*80}\n")

        # Display quick summary
        total_pnl = sum(float(t.get("realizedPnl", 0)) for t in enriched_trades)
        symbols = set(t["symbol"] for t in enriched_trades)
        first_time = ms_to_cst_string(int(enriched_trades[0]["time"]))
        last_time = ms_to_cst_string(int(enriched_trades[-1]["time"]))

        print(f"📊 SUMMARY:")
        print(f"   Total Trades: {len(enriched_trades):,}")
        print(f"   Total P&L: ${total_pnl:,.2f} USDT")
        print(f"   Symbols: {len(symbols)}")
        print(f"   First Trade: {first_time}")
        print(f"   Last Trade: {last_time}")
        print(f"\nOK - All exports successful!\n")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Close HTTP client
        executor.close()
        print("HTTP client closed.")


if __name__ == "__main__":
    main()
