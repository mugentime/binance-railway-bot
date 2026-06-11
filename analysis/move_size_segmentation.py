#!/usr/bin/env python3
"""
Move Size Segmentation Analysis - Additional Phase 2 Analysis

Segments movers by size and analyzes if different thresholds work better
for different move magnitudes:
- Small moves: 10-15%
- Medium moves: 15-25%
- Large moves: 25%+

Determines if strategy should differentiate by expected move size.

Input: analysis/226_movers_precursors.json (from Phase 1)
Output: analysis/move_size_segmentation_results.json
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


def segment_by_move_size(movers):
    """
    Segment movers into size categories

    Args:
        movers: List of mover data

    Returns:
        Dict with segmented movers
    """
    small = []  # 10-15%
    medium = []  # 15-25%
    large = []  # 25%+

    for mover in movers:
        move_pct = abs(mover['move_metadata']['move_pct'])

        if 10 <= move_pct < 15:
            small.append(mover)
        elif 15 <= move_pct < 25:
            medium.append(mover)
        else:  # 25+
            large.append(mover)

    return {
        'small': small,
        'medium': medium,
        'large': large
    }


def test_config_on_segment(movers, config):
    """
    Test configuration on a segment

    Args:
        movers: List of movers in segment
        config: Threshold configuration

    Returns:
        Dict with results
    """
    triggered = 0
    correct_direction = 0

    for mover in movers:
        actual_direction = mover['move_metadata']['direction']
        precursors = mover['precursor_candles']

        signal_found = False

        for candle in precursors:
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
        'coverage_pct': round(coverage, 2),
        'direction_accuracy': round(accuracy, 2),
        'triggered_count': triggered,
        'correct_direction_count': correct_direction,
        'total_movers': total
    }


def analyze_precursor_indicators_by_segment(segments):
    """
    Analyze if precursor indicator values differ by move size

    Args:
        segments: Dict with segmented movers

    Returns:
        Dict with indicator statistics by segment
    """
    results = {}

    for segment_name, movers in segments.items():
        if not movers:
            continue

        rsi_values = []
        bb_values = []
        zscore_values = []
        volume_ratios = []

        for mover in movers:
            # Use the last precursor candle (closest to move)
            last_candle = mover['precursor_candles'][-1]

            if last_candle.get('rsi') is not None:
                rsi_values.append(last_candle['rsi'])
            if last_candle.get('bb_pct_b') is not None:
                bb_values.append(last_candle['bb_pct_b'])
            if last_candle.get('zscore') is not None:
                zscore_values.append(last_candle['zscore'])
            if last_candle.get('volume_ratio') is not None:
                volume_ratios.append(last_candle['volume_ratio'])

        # Calculate averages
        avg_rsi = sum(rsi_values) / len(rsi_values) if rsi_values else None
        avg_bb = sum(bb_values) / len(bb_values) if bb_values else None
        avg_zscore = sum(zscore_values) / len(zscore_values) if zscore_values else None
        avg_volume = sum(volume_ratios) / len(volume_ratios) if volume_ratios else None

        results[segment_name] = {
            'avg_rsi': round(avg_rsi, 2) if avg_rsi else None,
            'avg_bb_pct_b': round(avg_bb, 3) if avg_bb else None,
            'avg_zscore': round(avg_zscore, 2) if avg_zscore else None,
            'avg_volume_ratio': round(avg_volume, 2) if avg_volume else None,
            'sample_size': len(movers)
        }

    return results


def main():
    """Main execution function"""
    print("="*80)
    print("Move Size Segmentation Analysis")
    print("="*80)
    print()

    # Paths
    analysis_dir = Path(__file__).parent
    precursor_data_path = analysis_dir / '226_movers_precursors.json'
    output_path = analysis_dir / 'move_size_segmentation_results.json'

    # Load data
    movers = load_precursor_data(precursor_data_path)

    # Segment by move size
    print("\nSegmenting movers by size...")
    segments = segment_by_move_size(movers)

    print(f"  Small moves (10-15%): {len(segments['small'])} movers")
    print(f"  Medium moves (15-25%): {len(segments['medium'])} movers")
    print(f"  Large moves (25%+): {len(segments['large'])} movers")
    print()

    # Analyze indicator patterns by segment
    print("Analyzing precursor indicator patterns by segment...")
    indicator_stats = analyze_precursor_indicators_by_segment(segments)

    print("\nIndicator Averages by Move Size:")
    print("-"*80)
    for segment_name, stats in indicator_stats.items():
        print(f"\n{segment_name.upper()} MOVES ({stats['sample_size']} movers):")
        print(f"  Avg RSI: {stats['avg_rsi']}")
        print(f"  Avg BB%B: {stats['avg_bb_pct_b']}")
        print(f"  Avg Z-score: {stats['avg_zscore']}")
        print(f"  Avg Volume Ratio: {stats['avg_volume_ratio']}")

    # Load best configuration from optimization
    opt_results_path = analysis_dir / 'threshold_optimization_results.json'
    with open(opt_results_path, 'r', encoding='utf-8') as f:
        opt_data = json.load(f)

    best_config = opt_data['top_configs'][0]['config']

    print(f"\nTesting best configuration from Phase 2 on each segment...")
    print(f"Config: RSI {best_config['rsi_short']}/{best_config['rsi_long']}, "
          f"BB {best_config['bb_short']}/{best_config['bb_long']}, "
          f"Z {best_config['z_short']}/{best_config['z_long']}")
    print("-"*80)

    # Test configuration on each segment
    segment_results = {}

    for segment_name, segment_movers in segments.items():
        if not segment_movers:
            continue

        print(f"\n{segment_name.upper()} MOVES:")
        result = test_config_on_segment(segment_movers, best_config)

        print(f"  Coverage: {result['coverage_pct']:.1f}% "
              f"({result['triggered_count']}/{result['total_movers']})")
        print(f"  Accuracy: {result['direction_accuracy']:.1f}% "
              f"({result['correct_direction_count']}/{result['triggered_count']})")

        segment_results[segment_name] = result

    # Summary
    print("\n" + "="*80)
    print("MOVE SIZE SEGMENTATION SUMMARY")
    print("="*80)

    # Find best performing segment
    best_segment = max(segment_results.items(),
                      key=lambda x: x[1]['direction_accuracy'])

    print(f"\nBest performing segment: {best_segment[0].upper()}")
    print(f"  Accuracy: {best_segment[1]['direction_accuracy']:.1f}%")
    print(f"  Coverage: {best_segment[1]['coverage_pct']:.1f}%")

    # Determine if segmentation is valuable
    print("\nRECOMMENDATION:")
    accuracies = [r['direction_accuracy'] for r in segment_results.values()]
    accuracy_range = max(accuracies) - min(accuracies)

    if accuracy_range > 10:
        print("  → SEGMENT-SPECIFIC THRESHOLDS recommended")
        print(f"  → Accuracy varies significantly across segments ({accuracy_range:.1f}pp range)")
        print("  → Different thresholds for small/medium/large moves could improve performance")
    else:
        print("  → UNIFIED THRESHOLDS sufficient")
        print(f"  → Accuracy is consistent across segments ({accuracy_range:.1f}pp range)")
        print("  → No need for segment-specific optimization")

    # Save results
    output_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'configuration_tested': best_config,
        'segments': {
            name: {
                'size': len(movers),
                'results': segment_results.get(name, {}),
                'indicator_stats': indicator_stats.get(name, {})
            }
            for name, movers in segments.items()
        },
        'best_segment': best_segment[0],
        'accuracy_range': round(accuracy_range, 2),
        'recommendation': 'segment_specific' if accuracy_range > 10 else 'unified'
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n✓ Move size segmentation results saved to: {output_path}")
    print()


if __name__ == '__main__':
    main()
