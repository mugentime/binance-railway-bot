#!/usr/bin/env python3
"""
Timing Window Analysis - Additional Phase 2 Analysis

Analyzes the optimal lookback window for precursor indicators:
- Tests 1, 3, and 6 candle windows (5, 15, 30 minutes)
- Determines if earlier signals are more predictive
- Identifies optimal timing for entry decisions

Input: analysis/226_movers_precursors.json (from Phase 1)
Output: analysis/timing_window_results.json
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Windows console encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def load_precursor_data(filepath):
    """Load precursor data from Phase 1"""
    print(f"Loading precursor data from: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    movers = data['movers']
    print(f"✓ Loaded {len(movers)} movers with precursor data")
    return movers


def test_window(movers, config, window_size):
    """
    Test a configuration with a specific window size

    Args:
        movers: List of mover data with precursor candles
        config: Threshold configuration
        window_size: Number of candles to check (1, 3, or 6)

    Returns:
        Dict with results
    """
    triggered = 0
    correct_direction = 0

    for mover in movers:
        actual_direction = mover['move_metadata']['direction']
        precursors = mover['precursor_candles']

        # Check only the last N candles
        candles_to_check = precursors[-window_size:]

        signal_found = False

        for candle in candles_to_check:
            rsi = candle.get('rsi')
            bb_pct_b = candle.get('bb_pct_b')
            zscore = candle.get('zscore')

            if rsi is None or bb_pct_b is None or zscore is None:
                continue

            # Check SHORT signal
            short_signal = (
                rsi > config['rsi_short'] and
                bb_pct_b > config['bb_short'] and
                zscore > config['z_short']
            )

            # Check LONG signal
            long_signal = (
                rsi < config['rsi_long'] and
                bb_pct_b < config['bb_long'] and
                zscore < config['z_long']
            )

            if short_signal or long_signal:
                triggered += 1
                predicted = 'DOWN' if short_signal else 'UP'

                if predicted == actual_direction:
                    correct_direction += 1

                signal_found = True
                break

        if signal_found:
            continue

    total = len(movers)
    coverage = (triggered / total * 100) if total > 0 else 0
    accuracy = (correct_direction / triggered * 100) if triggered > 0 else 0

    return {
        'window_size_candles': window_size,
        'window_size_minutes': window_size * 5,
        'coverage_pct': round(coverage, 2),
        'direction_accuracy': round(accuracy, 2),
        'triggered_count': triggered,
        'correct_direction_count': correct_direction,
        'total_movers': total
    }


def main():
    """Main execution function"""
    print("="*80)
    print("Timing Window Analysis")
    print("="*80)
    print()

    # Paths
    analysis_dir = Path(__file__).parent
    precursor_data_path = analysis_dir / '226_movers_precursors.json'
    output_path = analysis_dir / 'timing_window_results.json'

    # Load data
    movers = load_precursor_data(precursor_data_path)

    # Load best configuration from optimization results
    opt_results_path = analysis_dir / 'threshold_optimization_results.json'
    with open(opt_results_path, 'r', encoding='utf-8') as f:
        opt_data = json.load(f)

    best_config = opt_data['top_configs'][0]['config']

    print(f"\nUsing best configuration from Phase 2:")
    print(f"  RSI: {best_config['rsi_short']}/{best_config['rsi_long']}")
    print(f"  BB: {best_config['bb_short']}/{best_config['bb_long']}")
    print(f"  Z: {best_config['z_short']}/{best_config['z_long']}")
    print()

    # Test different window sizes
    window_sizes = [1, 3, 6]  # 5, 15, 30 minutes
    results = []

    print("Testing different timing windows...")
    print("-"*80)

    for window_size in window_sizes:
        print(f"\nWindow: {window_size} candles ({window_size * 5} minutes)")

        result = test_window(movers, best_config, window_size)

        print(f"  Coverage: {result['coverage_pct']:.1f}% "
              f"({result['triggered_count']}/{result['total_movers']})")
        print(f"  Accuracy: {result['direction_accuracy']:.1f}% "
              f"({result['correct_direction_count']}/{result['triggered_count']})")

        results.append(result)

    # Analysis
    print("\n" + "="*80)
    print("TIMING WINDOW SUMMARY")
    print("="*80)

    best_window = max(results, key=lambda x: x['direction_accuracy'])

    print(f"\nBest window size: {best_window['window_size_candles']} candles "
          f"({best_window['window_size_minutes']} minutes)")
    print(f"  Coverage: {best_window['coverage_pct']:.1f}%")
    print(f"  Accuracy: {best_window['direction_accuracy']:.1f}%")

    # Determine optimal strategy
    print("\nRECOMMENDATION:")
    if best_window['window_size_candles'] == 1:
        print("  → Use IMMEDIATE precursor (1 candle / 5 min before)")
        print("  → Signals closer to move have better accuracy")
    elif best_window['window_size_candles'] == 3:
        print("  → Use MEDIUM window (3 candles / 15 min before)")
        print("  → Balanced approach between coverage and accuracy")
    else:
        print("  → Use FULL window (6 candles / 30 min before)")
        print("  → Maximum coverage with acceptable accuracy")

    # Save results
    output_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'configuration_tested': best_config,
        'window_sizes_tested': window_sizes,
        'results': results,
        'best_window': best_window
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n✓ Timing window results saved to: {output_path}")
    print()


if __name__ == '__main__':
    main()
