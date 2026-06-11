"""
Identify losing chains - consecutive sequences of losing trades
"""
import json
from collections import defaultdict
from datetime import datetime

# Load latest positions
with open('docs/trades_export/latest_positions.json', 'r') as f:
    positions = json.load(f)

# Sort all positions by exit time
positions.sort(key=lambda x: x['exit_time'])

# Identify chains - consecutive losses on same symbol
chains = []
current_chain = None

for pos in positions:
    symbol = pos['symbol']
    outcome = pos['outcome']

    if outcome == 'LOSS':
        if current_chain and current_chain['symbol'] == symbol:
            # Continue existing chain
            current_chain['trades'].append(pos)
            current_chain['total_loss'] += pos['pnl_usdt']
            current_chain['end_time'] = pos['exit_time_cst']
        else:
            # Start new chain
            if current_chain and len(current_chain['trades']) > 1:
                chains.append(current_chain)

            current_chain = {
                'symbol': symbol,
                'trades': [pos],
                'total_loss': pos['pnl_usdt'],
                'start_time': pos['entry_time_cst'],
                'end_time': pos['exit_time_cst']
            }
    else:
        # Win or breakeven - end current chain
        if current_chain and len(current_chain['trades']) > 1:
            chains.append(current_chain)
        current_chain = None

# Add last chain if exists
if current_chain and len(current_chain['trades']) > 1:
    chains.append(current_chain)

# Sort by total loss (worst first)
chains.sort(key=lambda x: x['total_loss'])

print(f"\n{'='*120}")
print(f"LOSING CHAINS ANALYSIS - Consecutive Losses (May 24-30, 2026)")
print(f"{'='*120}\n")

print(f"Total Losing Chains Found: {len(chains)}")
print(f"Total Loss from Chains: ${sum(c['total_loss'] for c in chains):.2f}\n")

print(f"{'='*120}")
print(f"WORST LOSING CHAINS:")
print(f"{'='*120}\n")

print(f"{'#':<4} {'Symbol':<15} {'Trades':<8} {'Total Loss':<12} {'Start Time':<22} {'End Time':<22}")
print(f"{'-'*120}")

for i, chain in enumerate(chains, 1):
    print(f"{i:<4} {chain['symbol']:<15} {len(chain['trades']):<8} ${chain['total_loss']:<11.2f} {chain['start_time']:<22} {chain['end_time']:<22}")

print(f"\n{'='*120}")
print(f"DETAILED CHAIN BREAKDOWN (Top 10 Worst Chains):")
print(f"{'='*120}\n")

for i, chain in enumerate(chains[:10], 1):
    print(f"\n--- Chain #{i}: {chain['symbol']} ---")
    print(f"Total Trades: {len(chain['trades'])}")
    print(f"Total Loss: ${chain['total_loss']:.2f}")
    print(f"Duration: {chain['start_time']} to {chain['end_time']}")
    print(f"\nIndividual Losses:")

    for j, trade in enumerate(chain['trades'], 1):
        duration = trade['duration_minutes'] / 60
        print(f"  {j}. {trade['direction']} | Entry: {trade['entry_price']:.6f} | Exit: {trade['exit_price']:.6f} | Loss: ${trade['pnl_usdt']:.2f} | {duration:.2f}h")

print(f"\n{'='*120}")
print(f"\nCHAIN STATISTICS:")
print(f"{'-'*120}")

# Statistics
chain_lengths = [len(c['trades']) for c in chains]
chain_losses = [c['total_loss'] for c in chains]

print(f"Longest chain: {max(chain_lengths)} consecutive losses")
print(f"Shortest chain: {min(chain_lengths)} consecutive losses")
print(f"Average chain length: {sum(chain_lengths)/len(chain_lengths):.1f} trades")
print(f"Worst chain loss: ${min(chain_losses):.2f}")
print(f"Average chain loss: ${sum(chain_losses)/len(chain_losses):.2f}")

# By symbol
symbol_chains = defaultdict(lambda: {'count': 0, 'total_loss': 0.0})
for chain in chains:
    symbol = chain['symbol']
    symbol_chains[symbol]['count'] += 1
    symbol_chains[symbol]['total_loss'] += chain['total_loss']

sorted_symbols = sorted(symbol_chains.items(), key=lambda x: x[1]['total_loss'])

print(f"\n{'='*120}")
print(f"CHAINS BY SYMBOL:")
print(f"{'-'*120}")
print(f"{'Symbol':<15} {'# of Chains':<15} {'Total Chain Loss':<20}")
print(f"{'-'*120}")

for symbol, data in sorted_symbols[:20]:
    print(f"{symbol:<15} {data['count']:<15} ${data['total_loss']:<19.2f}")

print(f"\n{'='*120}\n")
