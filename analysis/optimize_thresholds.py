#!/usr/bin/env python3
"""
Threshold Optimization via Grid Search
=======================================
Tests ~3,000 threshold configurations to find optimal RSI/BB/Z-score thresholds
that maximize coverage of 226 10%+ movers with good directional accuracy.

Grid Search Parameters:
  - RSI thresholds: SHORT [55, 60, 65, 70, 75, 80], LONG [20, 25, 30, 35, 40, 45]
  - BB%B thresholds: SHORT [0.6, 0.7, 0.8, 0.9], LONG [0.1, 0.2, 0.3, 0.4]
  - Z-score thresholds: SHORT [0.5, 1.0, 1.5, 2.0], LONG [-2.0, -1.5, -1.0, -0.5]

Total combinations: 6 * 6 * 4 * 4 * 4 * 4 = 9,216 configs

Output: threshold_optimization_results.json

Usage:
  python analysis/optimize_thresholds.py
  python analysis/optimize_thresholds.py --input custom_precursors.json
  python analysis/optimize_thresholds.py --top 20  # save top 20 configs
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ─── GRID SEARCH PARAMETERS ──────────────────────────────────────────────────

RSI_SHORT_THRESHOLDS = [55, 60, 65, 70, 75, 80]
RSI_LONG_THRESHOLDS = [20, 25, 30, 35, 40, 45]

BB_SHORT_THRESHOLDS = [0.6, 0.7, 0.8, 0.9]
BB_LONG_THRESHOLDS = [0.1, 0.2, 0.3, 0.4]

ZSCORE_SHORT_THRESHOLDS = [0.5, 1.0, 1.5, 2.0]
ZSCORE_LONG_THRESHOLDS = [-2.0, -1.5, -1.0, -0.5]

# ─── CURRENT BOT CONFIG (BASELINE) ───────────────────────────────────────────

BASELINE_CONFIG = {
    'rsi_short': 75,
    'rsi_long': 25,
    'bb_short': 0.8,
    'bb_long': 0.2,
    'z_short': 1.5,
    'z_long': -1.5
}

# ─── THRESHOLD TESTING FUNCTIONS ─────────────────────────────────────────────

def test_threshold_config(config, precursor_data):
    """
    Test a threshold configuration against all movers.

    For each mover:
      - Check if ANY of the 6 precursor candles meet thresholds
      - If yes: count as triggered, check if direction matches
      - Track: coverage %, direction accuracy %

    Returns:
      {
        'coverage_pct': float,
        'direction_accuracy': float,
        'triggered_count': int,
        'correct_direction_count': int,
        'config': dict
      }
    """
    triggered = 0
    correct_direction = 0
    total_movers = len(precursor_data)

    for mover in precursor_data:
        actual_direction = mover['move_metadata']['direction']
        symbol = mover['symbol']

        # Check each precursor candle
        for candle in mover.get('precursor_candles', []):
            rsi = candle.get('rsi')
            bb_pct_b = candle.get('bb_pct_b')
            zscore = candle.get('zscore')

            # Skip if any indicator is missing
            if rsi is None or bb_pct_b is None or zscore is None:
                continue

            # SHORT signal conditions
            short_signal = (
                rsi > config['rsi_short'] and
                bb_pct_b > config['bb_short'] and
                zscore > config['z_short']
            )

            # LONG signal conditions
            long_signal = (
                rsi < config['rsi_long'] and
                bb_pct_b < config['bb_long'] and
                zscore < config['z_long']
            )

            # If either signal triggered
            if short_signal or long_signal:
                triggered += 1
                predicted = "DOWN" if short_signal else "UP"

                if predicted == actual_direction:
                    correct_direction += 1

                break  # Stop at first trigger for this mover

    # Calculate metrics
    coverage_pct = (triggered / total_movers * 100) if total_movers > 0 else 0
    direction_accuracy = (correct_direction / triggered * 100) if triggered > 0 else 0

    return {
        'coverage_pct': round(coverage_pct, 2),
        'direction_accuracy': round(direction_accuracy, 2),
        'triggered_count': triggered,
        'correct_direction_count': correct_direction,
        'total_movers': total_movers,
        'config': config
    }


def generate_all_configs():
    """Generate all possible threshold configurations"""
    configs = []

    for rsi_s, rsi_l, bb_s, bb_l, z_s, z_l in product(
        RSI_SHORT_THRESHOLDS,
        RSI_LONG_THRESHOLDS,
        BB_SHORT_THRESHOLDS,
        BB_LONG_THRESHOLDS,
        ZSCORE_SHORT_THRESHOLDS,
        ZSCORE_LONG_THRESHOLDS
    ):
        configs.append({
            'rsi_short': rsi_s,
            'rsi_long': rsi_l,
            'bb_short': bb_s,
            'bb_long': bb_l,
            'z_short': z_s,
            'z_long': z_l
        })

    return configs


def load_precursor_data(filepath):
    """Load precursor data from JSON file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['movers']


def save_results(results, filepath, top_n=50):
    """Save optimization results to JSON file"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Sort by combined score (coverage + accuracy)
    results_sorted = sorted(
        results,
        key=lambda x: x['coverage_pct'] + x['direction_accuracy'],
        reverse=True
    )

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_configs_tested': len(results),
            'baseline_config': BASELINE_CONFIG,
            'top_configs': results_sorted[:top_n],
            'all_results': results_sorted  # Save all for further analysis
        }, f, indent=2)

    print(f"\n✓ Results saved to: {filepath}")
    print(f"✓ Top {top_n} configurations included")


def print_progress(idx, total, elapsed, estimated_remaining):
    """Print progress bar with time estimates"""
    pct = (idx / total * 100) if total > 0 else 0
    bar_length = 50
    filled = int(bar_length * idx / total)
    bar = '█' * filled + '░' * (bar_length - filled)

    elapsed_str = f"{elapsed:.0f}s"
    remaining_str = f"{estimated_remaining:.0f}s" if estimated_remaining > 0 else "calculating..."

    print(f"\r[{bar}] {idx:,}/{total:,} ({pct:.1f}%) | Elapsed: {elapsed_str} | ETA: {remaining_str}", end='', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Grid search threshold optimization')
    parser.add_argument('--input', default='226_movers_precursors.json', help='Input precursors JSON file')
    parser.add_argument('--output', default='threshold_optimization_results.json', help='Output filename')
    parser.add_argument('--top', type=int, default=50, help='Number of top configs to highlight')
    args = parser.parse_args()

    # Convert relative paths
    input_path = Path(__file__).parent / args.input
    output_path = Path(__file__).parent / args.output

    print("=" * 80)
    print("THRESHOLD OPTIMIZATION VIA GRID SEARCH")
    print("=" * 80)

    # Load precursor data
    print(f"\nLoading precursor data from: {input_path}")
    precursor_data = load_precursor_data(input_path)
    print(f"Loaded {len(precursor_data)} movers with precursor data")

    # Generate all configurations
    print("\nGenerating threshold configurations...")
    all_configs = generate_all_configs()
    total_configs = len(all_configs)
    print(f"Generated {total_configs:,} configurations to test\n")

    # Print grid search parameters
    print("Grid Search Parameters:")
    print(f"  RSI SHORT:   {RSI_SHORT_THRESHOLDS}")
    print(f"  RSI LONG:    {RSI_LONG_THRESHOLDS}")
    print(f"  BB SHORT:    {BB_SHORT_THRESHOLDS}")
    print(f"  BB LONG:     {BB_LONG_THRESHOLDS}")
    print(f"  Z SHORT:     {ZSCORE_SHORT_THRESHOLDS}")
    print(f"  Z LONG:      {ZSCORE_LONG_THRESHOLDS}")
    print(f"\nTotal combinations: {total_configs:,}")

    print("\n" + "=" * 80)
    print("BASELINE CONFIGURATION (CURRENT BOT)")
    print("=" * 80)
    baseline_result = test_threshold_config(BASELINE_CONFIG, precursor_data)
    print(f"Coverage:          {baseline_result['coverage_pct']:.2f}%")
    print(f"Direction Accuracy: {baseline_result['direction_accuracy']:.2f}%")
    print(f"Triggered:         {baseline_result['triggered_count']}/{baseline_result['total_movers']}")
    print(f"Correct Direction:  {baseline_result['correct_direction_count']}/{baseline_result['triggered_count']}")

    # Test all configurations
    print("\n" + "=" * 80)
    print("TESTING ALL CONFIGURATIONS")
    print("=" * 80)

    results = []
    start_time = time.time()

    for idx, config in enumerate(all_configs, 1):
        result = test_threshold_config(config, precursor_data)
        results.append(result)

        # Progress update every 100 configs
        if idx % 100 == 0 or idx == total_configs:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = (total_configs - idx) / rate if rate > 0 else 0
            print_progress(idx, total_configs, elapsed, remaining)

    print()  # New line after progress bar
    elapsed = time.time() - start_time

    # Print summary
    print("\n" + "=" * 80)
    print("OPTIMIZATION SUMMARY")
    print("=" * 80)
    print(f"Total configurations tested:  {len(results):,}")
    print(f"Elapsed time:                 {elapsed:.1f} seconds")
    print(f"Average per config:           {elapsed/len(results)*1000:.1f} ms")

    # Find best configurations
    results_sorted = sorted(
        results,
        key=lambda x: x['coverage_pct'] + x['direction_accuracy'],
        reverse=True
    )

    print("\n" + "=" * 80)
    print(f"TOP {min(10, len(results_sorted))} CONFIGURATIONS")
    print("=" * 80)
    print(f"{'Rank':<6} {'Coverage':<10} {'Accuracy':<10} {'Triggered':<12} {'Correct':<10} {'Combined':<10} {'Config'}")
    print("-" * 120)

    for idx, result in enumerate(results_sorted[:10], 1):
        config = result['config']
        combined_score = result['coverage_pct'] + result['direction_accuracy']

        config_str = f"RSI:{config['rsi_short']}/{config['rsi_long']} BB:{config['bb_short']:.1f}/{config['bb_long']:.1f} Z:{config['z_short']:.1f}/{config['z_long']:.1f}"

        print(f"#{idx:<5} {result['coverage_pct']:>6.2f}%   {result['direction_accuracy']:>6.2f}%   "
              f"{result['triggered_count']:>3}/{result['total_movers']:<4}   "
              f"{result['correct_direction_count']:>3}/{result['triggered_count']:<4}   "
              f"{combined_score:>6.1f}      {config_str}")

    # Compare to baseline
    print("\n" + "=" * 80)
    print("IMPROVEMENT OVER BASELINE")
    print("=" * 80)
    best_result = results_sorted[0]
    coverage_improvement = best_result['coverage_pct'] - baseline_result['coverage_pct']
    accuracy_improvement = best_result['direction_accuracy'] - baseline_result['direction_accuracy']

    print(f"Best Config Coverage:   {best_result['coverage_pct']:.2f}% (Baseline: {baseline_result['coverage_pct']:.2f}%)")
    print(f"Coverage Improvement:   {coverage_improvement:+.2f}pp")
    print(f"Best Config Accuracy:   {best_result['direction_accuracy']:.2f}% (Baseline: {baseline_result['direction_accuracy']:.2f}%)")
    print(f"Accuracy Improvement:   {accuracy_improvement:+.2f}pp")

    # Distribution analysis
    print("\n" + "=" * 80)
    print("DISTRIBUTION ANALYSIS")
    print("=" * 80)

    coverage_ranges = {
        "0-20%": 0,
        "20-40%": 0,
        "40-60%": 0,
        "60-80%": 0,
        "80-100%": 0
    }

    accuracy_ranges = {
        "0-40%": 0,
        "40-50%": 0,
        "50-60%": 0,
        "60-70%": 0,
        "70-100%": 0
    }

    for result in results:
        cov = result['coverage_pct']
        acc = result['direction_accuracy']

        if cov < 20:
            coverage_ranges["0-20%"] += 1
        elif cov < 40:
            coverage_ranges["20-40%"] += 1
        elif cov < 60:
            coverage_ranges["40-60%"] += 1
        elif cov < 80:
            coverage_ranges["60-80%"] += 1
        else:
            coverage_ranges["80-100%"] += 1

        if acc < 40:
            accuracy_ranges["0-40%"] += 1
        elif acc < 50:
            accuracy_ranges["40-50%"] += 1
        elif acc < 60:
            accuracy_ranges["50-60%"] += 1
        elif acc < 70:
            accuracy_ranges["60-70%"] += 1
        else:
            accuracy_ranges["70-100%"] += 1

    print("\nCoverage Distribution:")
    for range_name, count in coverage_ranges.items():
        pct = (count / len(results) * 100) if results else 0
        bar = '█' * int(pct / 2)
        print(f"  {range_name:<12} {count:>5} ({pct:>5.1f}%) {bar}")

    print("\nAccuracy Distribution:")
    for range_name, count in accuracy_ranges.items():
        pct = (count / len(results) * 100) if results else 0
        bar = '█' * int(pct / 2)
        print(f"  {range_name:<12} {count:>5} ({pct:>5.1f}%) {bar}")

    # Save results
    save_results(results, output_path, args.top)

    print("\n✓ Optimization complete!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
