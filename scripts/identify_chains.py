"""
Identify trading chains from trade data
"""

# Trade data with position sizes
trades = [
    {"id": 1, "symbol": "EDGEUSDT", "time": "Jun 1 17:35", "pnl": -4.56, "size": 161.00, "dir": "LONG"},
    {"id": 2, "symbol": "UAIUSDT", "time": "Jun 1 19:15", "pnl": 0.23, "size": 13.27, "dir": "SHORT"},
    {"id": 3, "symbol": "UBUSDT", "time": "Jun 1 21:35", "pnl": -1.01, "size": 5.32, "dir": "SHORT"},
    {"id": 4, "symbol": "ORDIUSDT", "time": "Jun 1 22:55", "pnl": -1.39, "size": 34.29, "dir": "SHORT"},
    {"id": 5, "symbol": "PIEVERSEUSDT", "time": "Jun 2 00:00", "pnl": -0.02, "size": 43.24, "dir": "SHORT"},
    {"id": 6, "symbol": "RAVEUSDT", "time": "Jun 2 01:53", "pnl": 0.35, "size": 54.03, "dir": "LONG"},
    {"id": 7, "symbol": "IRYSUSDT", "time": "Jun 2 04:13", "pnl": 3.41, "size": 43.08, "dir": "SHORT"},
    {"id": 8, "symbol": "UAIUSDT", "time": "Jun 2 06:33", "pnl": -0.07, "size": 9.81, "dir": "SHORT"},
    {"id": 9, "symbol": "BASEDUSDT", "time": "Jun 2 08:08", "pnl": -0.44, "size": 9.89, "dir": "SHORT"},
    {"id": 10, "symbol": "INXUSDT", "time": "Jun 2 08:15", "pnl": 0.34, "size": 27.95, "dir": "SHORT"},
    {"id": 11, "symbol": "BIOUSDT", "time": "Jun 2 10:35", "pnl": -0.19, "size": 43.27, "dir": "SHORT"},
    {"id": 12, "symbol": "GENIUSUSDT", "time": "Jun 2 10:43", "pnl": 0.52, "size": 53.77, "dir": "LONG"},
    {"id": 13, "symbol": "BIOUSDT", "time": "Jun 2 13:03", "pnl": -0.17, "size": 34.35, "dir": "SHORT"},
    {"id": 14, "symbol": "SPKUSDT", "time": "Jun 2 14:38", "pnl": 0, "size": 54.11, "dir": "LONG"},
]

# Base size is around $5-15, multiplier is 1.25x
BASE_SIZE = 10
MULTIPLIER = 1.25

def estimate_level(size):
    """Estimate martingale level from position size"""
    if size < 20:
        return 0
    elif size < 30:
        return 1
    elif size < 45:
        return 2
    elif size < 60:
        return 3
    elif size < 100:
        return 4
    else:
        return 5

# Identify chains
chains = []
current_chain = None
chain_id = 0

print("\nCHAIN ANALYSIS")
print("="*120)

for trade in trades:
    estimated_level = estimate_level(trade['size'])

    # Start new chain if:
    # 1. Level 0 (small size)
    # 2. Previous chain ended (became profitable)
    # 3. First trade
    if current_chain is None or estimated_level == 0:
        # Check if we should close previous chain
        if current_chain is not None:
            cumulative_pnl = sum(t['pnl'] for t in current_chain['trades'])
            if cumulative_pnl > 0:
                chain_id += 1
                chains.append(current_chain)
                current_chain = None

        # Start new chain only if level 0 or first trade
        if estimated_level == 0 or current_chain is None:
            chain_id += 1
            current_chain = {
                'chain_id': f'CHAIN_{chain_id}',
                'trades': [],
                'start_time': trade['time'],
                'cumulative_pnl': 0
            }

    # Add trade to current chain
    trade['chain_id'] = current_chain['chain_id']
    trade['estimated_level'] = estimated_level
    current_chain['trades'].append(trade)
    current_chain['cumulative_pnl'] += trade['pnl']

    # Check if chain should end (became profitable)
    if current_chain['cumulative_pnl'] > 0 and trade['pnl'] > 0:
        chains.append(current_chain)
        current_chain = None

# Add final chain if still open
if current_chain is not None:
    chains.append(current_chain)

# Print results
for chain in chains:
    print(f"\n{chain['chain_id']}: Started {chain['start_time']}")
    print(f"  Cumulative PnL: ${chain['cumulative_pnl']:.2f}")
    print(f"  Trades: {len(chain['trades'])}")
    print("-"*120)

    for trade in chain['trades']:
        status = "WIN" if trade['pnl'] > 0 else "LOSS" if trade['pnl'] < 0 else "OPEN"
        print(f"  #{trade['id']:2} | {trade['time']:15} | {trade['symbol']:12} | "
              f"{trade['dir']:5} | Lvl {trade['estimated_level']} | "
              f"${trade['size']:6.2f} | PnL: ${trade['pnl']:7.2f} | {status}")

print(f"\n{'='*120}")
print(f"TOTAL CHAINS: {len(chains)}")
print(f"{'='*120}\n")
