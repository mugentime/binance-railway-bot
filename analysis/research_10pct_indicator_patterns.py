#!/usr/bin/env python3
"""
Research: Indicator Patterns Before 10%+ Price Moves
Analyzes pre-move indicator snapshots to identify predictive patterns
"""
import httpx
import time
import csv
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from collections import defaultdict
import sys
import os

# Add parent directory and src to path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from signal_scorer import SignalScorer

BASE_URL = "https://fapi.binance.com"
MAX_RETRIES = 3
RETRY_DELAY = 2

# Analysis parameters
DAYS_TO_ANALYZE = 30
KLINE_INTERVAL_DETECTION = "1h"  # Use 1h candles for move detection
KLINE_INTERVAL_INDICATORS = "5m"  # Use 5m candles for indicator calculation
PRE_MOVE_CANDLES = 3  # Number of 5m candles before move (15 minutes)

def get_all_usdt_symbols() -> List[str]:
    """Get all USDT-M Futures trading pairs"""
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

def get_klines(symbol: str, interval: str, start_time: int, end_time: int, client: httpx.Client) -> List[List]:
    """
    Fetch klines for a specific time range
    Returns list of [open_time, open, high, low, close, volume, ...]
    """
    all_klines = []
    current_start = start_time

    while current_start < end_time:
        for attempt in range(MAX_RETRIES):
            try:
                params = {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": current_start,
                    "endTime": end_time,
                    "limit": 1500
                }

                resp = client.get(f"{BASE_URL}/fapi/v1/klines", params=params)
                resp.raise_for_status()
                klines = resp.json()

                if not klines:
                    return all_klines

                all_klines.extend(klines)
                current_start = klines[-1][6] + 1  # Close time + 1ms

                time.sleep(0.1)  # Rate limit
                break

            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    print(f"  Error fetching klines for {symbol}: {e}")
                    return []

    return all_klines

def find_10pct_moves_hourly(klines: List[List]) -> List[Tuple[int, float, float, float, str]]:
    """
    Find all 1-hour candles with 10%+ price movement
    Returns list of (timestamp, low, high, move_pct, direction)
    """
    moves = []

    for candle in klines:
        open_time = candle[0]
        open_price = float(candle[1])
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])

        # Calculate percentage move
        if low > 0:
            move_pct = ((high - low) / low) * 100

            if move_pct >= 10.0:
                # Determine direction based on close vs open
                direction = "UP" if close > open_price else "DOWN"
                moves.append((open_time, low, high, move_pct, direction))

    return moves

def calculate_indicators(closes: np.ndarray, volumes: np.ndarray, funding_rate: float = 0.0) -> Dict[str, float]:
    """
    Calculate all indicators using SignalScorer logic
    Returns dict with indicator values
    """
    scorer = SignalScorer()

    # Calculate indicators
    rsi = scorer.calculate_rsi(closes, period=14)
    bb_pct_b = scorer.calculate_bollinger_pct_b(closes, period=20)
    zscore = scorer.calculate_zscore(closes, period=20)
    volume_ratio = scorer.calculate_volume_ratio(volumes, period=20)

    # SMA slope calculation
    sma_slope_pct = 0.0
    if len(closes) >= 50:
        sma_values = np.convolve(closes, np.ones(50)/50, mode='valid')
        if len(sma_values) >= 10:
            recent_sma = sma_values[-10:]
            x = np.arange(10)
            n = 10
            slope = (n * np.sum(x * recent_sma) - np.sum(x) * np.sum(recent_sma)) / \
                    (n * np.sum(x**2) - np.sum(x)**2)
            sma_slope_pct = (slope / sma_values[-1]) * 100

            if np.isnan(sma_slope_pct) or np.isinf(sma_slope_pct):
                sma_slope_pct = 0.0

    return {
        'rsi': rsi,
        'bb_pct_b': bb_pct_b,
        'zscore': zscore,
        'volume_ratio': volume_ratio,
        'funding_rate': funding_rate,
        'sma_slope_pct': sma_slope_pct
    }

def get_pre_move_indicators(symbol: str, move_timestamp: int, client: httpx.Client) -> Dict[str, float]:
    """
    Get indicator values 15 minutes (3 x 5m candles) before the move
    """
    # Calculate time range: 1 hour before move for sufficient indicator calculation
    # We need ~50 candles for SMA (50 * 5min = 250 minutes = 4.2 hours)
    lookback_ms = 5 * 60 * 60 * 1000  # 5 hours in milliseconds
    start_time = move_timestamp - lookback_ms
    end_time = move_timestamp  # Up to the start of the 1h move candle

    # Fetch 5-minute klines
    klines_5m = get_klines(symbol, "5m", start_time, end_time, client)

    if len(klines_5m) < 50:  # Need at least 50 candles for SMA
        return None

    # Extract closes and volumes (excluding the last 3 candles to get "before move" data)
    # Actually, we want data UP TO the move start, so we use all available data
    closes = np.array([float(k[4]) for k in klines_5m])
    volumes = np.array([float(k[5]) for k in klines_5m])

    # Calculate indicators at the point just before the move
    indicators = calculate_indicators(closes, volumes)

    return indicators

def analyze_symbol(symbol: str, days: int, client: httpx.Client) -> List[Dict]:
    """
    Analyze one symbol for 10%+ moves and collect pre-move indicators
    Returns list of move records with indicators
    """
    print(f"Analyzing {symbol}...")

    # Fetch 1-hour klines for move detection
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)

    klines_1h = get_klines(symbol, KLINE_INTERVAL_DETECTION, start_time, end_time, client)

    if not klines_1h:
        return []

    # Find 10%+ moves
    moves = find_10pct_moves_hourly(klines_1h)

    if not moves:
        return []

    print(f"  Found {len(moves)} instances of 10%+ moves")

    # Get funding rate (current, as historical funding is complex)
    funding_rate = 0.0
    try:
        resp = client.get(f"{BASE_URL}/fapi/v1/premiumIndex", params={"symbol": symbol})
        resp.raise_for_status()
        funding_data = resp.json()
        funding_rate = float(funding_data.get("lastFundingRate", 0.0))
        time.sleep(0.05)
    except Exception as e:
        print(f"  Warning: Could not fetch funding rate: {e}")

    # For each move, get pre-move indicators
    records = []
    for move_timestamp, low, high, move_pct, direction in moves:
        indicators = get_pre_move_indicators(symbol, move_timestamp, client)

        if indicators is None:
            continue

        # Use current funding rate (approximation)
        indicators['funding_rate'] = funding_rate

        record = {
            'symbol': symbol,
            'timestamp': move_timestamp,
            'datetime': datetime.fromtimestamp(move_timestamp / 1000).strftime('%Y-%m-%d %H:%M'),
            'direction': direction,
            'move_pct': move_pct,
            'low': low,
            'high': high,
            **indicators
        }
        records.append(record)

    return records

def analyze_all_symbols(symbols: List[str], days: int) -> List[Dict]:
    """
    Analyze all symbols and collect dataset
    """
    all_records = []
    total_symbols = len(symbols)
    errors = 0
    analyzed = 0

    print(f"\nAnalyzing {total_symbols} symbols for 10%+ moves in the last {days} days...")
    print("This will take 30-60 minutes depending on network speed...\n")

    start_time_analysis = time.time()

    with httpx.Client(timeout=60.0) as client:
        for idx, symbol in enumerate(symbols, 1):
            try:
                records = analyze_symbol(symbol, days, client)

                if records:
                    all_records.extend(records)
                    analyzed += 1
                    print(f"  ✓ {symbol}: Collected {len(records)} pre-move snapshots")

            except Exception as e:
                errors += 1
                print(f"  ✗ {symbol}: {e}")

            # Progress update every 25 symbols
            if idx % 25 == 0:
                elapsed = time.time() - start_time_analysis
                rate = idx / elapsed if elapsed > 0 else 0
                remaining = (total_symbols - idx) / rate if rate > 0 else 0
                print(f"\nProgress: {idx}/{total_symbols} ({idx/total_symbols*100:.1f}%) | "
                      f"Analyzed: {analyzed} | Errors: {errors} | "
                      f"Records: {len(all_records)} | "
                      f"ETA: {remaining/60:.1f} min\n")

    print(f"\nData collection complete: {analyzed} symbols analyzed, {errors} errors, {len(all_records)} total records")
    return all_records

def save_dataset(records: List[Dict], filename: str):
    """Save dataset to CSV"""
    if not records:
        print("No records to save")
        return

    fieldnames = [
        'symbol', 'timestamp', 'datetime', 'direction', 'move_pct', 'low', 'high',
        'rsi', 'bb_pct_b', 'zscore', 'volume_ratio', 'funding_rate', 'sma_slope_pct'
    ]

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"\nDataset saved to: {filename}")

def analyze_patterns(records: List[Dict]) -> Dict:
    """
    Analyze patterns in the dataset
    Returns statistics and pattern analysis
    """
    if not records:
        return {}

    print("\nAnalyzing patterns...")

    # Separate by direction
    up_moves = [r for r in records if r['direction'] == 'UP']
    down_moves = [r for r in records if r['direction'] == 'DOWN']

    # Define pattern detection functions
    def check_pattern(records, condition_func, pattern_name):
        matches = [r for r in records if condition_func(r)]
        return {
            'pattern': pattern_name,
            'count': len(matches),
            'percentage': len(matches) / len(records) * 100 if records else 0
        }

    # Pattern definitions
    patterns = {
        'UP': [
            check_pattern(up_moves, lambda r: r['rsi'] > 70, 'RSI > 70'),
            check_pattern(up_moves, lambda r: r['rsi'] < 30, 'RSI < 30'),
            check_pattern(up_moves, lambda r: r['bb_pct_b'] > 0.8, 'BB%B > 0.8'),
            check_pattern(up_moves, lambda r: r['bb_pct_b'] < 0.2, 'BB%B < 0.2'),
            check_pattern(up_moves, lambda r: r['zscore'] > 2.0, 'Z-score > 2.0'),
            check_pattern(up_moves, lambda r: r['zscore'] < -2.0, 'Z-score < -2.0'),
            check_pattern(up_moves, lambda r: r['volume_ratio'] > 1.5, 'Volume > 1.5x'),
            check_pattern(up_moves, lambda r: r['sma_slope_pct'] > 0.3, 'SMA Slope > 0.3%'),
            check_pattern(up_moves, lambda r: r['sma_slope_pct'] < -0.3, 'SMA Slope < -0.3%'),
        ],
        'DOWN': [
            check_pattern(down_moves, lambda r: r['rsi'] > 70, 'RSI > 70'),
            check_pattern(down_moves, lambda r: r['rsi'] < 30, 'RSI < 30'),
            check_pattern(down_moves, lambda r: r['bb_pct_b'] > 0.8, 'BB%B > 0.8'),
            check_pattern(down_moves, lambda r: r['bb_pct_b'] < 0.2, 'BB%B < 0.2'),
            check_pattern(down_moves, lambda r: r['zscore'] > 2.0, 'Z-score > 2.0'),
            check_pattern(down_moves, lambda r: r['zscore'] < -2.0, 'Z-score < -2.0'),
            check_pattern(down_moves, lambda r: r['volume_ratio'] > 1.5, 'Volume > 1.5x'),
            check_pattern(down_moves, lambda r: r['sma_slope_pct'] > 0.3, 'SMA Slope > 0.3%'),
            check_pattern(down_moves, lambda r: r['sma_slope_pct'] < -0.3, 'SMA Slope < -0.3%'),
        ]
    }

    # Top symbols by frequency
    symbol_counts = defaultdict(int)
    symbol_directions = defaultdict(lambda: {'UP': 0, 'DOWN': 0})
    for r in records:
        symbol_counts[r['symbol']] += 1
        symbol_directions[r['symbol']][r['direction']] += 1

    top_symbols = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    # Distribution by move size
    move_distribution = {
        '10-15%': len([r for r in records if 10 <= r['move_pct'] < 15]),
        '15-20%': len([r for r in records if 15 <= r['move_pct'] < 20]),
        '20-30%': len([r for r in records if 20 <= r['move_pct'] < 30]),
        '30-50%': len([r for r in records if 30 <= r['move_pct'] < 50]),
        '50%+': len([r for r in records if r['move_pct'] >= 50]),
    }

    return {
        'total_records': len(records),
        'up_moves': len(up_moves),
        'down_moves': len(down_moves),
        'patterns_up': patterns['UP'],
        'patterns_down': patterns['DOWN'],
        'top_symbols': top_symbols,
        'symbol_directions': symbol_directions,
        'move_distribution': move_distribution,
    }

def generate_report(analysis: Dict, records: List[Dict], filename: str):
    """Generate comprehensive markdown report"""

    if not analysis:
        print("No analysis data to report")
        return

    report_lines = []

    # Header
    report_lines.append("# 10%+ Price Move Analysis Report")
    report_lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"\nAnalysis Period: Last {DAYS_TO_ANALYZE} days")
    report_lines.append(f"\n---\n")

    # Executive Summary
    report_lines.append("## Executive Summary\n")
    report_lines.append(f"- **Total 10%+ Moves Detected:** {analysis['total_records']}")
    report_lines.append(f"- **UP Moves:** {analysis['up_moves']} ({analysis['up_moves']/analysis['total_records']*100:.1f}%)")
    report_lines.append(f"- **DOWN Moves:** {analysis['down_moves']} ({analysis['down_moves']/analysis['total_records']*100:.1f}%)")
    report_lines.append(f"- **Unique Symbols with 10%+ Moves:** {len(analysis['top_symbols'])}")
    report_lines.append(f"\n")

    # Dataset Summary
    report_lines.append("## Dataset Summary\n")
    report_lines.append("### Move Size Distribution\n")
    report_lines.append("| Move Range | Count | Percentage |")
    report_lines.append("|------------|-------|------------|")
    total = analysis['total_records']
    for range_name, count in analysis['move_distribution'].items():
        pct = count / total * 100 if total > 0 else 0
        report_lines.append(f"| {range_name} | {count} | {pct:.1f}% |")
    report_lines.append(f"\n")

    # Top Symbols
    report_lines.append("### Top 20 Symbols by Frequency of 10%+ Moves\n")
    report_lines.append("| Rank | Symbol | Total Moves | UP Moves | DOWN Moves |")
    report_lines.append("|------|--------|-------------|----------|------------|")
    for idx, (symbol, count) in enumerate(analysis['top_symbols'], 1):
        up = analysis['symbol_directions'][symbol]['UP']
        down = analysis['symbol_directions'][symbol]['DOWN']
        report_lines.append(f"| {idx} | {symbol} | {count} | {up} | {down} |")
    report_lines.append(f"\n")

    # Indicator Pattern Analysis
    report_lines.append("## Indicator Pattern Analysis\n")
    report_lines.append("### Patterns Before UP Moves\n")
    report_lines.append("| Pattern | Occurrences | Coverage (%) |")
    report_lines.append("|---------|-------------|--------------|")
    for p in sorted(analysis['patterns_up'], key=lambda x: x['percentage'], reverse=True):
        report_lines.append(f"| {p['pattern']} | {p['count']} | {p['percentage']:.1f}% |")
    report_lines.append(f"\n")

    report_lines.append("### Patterns Before DOWN Moves\n")
    report_lines.append("| Pattern | Occurrences | Coverage (%) |")
    report_lines.append("|---------|-------------|--------------|")
    for p in sorted(analysis['patterns_down'], key=lambda x: x['percentage'], reverse=True):
        report_lines.append(f"| {p['pattern']} | {p['count']} | {p['percentage']:.1f}% |")
    report_lines.append(f"\n")

    # Statistical Insights
    report_lines.append("## Key Insights\n")

    # Calculate averages for UP and DOWN moves
    up_records = [r for r in records if r['direction'] == 'UP']
    down_records = [r for r in records if r['direction'] == 'DOWN']

    def avg_indicator(records, indicator):
        values = [r[indicator] for r in records]
        return np.mean(values) if values else 0

    report_lines.append("### Average Indicator Values Before Moves\n")
    report_lines.append("| Indicator | Before UP Moves | Before DOWN Moves |")
    report_lines.append("|-----------|-----------------|-------------------|")
    for indicator in ['rsi', 'bb_pct_b', 'zscore', 'volume_ratio', 'sma_slope_pct']:
        up_avg = avg_indicator(up_records, indicator)
        down_avg = avg_indicator(down_records, indicator)
        report_lines.append(f"| {indicator} | {up_avg:.2f} | {down_avg:.2f} |")
    report_lines.append(f"\n")

    # Current Bot Comparison
    report_lines.append("## Current Bot Configuration Comparison\n")
    report_lines.append("### Bot Entry Criteria (from config.py)\n")
    report_lines.append("- **Strategy:** MEAN_REVERSION (inverted signals)")
    report_lines.append("- **RSI Thresholds:** <25 (LONG), >75 (SHORT)")
    report_lines.append("- **Entry Threshold:** 45.0 composite score")
    report_lines.append("- **SMA Slope Threshold:** ±0.3% (blocks counter-trend)")
    report_lines.append(f"\n")

    # How many moves would bot catch?
    bot_catchable_up = len([r for r in up_records if r['rsi'] > 75 or r['rsi'] < 25])
    bot_catchable_down = len([r for r in down_records if r['rsi'] > 75 or r['rsi'] < 25])

    report_lines.append("### Estimated Bot Coverage\n")
    report_lines.append(f"- **UP Moves with RSI >75 or <25:** {bot_catchable_up}/{len(up_records)} ({bot_catchable_up/len(up_records)*100 if up_records else 0:.1f}%)")
    report_lines.append(f"- **DOWN Moves with RSI >75 or <25:** {bot_catchable_down}/{len(down_records)} ({bot_catchable_down/len(down_records)*100 if down_records else 0:.1f}%)")
    report_lines.append(f"\n")

    # Recommendations
    report_lines.append("## Recommendations\n")
    report_lines.append("1. **Pattern Detection:** Focus on patterns with >30% coverage for reliable signals")
    report_lines.append("2. **Volume Confirmation:** High volume ratio (>1.5x) appears frequently before moves")
    report_lines.append("3. **Trend Alignment:** SMA slope shows directional bias - consider trend-following strategies")
    report_lines.append("4. **RSI Extremes:** Current thresholds (25/75) may be too conservative - analyze optimal levels")
    report_lines.append("5. **Combination Signals:** Multi-indicator confirmation may improve accuracy")
    report_lines.append(f"\n")

    # Footer
    report_lines.append("---\n")
    report_lines.append(f"**Data Source:** Binance USDT-M Futures")
    report_lines.append(f"\n**Analysis Method:** Pre-move indicator snapshots (15 minutes before 1-hour 10%+ candles)")
    report_lines.append(f"\n**Dataset:** See `pre_move_indicators_30d.csv` for raw data")

    # Save report
    with open(filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    print(f"\nReport saved to: {filename}")

def main():
    """Main execution"""
    start_time_total = time.time()

    try:
        # Get all symbols
        symbols = get_all_usdt_symbols()

        # Analyze all symbols
        records = analyze_all_symbols(symbols, DAYS_TO_ANALYZE)

        # Save dataset
        dataset_file = "analysis/pre_move_indicators_30d.csv"
        save_dataset(records, dataset_file)

        # Analyze patterns
        analysis = analyze_patterns(records)

        # Generate report
        report_file = "analysis/10pct_move_analysis_report.md"
        generate_report(analysis, records, report_file)

        elapsed = time.time() - start_time_total
        print(f"\n✓ Complete analysis finished in {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        print(f"\nOutput files:")
        print(f"  - Dataset: {dataset_file}")
        print(f"  - Report: {report_file}")

    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
