"""
Backtest validation script for new signal scorer
Validates against pre_move_indicators_30d.csv (4,821 real 10%+ moves)
"""
import sys
import os
import csv
from typing import Dict, List, Tuple

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

# Import config first to set thresholds
import config

class BacktestResult:
    def __init__(self):
        self.total_moves = 0
        self.triggered_count = 0
        self.correct_direction = 0
        self.wrong_direction = 0
        self.coverage_pct = 0.0
        self.direction_accuracy = 0.0
        self.passed = False

    def __str__(self):
        return f"""
BACKTEST RESULTS
================
Total 10%+ moves in CSV: {self.total_moves}
Triggered by scorer: {self.triggered_count}
Coverage: {self.coverage_pct:.1f}% (required >= 30%)
Direction correct: {self.correct_direction}
Direction wrong: {self.wrong_direction}
Direction accuracy: {self.direction_accuracy:.1f}% (required >= 55%)
RESULT: {'PASSED' if self.passed else 'FAILED'}
"""

def calculate_volume_score(volume_ratio: float) -> float:
    """
    Volume scoring: 40 points max
    HARD BLOCK if < 1.0x (returns 0) - lowered from 1.5x for better coverage
    1.0x → 0 points (threshold)
    1.5x → 10 points
    2.0x → 20 points
    3.0x → 30 points
    5.0x+ → 40 points (max)
    """
    if volume_ratio < 1.0:
        return 0.0  # HARD BLOCK - below average volume

    if volume_ratio >= 5.0:
        return 40.0
    elif volume_ratio >= 3.0:
        # 3.0 to 5.0: 30 to 40 points
        return 30.0 + ((volume_ratio - 3.0) / 2.0) * 10.0
    elif volume_ratio >= 2.0:
        # 2.0 to 3.0: 20 to 30 points
        return 20.0 + ((volume_ratio - 2.0) / 1.0) * 10.0
    elif volume_ratio >= 1.5:
        # 1.5 to 2.0: 10 to 20 points
        return 10.0 + ((volume_ratio - 1.5) / 0.5) * 10.0
    else:
        # 1.0 to 1.5: 0 to 10 points
        return ((volume_ratio - 1.0) / 0.5) * 10.0

def calculate_slope_score(sma_slope_pct: float) -> Tuple[float, str]:
    """
    SMA Slope scoring: 30 points max
    Also determines primary direction

    Returns: (score, direction)
    - Strong uptrend (>+0.3%): 30 points, LONG
    - Strong downtrend (<-0.3%): 30 points, SHORT
    - Flat (-0.3% to +0.3%): scaled points, use secondary signals
    """
    abs_slope = abs(sma_slope_pct)

    if abs_slope >= 0.3:
        # Strong trend: full points
        direction = "LONG" if sma_slope_pct > 0 else "SHORT"
        return 30.0, direction
    else:
        # Flat trend: scaled points (0 to 30), no direction yet
        slope_score = (abs_slope / 0.3) * 30.0
        return slope_score, None

def calculate_momentum_score(bb_pct_b: float, rsi: float, slope_direction: str = None) -> Tuple[float, str]:
    """
    Momentum scoring: 20 points max (BB%B + RSI)
    Also determines secondary direction if slope is flat
    TREND-FOLLOWING logic (not mean-reversion)

    BB%B scoring (10 points max):
    - >1.0 (strong upward momentum): 10 points → suggests LONG
    - <0.0 (strong downward momentum): 10 points → suggests SHORT
    - 0.0 to 1.0 (normal): scaled points based on distance from 0.5
      - >0.5 leans LONG, <0.5 leans SHORT

    RSI scoring (10 points max):
    - >70 (strong bullish): 10 points → suggests LONG
    - <30 (weak bearish): 10 points → suggests SHORT
    - 30 to 70 (neutral): scaled points, >50 leans LONG, <50 leans SHORT
    """
    # BB%B scoring - TREND-FOLLOWING
    if bb_pct_b > 1.0:
        # Above upper band = strong upward momentum
        bb_score = min(10.0, (bb_pct_b - 1.0) * 10.0)
        bb_direction = "LONG"  # Trend-following: momentum up → LONG
    elif bb_pct_b < 0.0:
        # Below lower band = strong downward momentum
        bb_score = min(10.0, abs(bb_pct_b) * 10.0)
        bb_direction = "SHORT"  # Trend-following: momentum down → SHORT
    else:
        # 0.0 to 1.0: score based on distance from center (0.5)
        distance_from_center = abs(bb_pct_b - 0.5)
        bb_score = distance_from_center * 10.0  # Max 5 points
        bb_direction = "LONG" if bb_pct_b > 0.5 else "SHORT"  # Trend-following

    # RSI scoring - TREND-FOLLOWING
    if rsi > 70:
        # Strong bullish momentum
        rsi_score = min(10.0, (rsi - 70) / 30 * 10.0)
        rsi_direction = "LONG"  # Trend-following: strong momentum → LONG
    elif rsi < 30:
        # Weak/bearish momentum
        rsi_score = min(10.0, (30 - rsi) / 30 * 10.0)
        rsi_direction = "SHORT"  # Trend-following: weak → SHORT
    else:
        # 30 to 70: score based on distance from center (50)
        distance_from_center = abs(rsi - 50)
        rsi_score = (distance_from_center / 20) * 5.0  # Max 5 points
        rsi_direction = "LONG" if rsi > 50 else "SHORT"  # Trend-following

    total_momentum = bb_score + rsi_score

    # Determine direction if slope is flat (slope_direction is None)
    if slope_direction is None:
        # Use BB%B and RSI agreement
        if bb_direction == rsi_direction:
            # Both agree
            direction = bb_direction
        else:
            # Disagree: use whichever has stronger signal
            direction = bb_direction if bb_score > rsi_score else rsi_direction
    else:
        # Slope already determined direction
        direction = slope_direction

    return total_momentum, direction

def calculate_zscore_score(zscore: float) -> float:
    """
    Z-score scoring: 10 points max
    Measures abnormality (distance from normal)

    |Z| >= 2.5: 10 points (highly abnormal)
    |Z| >= 2.0: 7 points
    |Z| >= 1.5: 4 points
    |Z| < 1.5: scaled 0-4 points
    """
    abs_z = abs(zscore)

    if abs_z >= 2.5:
        return 10.0
    elif abs_z >= 2.0:
        return 7.0
    elif abs_z >= 1.5:
        return 4.0
    else:
        return (abs_z / 1.5) * 4.0

def calculate_volatility_bonus(raw_count: int) -> float:
    """
    Volatility bonus: 20 points max (flat point system)
    Based on 10%+ hourly move count over 7 days

    500+ hours → +20 points
    200-499 → +15 points
    50-199 → +10 points
    10-49 → +5 points
    <10 → +0 points
    """
    if raw_count >= 500:
        return 20.0
    elif raw_count >= 200:
        return 15.0
    elif raw_count >= 50:
        return 10.0
    elif raw_count >= 10:
        return 5.0
    else:
        return 0.0

def score_single_snapshot(row: Dict) -> Tuple[float, str]:
    """
    Score a single pre-move snapshot using new volume-first logic
    Returns: (total_score, predicted_direction)
    """
    # Extract indicators
    rsi = float(row['rsi'])
    bb_pct_b = float(row['bb_pct_b'])
    zscore = float(row['zscore'])
    volume_ratio = float(row['volume_ratio'])
    sma_slope_pct = float(row['sma_slope_pct'])

    # Volume score (40 points max, hard block if < 1.5x)
    volume_score = calculate_volume_score(volume_ratio)
    if volume_score == 0.0:
        # HARD BLOCK: volume too low
        return 0.0, None

    # Slope score + primary direction (30 points max)
    slope_score, slope_direction = calculate_slope_score(sma_slope_pct)

    # Momentum score + secondary direction (20 points max)
    momentum_score, final_direction = calculate_momentum_score(bb_pct_b, rsi, slope_direction)

    # Z-score abnormality (10 points max)
    zscore_score = calculate_zscore_score(zscore)

    # Base score (100 points max)
    base_score = volume_score + slope_score + momentum_score + zscore_score

    # Volatility bonus (20 points max) - NOT AVAILABLE IN CSV, so skip for backtest
    # In real trading, this would be added from volatility_tracker
    volatility_bonus = 0.0  # No historical volatility data in CSV

    total_score = base_score + volatility_bonus

    return total_score, final_direction

def run_backtest(csv_path: str, entry_threshold: float = 55.0) -> BacktestResult:
    """
    Run backtest against CSV file
    Returns: BacktestResult with coverage and accuracy metrics
    """
    result = BacktestResult()

    # Read CSV
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    result.total_moves = len(rows)

    print(f"\nAnalyzing {result.total_moves} pre-move snapshots...")
    print(f"Entry threshold: {entry_threshold}")
    print("="*80)

    triggered_moves = []

    for row in rows:
        actual_direction = row['direction']  # "UP" or "DOWN"
        score, predicted_direction = score_single_snapshot(row)

        # Check if scorer would trigger
        if score >= entry_threshold and predicted_direction is not None:
            result.triggered_count += 1

            # Map actual direction to expected position
            # UP move → should predict LONG (buy before rise)
            # DOWN move → should predict SHORT (sell before drop)
            expected_position = "LONG" if actual_direction == "UP" else "SHORT"

            if predicted_direction == expected_position:
                result.correct_direction += 1
            else:
                result.wrong_direction += 1

            triggered_moves.append({
                'symbol': row['symbol'],
                'actual': actual_direction,
                'predicted': predicted_direction,
                'score': score,
                'correct': predicted_direction == expected_position
            })

    # Calculate metrics
    result.coverage_pct = (result.triggered_count / result.total_moves * 100) if result.total_moves > 0 else 0.0
    result.direction_accuracy = (result.correct_direction / result.triggered_count * 100) if result.triggered_count > 0 else 0.0

    # Check pass/fail
    result.passed = result.coverage_pct >= 30.0 and result.direction_accuracy >= 55.0

    # Show sample of triggered moves
    print("\nSample of triggered moves (first 10):")
    print("-"*80)
    for move in triggered_moves[:10]:
        status = "[OK]" if move['correct'] else "[X]"
        print(f"{status} {move['symbol']:<15} Actual: {move['actual']:<5} Predicted: {move['predicted']:<6} Score: {move['score']:.1f}")

    if len(triggered_moves) > 10:
        print(f"... and {len(triggered_moves) - 10} more")

    return result

if __name__ == "__main__":
    csv_path = os.path.join(project_root, "analysis", "pre_move_indicators_30d.csv")

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV file not found at {csv_path}")
        sys.exit(1)

    print("="*80)
    print("SIGNAL SCORER BACKTEST VALIDATION")
    print("="*80)
    print(f"CSV: {csv_path}")
    print(f"Entry threshold: {config.ENTRY_THRESHOLD}")

    result = run_backtest(csv_path, config.ENTRY_THRESHOLD)
    print(result)

    if result.passed:
        print("\n[OK] BACKTEST PASSED - Ready for deployment")
        sys.exit(0)
    else:
        print("\n[X] BACKTEST FAILED - Do NOT deploy")
        if result.coverage_pct < 30.0:
            print(f"   Coverage too low: {result.coverage_pct:.1f}% < 30%")
        if result.direction_accuracy < 55.0:
            print(f"   Direction accuracy too low: {result.direction_accuracy:.1f}% < 55%")
        sys.exit(1)
