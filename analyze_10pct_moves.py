#!/usr/bin/env python3
"""
Analyze 10%+ price movements across all Binance USDT-M Futures symbols
Uses 1-minute klines with sliding 60-minute window
"""
import httpx
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Tuple

BASE_URL = "https://fapi.binance.com"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

def get_all_usdt_symbols() -> List[str]:
    """Get all USDT-M Futures trading pairs with retry logic"""
    print("Fetching all USDT-M Futures symbols...")

    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(f"{BASE_URL}/fapi/v1/exchangeInfo")
                resp.raise_for_status()
                data = resp.json()

                symbols = []
                for s in data['symbols']:
                    if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                        symbols.append(s['symbol'])

                print(f"Found {len(symbols)} active USDT pairs")
                return symbols

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"Error fetching symbols (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY)
            else:
                raise

    return []

def get_klines(symbol: str, days: int = 7, client: httpx.Client = None) -> List[List]:
    """
    Fetch 1-minute klines for the last N days with retry logic
    Returns list of [open_time, open, high, low, close, volume, ...]
    """
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)

    all_klines = []
    current_start = start_time

    # Use provided client or create temporary one
    should_close = False
    if client is None:
        client = httpx.Client(timeout=60.0)
        should_close = True

    try:
        while current_start < end_time:
            for attempt in range(MAX_RETRIES):
                try:
                    params = {
                        "symbol": symbol,
                        "interval": "1m",
                        "startTime": current_start,
                        "endTime": end_time,
                        "limit": 1500  # Max per request
                    }

                    resp = client.get(f"{BASE_URL}/fapi/v1/klines", params=params)
                    resp.raise_for_status()
                    klines = resp.json()

                    if not klines:
                        return all_klines  # No more data

                    all_klines.extend(klines)

                    # Update start time to last kline's close time + 1
                    current_start = klines[-1][6] + 1  # Close time + 1ms

                    # Rate limit protection
                    time.sleep(0.15)
                    break  # Success, exit retry loop

                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout) as e:
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (attempt + 1)
                        time.sleep(wait_time)
                    else:
                        print(f"  ✗ {symbol}: Network error after {MAX_RETRIES} attempts")
                        return []
                except Exception as e:
                    print(f"  ✗ {symbol}: {type(e).__name__}")
                    return []

        return all_klines

    finally:
        if should_close:
            client.close()

def find_10pct_moves(klines: List[List]) -> List[Tuple[int, float, float, float]]:
    """
    Find all 60-minute windows with 10%+ price movement
    Returns list of (timestamp, low, high, move_pct)
    """
    if len(klines) < 60:
        return []

    moves = []

    # Sliding window of 60 candles (60 minutes)
    for i in range(len(klines) - 59):
        window = klines[i:i+60]

        # Get high and low within this 60-minute window
        window_high = max(float(k[2]) for k in window)  # High price
        window_low = min(float(k[3]) for k in window)   # Low price

        # Calculate percentage move
        if window_low > 0:
            move_pct = ((window_high - window_low) / window_low) * 100

            if move_pct >= 10.0:
                timestamp = window[0][0]  # Open time of first candle
                moves.append((timestamp, window_low, window_high, move_pct))

    return moves

def analyze_all_symbols(symbols: List[str], days: int = 7) -> Dict[str, List[Tuple]]:
    """
    Analyze all symbols for 10%+ moves using persistent HTTP client
    Returns dict of {symbol: [(timestamp, low, high, move_pct), ...]}
    """
    results = {}
    total_symbols = len(symbols)
    errors = 0
    analyzed = 0

    print(f"\nAnalyzing {total_symbols} symbols for 10%+ moves in the last {days} days...")
    print("This may take 10-20 minutes depending on network speed...\n")

    start_time = time.time()

    # Use persistent client for all requests
    with httpx.Client(timeout=60.0) as client:
        for idx, symbol in enumerate(symbols, 1):
            klines = get_klines(symbol, days, client)

            if not klines:
                errors += 1
                continue

            analyzed += 1
            moves = find_10pct_moves(klines)

            if moves:
                results[symbol] = moves
                print(f"  ✓ {symbol}: {len(moves)} instances of 10%+ moves")

            # Progress update every 25 symbols
            if idx % 25 == 0:
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                remaining = (total_symbols - idx) / rate if rate > 0 else 0
                print(f"\nProgress: {idx}/{total_symbols} ({idx/total_symbols*100:.1f}%) | "
                      f"Analyzed: {analyzed} | Errors: {errors} | "
                      f"ETA: {remaining/60:.1f} min\n")

    print(f"\nAnalysis complete: {analyzed} symbols analyzed, {errors} errors")
    return results

def print_analysis(results: Dict[str, List[Tuple]], days: int = 7):
    """Print analysis results"""
    if not results:
        print("\nNo 10%+ moves found in the analyzed period.")
        return

    # Sort by number of occurrences
    sorted_results = sorted(results.items(), key=lambda x: len(x[1]), reverse=True)

    print("\n" + "="*80)
    print("ANALYSIS: 10%+ Price Moves in 1-Hour Windows (Last 7 Days)")
    print("="*80)

    # Summary statistics
    total_moves = sum(len(moves) for moves in results.values())
    total_symbols_with_moves = len(results)
    avg_moves_per_day = total_moves / days

    print(f"\nSUMMARY:")
    print(f"  Total symbols with 10%+ moves: {total_symbols_with_moves}")
    print(f"  Total 10%+ move instances: {total_moves}")
    print(f"  Average 10%+ moves per day (all pairs): {avg_moves_per_day:.1f}")
    print(f"  Average moves per symbol: {total_moves / total_symbols_with_moves:.1f}")

    # Top 20 symbols by frequency
    print(f"\nTOP 20 SYMBOLS BY FREQUENCY OF 10%+ MOVES:")
    print(f"{'Symbol':<15} {'Count':<8} {'Avg/Day':<10} {'Max Move':<12}")
    print("-" * 60)

    for symbol, moves in sorted_results[:20]:
        count = len(moves)
        avg_per_day = count / days
        max_move = max(m[3] for m in moves)
        print(f"{symbol:<15} {count:<8} {avg_per_day:<10.2f} {max_move:<12.2f}%")

    # Distribution analysis
    print(f"\nDISTRIBUTION OF 10%+ MOVES:")
    move_ranges = {
        "10-15%": 0,
        "15-20%": 0,
        "20-30%": 0,
        "30-50%": 0,
        "50%+": 0
    }

    for moves in results.values():
        for _, _, _, move_pct in moves:
            if move_pct < 15:
                move_ranges["10-15%"] += 1
            elif move_pct < 20:
                move_ranges["15-20%"] += 1
            elif move_pct < 30:
                move_ranges["20-30%"] += 1
            elif move_pct < 50:
                move_ranges["30-50%"] += 1
            else:
                move_ranges["50%+"] += 1

    for range_name, count in move_ranges.items():
        pct = (count / total_moves * 100) if total_moves > 0 else 0
        print(f"  {range_name:<10} {count:>6} ({pct:>5.1f}%)")

    # Recent movers (last 24 hours)
    print(f"\nRECENT MOVERS (Last 24 Hours):")
    now = int(time.time() * 1000)
    last_24h = now - (24 * 60 * 60 * 1000)

    recent_moves = []
    for symbol, moves in results.items():
        for timestamp, low, high, move_pct in moves:
            if timestamp >= last_24h:
                recent_moves.append((symbol, timestamp, low, high, move_pct))

    recent_moves.sort(key=lambda x: x[4], reverse=True)  # Sort by move %

    if recent_moves:
        print(f"{'Symbol':<15} {'Time':<20} {'Low':<12} {'High':<12} {'Move %':<10}")
        print("-" * 80)
        for symbol, ts, low, high, move_pct in recent_moves[:15]:
            dt = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M')
            print(f"{symbol:<15} {dt:<20} {low:<12.6f} {high:<12.6f} {move_pct:<10.2f}%")
    else:
        print("  No 10%+ moves in the last 24 hours")

    print("\n" + "="*80)

def main():
    """Main execution"""
    start_time = time.time()

    try:
        # Get all symbols
        symbols = get_all_usdt_symbols()

        # Analyze for 10%+ moves
        days = 7
        results = analyze_all_symbols(symbols, days)

        # Print analysis
        print_analysis(results, days)

        elapsed = time.time() - start_time
        print(f"\nAnalysis completed in {elapsed:.1f} seconds")

    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
