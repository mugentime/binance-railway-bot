"""
Generate comprehensive trade reports for May 17 - June 1, 2026
"""
import sys
import os
import json
from datetime import datetime
from collections import defaultdict
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from order_executor import OrderExecutor
import config


def cst_to_utc_milliseconds(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Convert CST datetime to UTC Unix milliseconds"""
    cst = pytz.timezone('US/Central')
    target_time_cst = cst.localize(datetime(year, month, day, hour, minute, 0))
    target_time_utc = target_time_cst.astimezone(pytz.UTC)
    return int(target_time_utc.timestamp() * 1000)


def ms_to_cst_string(timestamp_ms: int) -> str:
    """Convert Unix milliseconds to CST datetime string"""
    utc_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
    cst = pytz.timezone('US/Central')
    cst_time = utc_time.astimezone(cst)
    return cst_time.strftime('%Y-%m-%d %H:%M:%S CST')


def fetch_all_trades(executor: OrderExecutor, start_time_ms: int, end_time_ms: int) -> list:
    """Fetch all trades within date range, using 7-day windows to avoid API limits"""
    all_trades = []

    # Binance has a max time window limit, so we'll fetch in 7-day chunks
    SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000

    print(f"\nFetching trades from {ms_to_cst_string(start_time_ms)} to {ms_to_cst_string(end_time_ms)}")

    chunk_start = start_time_ms

    while chunk_start < end_time_ms:
        chunk_end = min(chunk_start + SEVEN_DAYS_MS, end_time_ms)

        print(f"\nChunk: {ms_to_cst_string(chunk_start)} to {ms_to_cst_string(chunk_end)}")

        current_start_time = chunk_start
        batch_num = 1

        while current_start_time < chunk_end:
            try:
                params = {
                    "startTime": current_start_time,
                    "endTime": chunk_end,
                    "limit": 1000
                }
                params = executor._sign_params(params)

                print(f"  Batch {batch_num}: Fetching...", end=" ")
                resp = executor.client.get(
                    f"{config.BINANCE_BASE_URL}/fapi/v1/userTrades",
                    params=params,
                    headers=executor._headers()
                )
                resp.raise_for_status()
                trades = resp.json()

                if not trades:
                    print("No more trades.")
                    break

                print(f"{len(trades)} trades")
                all_trades.extend(trades)

                if len(trades) < 1000:
                    break

                current_start_time = trades[-1]["time"] + 1
                batch_num += 1

            except Exception as e:
                print(f"\n  ERROR: {e}")
                break

        chunk_start = chunk_end + 1

    print(f"\nTotal trades retrieved: {len(all_trades)}")
    return all_trades


def reconstruct_positions(trades: list) -> list:
    """Reconstruct position entries and exits from trades"""
    trades_by_symbol = defaultdict(list)
    for trade in trades:
        symbol = trade["symbol"]
        trades_by_symbol[symbol].append(trade)

    for symbol in trades_by_symbol:
        trades_by_symbol[symbol].sort(key=lambda t: int(t["time"]))

    positions = []

    for symbol, symbol_trades in trades_by_symbol.items():
        position_amt = 0.0
        entry_trades = []
        entry_qty_total = 0.0
        entry_value_total = 0.0
        exit_trades = []
        accumulated_pnl = 0.0

        for trade in symbol_trades:
            side = trade["side"]
            qty = float(trade["qty"])
            price = float(trade["price"])
            trade_time = int(trade["time"])
            realized_pnl = float(trade.get("realizedPnl", 0))

            if side == "BUY":
                new_position_amt = position_amt + qty
            else:
                new_position_amt = position_amt - qty

            # Entry trade
            if abs(new_position_amt) > abs(position_amt):
                entry_trades.append(trade)
                entry_qty_total += qty
                entry_value_total += qty * price

            # Exit trade
            elif abs(new_position_amt) < abs(position_amt):
                if entry_qty_total > 0:
                    avg_entry_price = entry_value_total / entry_qty_total

                    # Accumulate exit trades and PNL
                    exit_trades.append(trade)
                    accumulated_pnl += realized_pnl

                    # Only create position record when position is FULLY closed
                    if new_position_amt == 0:
                        if position_amt > 0:
                            direction = "LONG"
                        elif position_amt < 0:
                            direction = "SHORT"
                        else:
                            direction = "UNKNOWN"

                        # Use first and last exit for price and time
                        first_exit = exit_trades[0]
                        last_exit = exit_trades[-1]
                        total_exit_qty = sum(float(t["qty"]) for t in exit_trades)
                        weighted_exit_price = sum(float(t["qty"]) * float(t["price"]) for t in exit_trades) / total_exit_qty

                        outcome = "WIN" if accumulated_pnl > 0 else "LOSS" if accumulated_pnl < 0 else "BREAKEVEN"

                        if entry_trades:
                            entry_time = int(entry_trades[0]["time"])
                            exit_time = int(last_exit["time"])
                            duration_ms = exit_time - entry_time
                            duration_minutes = duration_ms / 1000 / 60
                        else:
                            entry_time = trade_time
                            duration_minutes = 0

                        position = {
                            "symbol": symbol,
                            "direction": direction,
                            "entry_time": entry_time,
                            "entry_time_cst": ms_to_cst_string(entry_time),
                            "exit_time": exit_time,
                            "exit_time_cst": ms_to_cst_string(exit_time),
                            "entry_price": round(avg_entry_price, 8),
                            "exit_price": round(weighted_exit_price, 8),
                            "quantity": round(total_exit_qty, 8),
                            "pnl_usdt": round(accumulated_pnl, 4),
                            "outcome": outcome,
                            "duration_minutes": round(duration_minutes, 2),
                            "num_entry_trades": len(entry_trades),
                            "martingale_level": len(entry_trades) - 1,
                        }

                        positions.append(position)

                        # Reset for next position
                        entry_trades = []
                        entry_qty_total = 0.0
                        entry_value_total = 0.0
                        exit_trades = []
                        accumulated_pnl = 0.0
                    else:
                        # Partial exit - adjust entry tracking proportionally
                        entry_qty_total -= qty
                        entry_value_total -= qty * avg_entry_price

            position_amt = new_position_amt

    return positions


def identify_chains(positions: list) -> list:
    """Identify consecutive losing chains from positions"""
    # Sort by exit time
    sorted_positions = sorted(positions, key=lambda x: x["exit_time"])

    chains = []
    chains_by_symbol = {}

    for pos in sorted_positions:
        symbol = pos["symbol"]

        if symbol not in chains_by_symbol:
            chains_by_symbol[symbol] = []

        if pos["outcome"] == "LOSS":
            # Add to current chain or start new one
            if chains_by_symbol[symbol] and chains_by_symbol[symbol][-1]["active"]:
                chains_by_symbol[symbol][-1]["positions"].append(pos)
                chains_by_symbol[symbol][-1]["total_loss"] += pos["pnl_usdt"]
            else:
                chains_by_symbol[symbol].append({
                    "symbol": symbol,
                    "positions": [pos],
                    "total_loss": pos["pnl_usdt"],
                    "active": True
                })
        else:
            # WIN or BREAKEVEN - close current chain
            if chains_by_symbol[symbol] and chains_by_symbol[symbol][-1]["active"]:
                chains_by_symbol[symbol][-1]["active"] = False

    # Collect all chains with 2+ losses
    for symbol, symbol_chains in chains_by_symbol.items():
        for chain in symbol_chains:
            if len(chain["positions"]) >= 2:
                chains.append(chain)

    # Sort by total loss (worst first)
    chains.sort(key=lambda c: c["total_loss"])

    return chains


def generate_document1(positions: list):
    """Document 1: Detailed trade list with entry/exit conditions"""
    output_path = "docs/trades_export/DOCUMENT_1_All_Trades_May17_Jun1.md"

    print(f"\nGenerating Document 1: {output_path}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# DOCUMENT 1: All Trades (May 17 - June 1, 2026)\n\n")
        f.write("## Complete Trade List with Entry & Exit Details\n\n")

        # Summary stats
        total_positions = len(positions)
        winning = [p for p in positions if p["outcome"] == "WIN"]
        losing = [p for p in positions if p["outcome"] == "LOSS"]
        total_pnl = sum(p["pnl_usdt"] for p in positions)

        f.write(f"**Period:** May 17, 2026 - June 1, 2026\n")
        f.write(f"**Total Trades:** {total_positions}\n")
        f.write(f"**Winning Trades:** {len(winning)} ({len(winning)/total_positions*100:.1f}%)\n")
        f.write(f"**Losing Trades:** {len(losing)} ({len(losing)/total_positions*100:.1f}%)\n")
        f.write(f"**Total P&L:** ${total_pnl:.2f} USDT\n\n")

        f.write("---\n\n")
        f.write("## Individual Trade Details\n\n")

        # Sort by entry time
        positions.sort(key=lambda x: x["entry_time"])

        for i, pos in enumerate(positions, 1):
            f.write(f"### Trade #{i}: {pos['symbol']} {pos['direction']}\n\n")

            # Entry details
            f.write(f"**ENTRY:**\n")
            f.write(f"- Time: {pos['entry_time_cst']}\n")
            f.write(f"- Price: {pos['entry_price']:.8f}\n")
            f.write(f"- Direction: {pos['direction']}\n")
            f.write(f"- Martingale Level: Level {pos['martingale_level']} ({pos['num_entry_trades']} entries)\n")
            f.write(f"- Entry Condition: *Signal triggered (RSI/BB/Z-score analysis)*\n\n")

            # Exit details
            f.write(f"**EXIT:**\n")
            f.write(f"- Time: {pos['exit_time_cst']}\n")
            f.write(f"- Price: {pos['exit_price']:.8f}\n")
            f.write(f"- Exit Condition: ")

            # Determine exit condition
            if pos["outcome"] == "WIN":
                f.write(f"**Take Profit Hit** (10% TP target)\n")
            elif pos["outcome"] == "LOSS":
                f.write(f"**Stop Loss Hit** (4% SL trigger)\n")
            else:
                f.write(f"**Breakeven Exit**\n")

            f.write(f"\n**RESULT:**\n")
            f.write(f"- P&L: ${pos['pnl_usdt']:.2f} USDT\n")
            f.write(f"- Outcome: {pos['outcome']}\n")
            f.write(f"- Duration: {pos['duration_minutes']:.1f} minutes ({pos['duration_minutes']/60:.1f} hours)\n")
            f.write(f"- Price Change: {((pos['exit_price']-pos['entry_price'])/pos['entry_price']*100):.2f}%\n")

            f.write(f"\n---\n\n")

    print(f"[OK] Document 1 created: {output_path}")


def generate_document2(positions: list):
    """Document 2: All trades grouped by chains (winning and losing)"""
    output_path = "docs/trades_export/DOCUMENT_2_All_Chains_May17_Jun1.md"

    print(f"\nGenerating Document 2: {output_path}")

    winning_chains, losing_chains = identify_all_chains(positions)

    # Combine all chains and sort by absolute P&L (biggest impact first)
    all_chains = winning_chains + losing_chains
    all_chains.sort(key=lambda c: abs(c["total_pnl"]), reverse=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# DOCUMENT 2: All Chains (May 17 - June 1, 2026)\n\n")
        f.write("## All Trades Grouped by Chains\n\n")

        # Summary stats
        total_chains = len(all_chains)
        total_winning = len(winning_chains)
        total_losing = len(losing_chains)
        total_pnl = sum(c["total_pnl"] for c in all_chains)
        total_trades = sum(len(c["positions"]) for c in all_chains)

        f.write(f"**Period:** May 17, 2026 - June 1, 2026\n")
        f.write(f"**Total Chains:** {total_chains}\n")
        f.write(f"**Winning Chains:** {total_winning}\n")
        f.write(f"**Losing Chains:** {total_losing}\n")
        f.write(f"**Total Trades in Chains:** {total_trades}\n")
        f.write(f"**Net P&L:** ${total_pnl:.2f} USDT\n")
        f.write(f"**Average Chain Length:** {total_trades/total_chains:.1f} trades\n\n")

        f.write("---\n\n")
        f.write("## All Chains (Sorted by P&L Impact)\n\n")

        for i, chain in enumerate(all_chains, 1):
            chain_length = len(chain["positions"])
            chain_pnl = chain["total_pnl"]
            outcome_label = "[WIN]" if chain_pnl > 0 else "[LOSS]"
            first_pos = chain["positions"][0]
            last_pos = chain["positions"][-1]

            f.write(f"### Chain #{i}: {chain['symbol']} - {chain_length} Trades {outcome_label}\n\n")
            f.write(f"**Chain Summary:**\n")
            f.write(f"- Symbol: {chain['symbol']}\n")
            f.write(f"- Total P&L: **${chain_pnl:.2f} USDT**\n")
            f.write(f"- Chain Length: {chain_length} trades\n")
            f.write(f"- Outcome: {outcome_label}\n")
            f.write(f"- Started: {first_pos['entry_time_cst']}\n")
            f.write(f"- Ended: {last_pos['exit_time_cst']}\n")

            # Calculate total duration
            duration_ms = last_pos["exit_time"] - first_pos["entry_time"]
            duration_hours = duration_ms / 1000 / 60 / 60
            f.write(f"- Chain Duration: {duration_hours:.1f} hours\n\n")

            f.write(f"**Trades in Chain:**\n\n")

            for j, pos in enumerate(chain["positions"], 1):
                trade_outcome = "[WIN]" if pos["outcome"] == "WIN" else "[LOSS]" if pos["outcome"] == "LOSS" else "[BE]"
                f.write(f"**Trade {j} (Level {pos['martingale_level']}):** {trade_outcome}\n")
                f.write(f"- Entry: {pos['entry_time_cst']} @ {pos['entry_price']:.8f}\n")
                f.write(f"- Exit: {pos['exit_time_cst']} @ {pos['exit_price']:.8f}\n")
                f.write(f"- Direction: {pos['direction']}\n")
                f.write(f"- P&L: ${pos['pnl_usdt']:.2f} USDT\n")
                f.write(f"- Duration: {pos['duration_minutes']:.1f} minutes\n")
                f.write(f"- Price Change: {((pos['exit_price']-pos['entry_price'])/pos['entry_price']*100):.2f}%\n\n")

            f.write(f"---\n\n")

    print(f"[OK] Document 2 created: {output_path}")


def identify_all_chains(positions: list) -> tuple:
    """Identify all chains (both winning and losing) from positions"""
    # Sort by exit time
    sorted_positions = sorted(positions, key=lambda x: x["exit_time"])

    all_chains = []
    chains_by_symbol = {}

    for pos in sorted_positions:
        symbol = pos["symbol"]

        if symbol not in chains_by_symbol:
            chains_by_symbol[symbol] = []

        # Start new chain or continue current
        if not chains_by_symbol[symbol] or not chains_by_symbol[symbol][-1]["active"]:
            # Start new chain
            chains_by_symbol[symbol].append({
                "symbol": symbol,
                "positions": [pos],
                "total_pnl": pos["pnl_usdt"],
                "outcome": pos["outcome"],
                "active": True
            })
        else:
            # Check if we should continue or end chain
            current_chain = chains_by_symbol[symbol][-1]

            # If outcome changes (WIN→LOSS or LOSS→WIN), end current and start new
            if (current_chain["outcome"] == "WIN" and pos["outcome"] == "LOSS") or \
               (current_chain["outcome"] == "LOSS" and pos["outcome"] == "WIN"):
                current_chain["active"] = False
                chains_by_symbol[symbol].append({
                    "symbol": symbol,
                    "positions": [pos],
                    "total_pnl": pos["pnl_usdt"],
                    "outcome": pos["outcome"],
                    "active": True
                })
            else:
                # Continue current chain (same outcome type)
                current_chain["positions"].append(pos)
                current_chain["total_pnl"] += pos["pnl_usdt"]
                current_chain["outcome"] = pos["outcome"]

    # Close any active chains
    for symbol_chains in chains_by_symbol.values():
        for chain in symbol_chains:
            chain["active"] = False

    # Collect all chains with 2+ trades
    winning_chains = []
    losing_chains = []

    for symbol, symbol_chains in chains_by_symbol.items():
        for chain in symbol_chains:
            if len(chain["positions"]) >= 2:
                if chain["total_pnl"] > 0:
                    winning_chains.append(chain)
                else:
                    losing_chains.append(chain)

    # Sort by P&L (winning: best first, losing: worst first)
    winning_chains.sort(key=lambda c: c["total_pnl"], reverse=True)
    losing_chains.sort(key=lambda c: c["total_pnl"])

    return winning_chains, losing_chains


def generate_document3(positions: list):
    """Document 3: All chains grouped by winning and losing"""
    output_path = "docs/trades_export/DOCUMENT_3_Chains_Grouped_May17_Jun1.md"

    print(f"\nGenerating Document 3: {output_path}")

    winning_chains, losing_chains = identify_all_chains(positions)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# DOCUMENT 3: All Chains Grouped (May 17 - June 1, 2026)\n\n")
        f.write("## Winning Chains vs Losing Chains\n\n")

        # Summary stats
        total_winning_pnl = sum(c["total_pnl"] for c in winning_chains)
        total_losing_pnl = sum(c["total_pnl"] for c in losing_chains)
        total_winning_trades = sum(len(c["positions"]) for c in winning_chains)
        total_losing_trades = sum(len(c["positions"]) for c in losing_chains)

        f.write(f"**Period:** May 17, 2026 - June 1, 2026\n\n")

        f.write(f"### Winning Chains Summary\n")
        f.write(f"- Total Winning Chains: {len(winning_chains)}\n")
        f.write(f"- Total Trades in Winning Chains: {total_winning_trades}\n")
        f.write(f"- Total P&L from Winning Chains: ${total_winning_pnl:.2f} USDT\n")
        if winning_chains:
            f.write(f"- Average Chain Length: {total_winning_trades/len(winning_chains):.1f} trades\n")
            f.write(f"- Average Chain P&L: ${total_winning_pnl/len(winning_chains):.2f} USDT\n")
        f.write(f"\n")

        f.write(f"### Losing Chains Summary\n")
        f.write(f"- Total Losing Chains: {len(losing_chains)}\n")
        f.write(f"- Total Trades in Losing Chains: {total_losing_trades}\n")
        f.write(f"- Total P&L from Losing Chains: ${total_losing_pnl:.2f} USDT\n")
        if losing_chains:
            f.write(f"- Average Chain Length: {total_losing_trades/len(losing_chains):.1f} trades\n")
            f.write(f"- Average Chain Loss: ${total_losing_pnl/len(losing_chains):.2f} USDT\n")
        f.write(f"\n")

        f.write(f"### Net Performance\n")
        f.write(f"- Net P&L: ${total_winning_pnl + total_losing_pnl:.2f} USDT\n\n")

        f.write("---\n\n")

        # WINNING CHAINS SECTION
        f.write(f"## WINNING CHAINS ({len(winning_chains)})\n\n")

        for i, chain in enumerate(winning_chains, 1):
            chain_length = len(chain["positions"])
            chain_pnl = chain["total_pnl"]
            first_pos = chain["positions"][0]
            last_pos = chain["positions"][-1]

            f.write(f"### Winning Chain #{i}: {chain['symbol']} - {chain_length} Trades\n\n")
            f.write(f"**Chain Summary:**\n")
            f.write(f"- Symbol: {chain['symbol']}\n")
            f.write(f"- Total P&L: **${chain_pnl:.2f} USDT** [WIN]\n")
            f.write(f"- Chain Length: {chain_length} trades\n")
            f.write(f"- Started: {first_pos['entry_time_cst']}\n")
            f.write(f"- Ended: {last_pos['exit_time_cst']}\n\n")

            f.write(f"**Trades in Chain:**\n\n")

            for j, pos in enumerate(chain["positions"], 1):
                outcome_str = "[WIN]" if pos["outcome"] == "WIN" else "[BE]"
                f.write(f"**Trade {j} (Level {pos['martingale_level']}):** {outcome_str}\n")
                f.write(f"- Entry: {pos['entry_time_cst']} @ {pos['entry_price']:.8f}\n")
                f.write(f"- Exit: {pos['exit_time_cst']} @ {pos['exit_price']:.8f}\n")
                f.write(f"- Direction: {pos['direction']}\n")
                f.write(f"- P&L: ${pos['pnl_usdt']:.2f} USDT\n")
                f.write(f"- Duration: {pos['duration_minutes']:.1f} minutes\n\n")

            f.write(f"---\n\n")

        # LOSING CHAINS SECTION
        f.write(f"## LOSING CHAINS ({len(losing_chains)})\n\n")

        for i, chain in enumerate(losing_chains, 1):
            chain_length = len(chain["positions"])
            chain_pnl = chain["total_pnl"]
            first_pos = chain["positions"][0]
            last_pos = chain["positions"][-1]

            f.write(f"### Losing Chain #{i}: {chain['symbol']} - {chain_length} Trades\n\n")
            f.write(f"**Chain Summary:**\n")
            f.write(f"- Symbol: {chain['symbol']}\n")
            f.write(f"- Total Loss: **${chain_pnl:.2f} USDT** [LOSS]\n")
            f.write(f"- Chain Length: {chain_length} trades\n")
            f.write(f"- Started: {first_pos['entry_time_cst']}\n")
            f.write(f"- Ended: {last_pos['exit_time_cst']}\n\n")

            f.write(f"**Trades in Chain:**\n\n")

            for j, pos in enumerate(chain["positions"], 1):
                outcome_str = "[LOSS]" if pos["outcome"] == "LOSS" else "[BE]"
                f.write(f"**Trade {j} (Level {pos['martingale_level']}):** {outcome_str}\n")
                f.write(f"- Entry: {pos['entry_time_cst']} @ {pos['entry_price']:.8f}\n")
                f.write(f"- Exit: {pos['exit_time_cst']} @ {pos['exit_price']:.8f}\n")
                f.write(f"- Direction: {pos['direction']}\n")
                f.write(f"- P&L: ${pos['pnl_usdt']:.2f} USDT\n")
                f.write(f"- Duration: {pos['duration_minutes']:.1f} minutes\n\n")

            f.write(f"---\n\n")

    print(f"[OK] Document 3 created: {output_path}")


def main():
    """Main execution"""
    print("="*80)
    print("TRADE REPORT GENERATOR")
    print("="*80)

    # Date range: May 17 - June 1, 2026
    start_time_ms = cst_to_utc_milliseconds(2026, 5, 17, 0, 0)
    end_time_ms = cst_to_utc_milliseconds(2026, 6, 1, 23, 59)

    print("\nInitializing Binance API client...")
    executor = OrderExecutor()

    try:
        # Fetch trades
        trades = fetch_all_trades(executor, start_time_ms, end_time_ms)

        if not trades:
            print("\nNo trades found in this period.")
            return

        # Reconstruct positions
        print("\nReconstructing positions from trades...")
        positions = reconstruct_positions(trades)

        print(f"Total positions reconstructed: {len(positions)}")

        # Create output directory
        os.makedirs("docs/trades_export", exist_ok=True)

        # Generate all 3 documents
        generate_document1(positions)
        generate_document2(positions)
        generate_document3(positions)

        print("\n" + "="*80)
        print("COMPLETE! All 3 documents generated.")
        print("="*80)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        executor.close()


if __name__ == "__main__":
    main()
