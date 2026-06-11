#!/usr/bin/env python3
"""
Phase 3: Backtest Validation of Optimized Thresholds

Validates the top 10 configurations from Phase 2 against the historical
4,821-move dataset (pre_move_indicators_30d.csv) to assess:

1. Historical coverage: % of 4,821 moves that would trigger
2. Directional accuracy: % of triggers with correct direction prediction
3. False positive estimate: Expected daily triggers vs real moves
4. Comparison to 59-mover results to quantify overfitting

Output: analysis/backtest_validation_results.json
"""

import sys
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

# Windows console encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def load_historical_data(filepath):
    """Load the 4,821 historical moves with precursor indicators"""
    print(f"Loading historical data from: {filepath}")
    df = pd.read_csv(filepath)
    print(f"✓ Loaded {len(df)} historical moves")

    # Display columns to understand the data structure
    print(f"  Columns: {', '.join(df.columns.tolist())}")

    return df


def load_optimization_results(filepath):
    """Load top 10 configurations from Phase 2"""
    print(f"\nLoading optimization results from: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    top_configs = data['top_configs'][:10]  # Top 10 configurations
    print(f"✓ Loaded {len(top_configs)} top configurations")

    return top_configs, data['baseline_config']


def test_config_on_historical(df, config):
    """
    Test a single configuration against historical dataset

    Args:
        df: DataFrame with historical moves
        config: Dict with threshold configuration

    Returns:
        Dict with validation metrics
    """
    triggered = 0
    correct_direction = 0

    # Extract thresholds
    rsi_short = config['rsi_short']
    rsi_long = config['rsi_long']
    bb_short = config['bb_short']
    bb_long = config['bb_long']
    z_short = config['z_short']
    z_long = config['z_long']

    for idx, row in df.iterrows():
        # Get precursor indicators (assuming column names match)
        # Check if columns exist in the dataframe
        if 'rsi' not in df.columns:
            # Try alternative column names
            rsi_col = [c for c in df.columns if 'rsi' in c.lower()]
            bb_col = [c for c in df.columns if 'bb' in c.lower() or '%b' in c.lower()]
            z_col = [c for c in df.columns if 'zscore' in c.lower() or 'z_score' in c.lower()]

            if not rsi_col or not bb_col or not z_col:
                print(f"  ⚠ Warning: Could not find indicator columns")
                return None

            rsi = row[rsi_col[0]]
            bb_pct_b = row[bb_col[0]]
            zscore = row[z_col[0]]
        else:
            rsi = row.get('rsi')
            bb_pct_b = row.get('bb_pct_b') or row.get('bb%b') or row.get('bb_percent_b')
            zscore = row.get('zscore') or row.get('z_score')

        # Skip if any indicator is missing
        if pd.isna(rsi) or pd.isna(bb_pct_b) or pd.isna(zscore):
            continue

        # Get actual move direction
        # Try different possible column names
        direction_col = None
        if 'direction' in df.columns:
            direction_col = 'direction'
        elif 'move_direction' in df.columns:
            direction_col = 'move_direction'
        elif 'price_change_pct' in df.columns:
            actual_direction = 'UP' if row['price_change_pct'] > 0 else 'DOWN'
        elif 'change_pct' in df.columns:
            actual_direction = 'UP' if row['change_pct'] > 0 else 'DOWN'
        else:
            print(f"  ⚠ Warning: Could not find direction column")
            return None

        if direction_col:
            actual_direction = row[direction_col]

        # Check SHORT signal conditions
        short_signal = (rsi > rsi_short and bb_pct_b > bb_short and zscore > z_short)

        # Check LONG signal conditions
        long_signal = (rsi < rsi_long and bb_pct_b < bb_long and zscore < z_long)

        if short_signal or long_signal:
            triggered += 1
            predicted = 'DOWN' if short_signal else 'UP'

            if predicted == actual_direction:
                correct_direction += 1

    total_movers = len(df)
    coverage_pct = (triggered / total_movers * 100) if total_movers > 0 else 0
    direction_accuracy = (correct_direction / triggered * 100) if triggered > 0 else 0

    return {
        'coverage_pct': round(coverage_pct, 2),
        'direction_accuracy': round(direction_accuracy, 2),
        'triggered_count': triggered,
        'correct_direction_count': correct_direction,
        'total_movers': total_movers
    }


def estimate_false_positives(coverage_pct, avg_real_moves_per_day=160):
    """
    Estimate daily false positives based on coverage percentage

    Assumptions:
    - 100 trading pairs scanned
    - 5-minute interval (86400s / 300s = 288 scans per day per pair)
    - Total scans per day = 100 * 288 = 28,800
    - Real 10%+ moves per day ~160 (from historical data)

    Args:
        coverage_pct: Percentage of moves triggered (0-100)
        avg_real_moves_per_day: Average number of real 10%+ moves per day

    Returns:
        Dict with false positive estimates
    """
    scans_per_day = 100 * 288  # 28,800 scans per day
    trigger_rate = coverage_pct / 100
    expected_triggers_per_day = scans_per_day * trigger_rate

    # Assume we catch coverage_pct of real moves
    expected_real_triggers = avg_real_moves_per_day * trigger_rate
    expected_false_positives = expected_triggers_per_day - expected_real_triggers

    return {
        'scans_per_day': scans_per_day,
        'trigger_rate': round(trigger_rate, 4),
        'expected_triggers_per_day': round(expected_triggers_per_day, 1),
        'expected_real_triggers': round(expected_real_triggers, 1),
        'expected_false_positives': round(expected_false_positives, 1),
        'false_positive_rate': round((expected_false_positives / expected_triggers_per_day * 100) if expected_triggers_per_day > 0 else 0, 2)
    }


def compare_to_59_movers(historical_result, config_59_result):
    """
    Compare historical dataset results to 59-mover results to quantify overfitting

    Args:
        historical_result: Validation results on 4,821 historical moves
        config_59_result: Original results on 59 movers

    Returns:
        Dict with comparison metrics
    """
    coverage_diff = historical_result['coverage_pct'] - config_59_result['coverage_pct']
    accuracy_diff = historical_result['direction_accuracy'] - config_59_result['direction_accuracy']

    # Overfitting severity assessment
    if coverage_diff < -20:
        overfitting_severity = 'SEVERE'
        overfitting_note = 'Coverage dropped >20pp - strong overfitting signal'
    elif coverage_diff < -10:
        overfitting_severity = 'MODERATE'
        overfitting_note = 'Coverage dropped 10-20pp - moderate overfitting'
    elif coverage_diff < -5:
        overfitting_severity = 'MILD'
        overfitting_note = 'Coverage dropped 5-10pp - mild overfitting'
    else:
        overfitting_severity = 'MINIMAL'
        overfitting_note = 'Coverage relatively stable'

    return {
        'coverage_diff': round(coverage_diff, 2),
        'accuracy_diff': round(accuracy_diff, 2),
        'overfitting_severity': overfitting_severity,
        'overfitting_note': overfitting_note
    }


def main():
    """Main execution function"""
    print("="*80)
    print("Phase 3: Backtest Validation of Optimized Thresholds")
    print("="*80)
    print()

    # Paths
    analysis_dir = Path(__file__).parent
    historical_data_path = analysis_dir / 'pre_move_indicators_30d.csv'
    optimization_results_path = analysis_dir / 'threshold_optimization_results.json'
    output_path = analysis_dir / 'backtest_validation_results.json'

    # Load data
    df = load_historical_data(historical_data_path)
    top_configs, baseline_config = load_optimization_results(optimization_results_path)

    # Test each configuration
    print("\nTesting configurations against historical dataset...")
    print("-"*80)

    results = []

    for i, config_data in enumerate(top_configs, 1):
        config = config_data['config']
        config_59_result = {
            'coverage_pct': config_data['coverage_pct'],
            'direction_accuracy': config_data['direction_accuracy'],
            'triggered_count': config_data['triggered_count'],
            'correct_direction_count': config_data['correct_direction_count']
        }

        print(f"\n[{i}/10] Testing config #{i}:")
        print(f"  RSI: {config['rsi_short']}/{config['rsi_long']}, "
              f"BB: {config['bb_short']}/{config['bb_long']}, "
              f"Z: {config['z_short']}/{config['z_long']}")

        # Test on historical data
        historical_result = test_config_on_historical(df, config)

        if historical_result is None:
            print(f"  ✗ Failed to test configuration (missing data)")
            continue

        print(f"  Historical coverage: {historical_result['coverage_pct']:.1f}% "
              f"({historical_result['triggered_count']}/{historical_result['total_movers']})")
        print(f"  Historical accuracy: {historical_result['direction_accuracy']:.1f}% "
              f"({historical_result['correct_direction_count']}/{historical_result['triggered_count']})")

        # Estimate false positives
        fp_estimate = estimate_false_positives(historical_result['coverage_pct'])
        print(f"  Est. daily triggers: {fp_estimate['expected_triggers_per_day']:.0f}")
        print(f"  Est. false positives: {fp_estimate['expected_false_positives']:.0f}/day "
              f"({fp_estimate['false_positive_rate']:.1f}%)")

        # Compare to 59-mover results
        comparison = compare_to_59_movers(historical_result, config_59_result)
        print(f"  Overfitting severity: {comparison['overfitting_severity']}")
        print(f"  Coverage diff: {comparison['coverage_diff']:+.1f}pp, "
              f"Accuracy diff: {comparison['accuracy_diff']:+.1f}pp")

        results.append({
            'config_rank': i,
            'config': config,
            'results_59_movers': config_59_result,
            'results_historical': historical_result,
            'false_positive_estimate': fp_estimate,
            'overfitting_analysis': comparison
        })

    # Summary
    print("\n" + "="*80)
    print("VALIDATION SUMMARY")
    print("="*80)

    if results:
        best_config = results[0]
        print(f"\nBest Configuration (Config #1):")
        print(f"  Historical Coverage: {best_config['results_historical']['coverage_pct']:.1f}%")
        print(f"  Historical Accuracy: {best_config['results_historical']['direction_accuracy']:.1f}%")
        print(f"  Est. False Positives: {best_config['false_positive_estimate']['expected_false_positives']:.0f}/day")
        print(f"  Overfitting: {best_config['overfitting_analysis']['overfitting_severity']}")

        # Overall assessment
        print("\nOVERALL ASSESSMENT:")
        hist_coverage = best_config['results_historical']['coverage_pct']
        hist_accuracy = best_config['results_historical']['direction_accuracy']
        fp_per_day = best_config['false_positive_estimate']['expected_false_positives']

        if hist_accuracy > 55 and fp_per_day < 50 and hist_coverage > 40:
            print("  ✓ Strategy shows promise for production deployment")
        elif hist_accuracy > 50 and fp_per_day < 80:
            print("  ⚠ Strategy marginal - consider with caution")
        else:
            print("  ✗ Strategy not viable for production")
            print(f"    - Accuracy too low (<55%): {hist_accuracy:.1f}%")
            print(f"    - False positives too high (>50/day): {fp_per_day:.0f}/day")

    # Save results
    output_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'validation_dataset': {
            'file': str(historical_data_path),
            'total_moves': len(df),
            'date_range': 'Last 30 days'
        },
        'configurations_tested': len(results),
        'results': results
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n✓ Validation results saved to: {output_path}")
    print()


if __name__ == '__main__':
    main()
