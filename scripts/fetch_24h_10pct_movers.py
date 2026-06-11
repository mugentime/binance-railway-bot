#!/usr/bin/env python3
"""
Fetch all 10%+ price movers on Binance USDT-M Futures in the last 24 hours
Checks ALL 500+ trading pairs
"""
import httpx
import time
from datetime import datetime
import sys
import json

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_URL = "https://fapi.binance.com"
MAX_RETRIES = 3
RETRY_DELAY = 2

def get_all_usdt_symbols():
    """Get all USDT-M Futures trading pairs"""
    print("Fetching all USDT-M Futures symbols...")

    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(f"{BASE_URL}/fapi/v1/exchangeInfo")
                resp.raise_for_status()
                data = resp.json()

                symbols = [s['symbol'] for s in data['symbols']
                          if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']

                print(f"Found {len(symbols)} active USDT pairs\n")
                return symbols

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"Retry {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(RETRY_DELAY)
            else:
                raise
    return []

def get_24h_ticker_data():
    """Get 24-hour price change data for all symbols"""
    print("Fetching 24-hour ticker data for all symbols...")

    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(f"{BASE_URL}/fapi/v1/ticker/24hr")
                resp.raise_for_status()
                data = resp.json()

                print(f"Retrieved data for {len(data)} symbols\n")
                return data

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"Retry {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(RETRY_DELAY)
            else:
                raise
    return []

def find_10pct_movers(ticker_data, min_pct=10.0):
    """Find all symbols with 10%+ price change in last 24h"""
    movers = []

    for ticker in ticker_data:
        try:
            symbol = ticker['symbol']
            price_change_pct = float(ticker['priceChangePercent'])
            last_price = float(ticker['lastPrice'])
            volume = float(ticker['volume'])
            quote_volume = float(ticker['quoteVolume'])
            high = float(ticker['highPrice'])
            low = float(ticker['lowPrice'])

            # Calculate actual high-low range percentage
            if low > 0:
                range_pct = ((high - low) / low) * 100
            else:
                range_pct = 0

            # Check if either price change or range exceeds threshold
            if abs(price_change_pct) >= min_pct or range_pct >= min_pct:
                movers.append({
                    'symbol': symbol,
                    'price_change_pct': price_change_pct,
                    'range_pct': range_pct,
                    'last_price': last_price,
                    'high': high,
                    'low': low,
                    'volume': volume,
                    'quote_volume': quote_volume,
                    'num_trades': int(ticker.get('count', 0))
                })
        except (ValueError, KeyError) as e:
            continue

    return movers

def print_movers(movers, min_pct=10.0):
    """Print formatted list of movers"""
    if not movers:
        print(f"\nNo symbols with {min_pct}%+ moves found in the last 24 hours.")
        return

    # Sort by absolute price change
    movers_sorted = sorted(movers, key=lambda x: abs(x['price_change_pct']), reverse=True)

    print("="*120)
    print(f"24-HOUR MOVERS: {len(movers)} symbols with {min_pct}%+ price movement")
    print("="*120)
    print()

    # Summary stats
    up_movers = [m for m in movers if m['price_change_pct'] > 0]
    down_movers = [m for m in movers if m['price_change_pct'] < 0]

    print(f"SUMMARY:")
    print(f"  Total movers: {len(movers)}")
    print(f"  Up {min_pct}%+: {len(up_movers)}")
    print(f"  Down {min_pct}%+: {len(down_movers)}")
    print()

    # Print detailed table
    print(f"{'Symbol':<15} {'24h %':<10} {'Range %':<10} {'Last Price':<15} {'High':<15} {'Low':<15} {'Volume (USDT)':<18} {'Trades':<10}")
    print("-"*120)

    for mover in movers_sorted:
        symbol = mover['symbol']
        pct = mover['price_change_pct']
        range_pct = mover['range_pct']
        price = mover['last_price']
        high = mover['high']
        low = mover['low']
        quote_vol = mover['quote_volume']
        trades = mover['num_trades']

        # Format numbers
        if price < 0.01:
            price_str = f"{price:.8f}"
            high_str = f"{high:.8f}"
            low_str = f"{low:.8f}"
        elif price < 1:
            price_str = f"{price:.6f}"
            high_str = f"{high:.6f}"
            low_str = f"{low:.6f}"
        else:
            price_str = f"{price:.4f}"
            high_str = f"{high:.4f}"
            low_str = f"{low:.4f}"

        quote_vol_str = f"${quote_vol:,.0f}" if quote_vol > 0 else "N/A"

        print(f"{symbol:<15} {pct:>8.2f}% {range_pct:>8.2f}% {price_str:<15} {high_str:<15} {low_str:<15} {quote_vol_str:<18} {trades:<10}")

    print("\n" + "="*120)

    # Distribution analysis
    print("\nDISTRIBUTION BY PRICE CHANGE:")
    ranges = {
        "10-15%": 0,
        "15-20%": 0,
        "20-30%": 0,
        "30-50%": 0,
        "50%+": 0
    }

    for mover in movers:
        abs_pct = abs(mover['price_change_pct'])
        if abs_pct < 15:
            ranges["10-15%"] += 1
        elif abs_pct < 20:
            ranges["15-20%"] += 1
        elif abs_pct < 30:
            ranges["20-30%"] += 1
        elif abs_pct < 50:
            ranges["30-50%"] += 1
        else:
            ranges["50%+"] += 1

    for range_name, count in ranges.items():
        pct_of_total = (count / len(movers) * 100) if len(movers) > 0 else 0
        print(f"  {range_name:<10} {count:>4} ({pct_of_total:>5.1f}%)")

    # Top gainers and losers
    print("\nTOP 10 GAINERS:")
    gainers = sorted(up_movers, key=lambda x: x['price_change_pct'], reverse=True)[:10]
    for i, m in enumerate(gainers, 1):
        print(f"  {i:2d}. {m['symbol']:<15} +{m['price_change_pct']:.2f}%")

    print("\nTOP 10 DECLINERS:")
    decliners = sorted(down_movers, key=lambda x: x['price_change_pct'])[:10]
    for i, m in enumerate(decliners, 1):
        print(f"  {i:2d}. {m['symbol']:<15} {m['price_change_pct']:.2f}%")

def save_to_json(movers, filename="../docs/trades_export/24h_movers.json"):
    """Save movers data to JSON file"""
    import os
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'total_movers': len(movers),
            'movers': movers
        }, f, indent=2)

    print(f"\nData saved to: {filename}")

def main():
    """Main execution"""
    start_time = time.time()

    try:
        # Get all symbols
        symbols = get_all_usdt_symbols()
        print(f"Checking {len(symbols)} symbols for 10%+ moves in the last 24 hours...\n")

        # Get 24h ticker data (much faster than klines)
        ticker_data = get_24h_ticker_data()

        # Find movers
        movers = find_10pct_movers(ticker_data, min_pct=10.0)

        # Print results
        print_movers(movers, min_pct=10.0)

        # Save to JSON
        save_to_json(movers)

        elapsed = time.time() - start_time
        print(f"\nAnalysis completed in {elapsed:.1f} seconds")
        print(f"Checked all {len(symbols)} pairs on Binance USDT-M Futures")

    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
