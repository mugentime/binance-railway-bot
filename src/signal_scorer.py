"""
Martingale Signal Scanner - Signal Scorer (Volume-First Redesign)
Computes composite score based on empirical data from 4,821 real 10%+ moves
"""
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import config
from utils import log

@dataclass
class SignalResult:
    symbol: str
    direction: str       # "LONG" or "SHORT"
    score: float         # 0-120 (100 base + 20 volatility bonus)
    rsi: float
    bb_pct_b: float
    zscore: float
    volume_ratio: float
    spread_pct: float
    funding_rate: float
    sma_slope_pct: float = 0.0
    volume_24h: float = 0.0
    volume_score: float = 0.0      # Individual component scores for debugging
    slope_score: float = 0.0
    momentum_score: float = 0.0
    zscore_score: float = 0.0
    volatility_bonus: float = 0.0

class SignalScorer:
    @staticmethod
    def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(closes) < period + 1:
            return 50.0

        deltas = np.diff(closes[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = gains.mean()
        avg_loss = losses.mean()

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_bollinger_pct_b(closes: np.ndarray, period: int = 20, std_dev: float = 2.0) -> float:
        """Calculate Bollinger %B"""
        if len(closes) < period:
            return 0.5

        recent_closes = closes[-period:]
        sma = recent_closes.mean()
        std = recent_closes.std()

        if std == 0:
            return 0.5

        current_close = closes[-1]
        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)

        pct_b = (current_close - lower_band) / (upper_band - lower_band)
        return pct_b

    @staticmethod
    def calculate_zscore(closes: np.ndarray, period: int = 20) -> float:
        """Calculate Z-score"""
        if len(closes) < period:
            return 0.0

        recent_closes = closes[-period:]
        mean = recent_closes.mean()
        std = recent_closes.std()

        if std == 0:
            return 0.0

        current_close = closes[-1]
        zscore = (current_close - mean) / std
        return zscore

    @staticmethod
    def calculate_volume_ratio(volumes: np.ndarray, period: int = 20) -> float:
        """Calculate volume ratio (current vs average)"""
        if len(volumes) < period + 1:
            return 1.0

        current_volume = volumes[-1]
        avg_volume = volumes[-period-1:-1].mean()

        if avg_volume == 0:
            return 1.0

        ratio = current_volume / avg_volume
        return ratio

    @staticmethod
    def calculate_volume_score(volume_ratio: float) -> float:
        """
        PRIMARY SIGNAL — VOLUME (40 points max)
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

    @staticmethod
    def calculate_slope_score(sma_slope_pct: float) -> Tuple[float, Optional[str]]:
        """
        DIRECTION — SMA SLOPE (30 points max)
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

    @staticmethod
    def calculate_momentum_score(bb_pct_b: float, rsi: float, slope_direction: Optional[str] = None) -> Tuple[float, str]:
        """
        MOMENTUM CONFIRMATION — BB%B + RSI (20 points max)
        Also determines secondary direction if slope is flat
        TREND-FOLLOWING logic (not mean-reversion)

        BB%B scoring (10 points max):
        - >1.0 (strong upward momentum): 10 points → suggests LONG
        - <0.0 (strong downward momentum): 10 points → suggests SHORT
        - 0.0 to 1.0 (normal): scaled points, >0.5 leans LONG, <0.5 leans SHORT

        RSI scoring (10 points max):
        - >70 (strong bullish): 10 points → suggests LONG
        - <30 (weak bearish): 10 points → suggests SHORT
        - 30 to 70 (neutral): scaled points, >50 leans LONG, <50 leans SHORT
        """
        # BB%B scoring - TREND-FOLLOWING
        if bb_pct_b > 1.0:
            # Above upper band = strong upward momentum
            bb_score = min(10.0, (bb_pct_b - 1.0) * 10.0)
            bb_direction = "LONG"  # FLIPPED from mean-reversion
        elif bb_pct_b < 0.0:
            # Below lower band = strong downward momentum
            bb_score = min(10.0, abs(bb_pct_b) * 10.0)
            bb_direction = "SHORT"  # FLIPPED from mean-reversion
        else:
            # 0.0 to 1.0: score based on distance from center (0.5)
            distance_from_center = abs(bb_pct_b - 0.5)
            bb_score = distance_from_center * 10.0  # Max 5 points
            bb_direction = "LONG" if bb_pct_b > 0.5 else "SHORT"  # FLIPPED

        # RSI scoring - TREND-FOLLOWING
        if rsi > 70:
            # Strong bullish momentum
            rsi_score = min(10.0, (rsi - 70) / 30 * 10.0)
            rsi_direction = "LONG"  # FLIPPED from mean-reversion
        elif rsi < 30:
            # Weak/bearish momentum
            rsi_score = min(10.0, (30 - rsi) / 30 * 10.0)
            rsi_direction = "SHORT"  # FLIPPED from mean-reversion
        else:
            # 30 to 70: score based on distance from center (50)
            distance_from_center = abs(rsi - 50)
            rsi_score = (distance_from_center / 20) * 5.0  # Max 5 points
            rsi_direction = "LONG" if rsi > 50 else "SHORT"  # FLIPPED

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

    @staticmethod
    def calculate_zscore_score(zscore: float) -> float:
        """
        ABNORMALITY CONFIRMATION — Z-SCORE (10 points max)
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

    def score_all_pairs(self, pair_data: Dict[str, dict], blacklisted_symbols: List[str] = None,
                       regime_data: dict = None, volatility_tracker=None) -> List[SignalResult]:
        """
        Score all pairs using volume-first approach
        Returns sorted list (highest score first), filtered by ENTRY_THRESHOLD

        Args:
            pair_data: Dictionary of pair market data
            blacklisted_symbols: List of symbols on cooldown (skip these)
            regime_data: DEPRECATED - not used anymore
            volatility_tracker: Optional volatility tracker for bonus points
        """
        if blacklisted_symbols is None:
            blacklisted_symbols = []

        all_scores = []  # Store ALL scores (even below threshold)
        signals = []     # Store only above-threshold signals
        skipped_blacklist = []  # Track skipped symbols
        skipped_volume = []  # Track volume-blocked symbols

        for symbol, data in pair_data.items():
            # Skip blacklisted symbols
            if symbol in blacklisted_symbols:
                skipped_blacklist.append(symbol)
                continue

            closes = data["closes"]
            volumes = data["volumes"]
            spread_pct = data["spread_pct"]
            funding_rate = data["funding_rate"]
            sma_slope_pct = data.get("sma_slope_pct", 0.0)
            volume_24h = data.get("volume_24h", 0.0)

            # Calculate indicators
            rsi = self.calculate_rsi(closes)
            bb_pct_b = self.calculate_bollinger_pct_b(closes)
            zscore = self.calculate_zscore(closes)
            volume_ratio = self.calculate_volume_ratio(volumes)

            # PRIMARY SIGNAL: VOLUME (40 points max, hard block if < 1.0x)
            volume_score = self.calculate_volume_score(volume_ratio)
            if volume_score == 0.0:
                # HARD BLOCK: volume too low, skip this pair
                skipped_volume.append(f"{symbol} (vol={volume_ratio:.2f}x)")
                continue

            # DIRECTION: SMA SLOPE (30 points max)
            slope_score, slope_direction = self.calculate_slope_score(sma_slope_pct)

            # MOMENTUM: BB%B + RSI (20 points max)
            momentum_score, final_direction = self.calculate_momentum_score(bb_pct_b, rsi, slope_direction)

            # ABNORMALITY: Z-SCORE (10 points max)
            zscore_score = self.calculate_zscore_score(zscore)

            # BASE SCORE (100 points max)
            base_score = volume_score + slope_score + momentum_score + zscore_score

            # VOLATILITY BONUS (20 points max, flat point system)
            volatility_bonus = 0.0
            if volatility_tracker is not None:
                raw_count = volatility_tracker.raw_scores.get(symbol, 0)
                volatility_bonus = volatility_tracker.get_volatility_bonus_points(symbol)

            # TOTAL SCORE (120 points max)
            total_score = base_score + volatility_bonus

            # Create signal result
            result = SignalResult(
                symbol=symbol,
                direction=final_direction,
                score=total_score,
                rsi=rsi,
                bb_pct_b=bb_pct_b,
                zscore=zscore,
                volume_ratio=volume_ratio,
                spread_pct=spread_pct,
                funding_rate=funding_rate,
                sma_slope_pct=sma_slope_pct,
                volume_24h=volume_24h,
                volume_score=volume_score,
                slope_score=slope_score,
                momentum_score=momentum_score,
                zscore_score=zscore_score,
                volatility_bonus=volatility_bonus,
            )

            all_scores.append(result)

            # Add to signals list if above threshold
            if total_score >= config.ENTRY_THRESHOLD:
                signals.append(result)

        # Sort all scores by score (highest first)
        all_scores.sort(key=lambda x: x.score, reverse=True)

        # Sort filtered signals by score (highest first)
        signals.sort(key=lambda x: x.score, reverse=True)

        # Log detailed output
        log("=" * 140)
        log(f"SCAN RESULTS (Volume-First Scorer) - Top 30 of {len(all_scores)} total signals")
        log("=" * 140)
        log("")

        if skipped_blacklist:
            log(f"BLACKLISTED ({len(skipped_blacklist)}): {', '.join(skipped_blacklist)}")
            log("")

        if skipped_volume:
            log(f"VOLUME BLOCKED ({len(skipped_volume)}): Volume < 1.5x average (hard requirement)")
            log(f"  Blocked: {', '.join(skipped_volume[:10])}")
            if len(skipped_volume) > 10:
                log(f"  ... and {len(skipped_volume) - 10} more")
            log("")

        log("SCORING SYSTEM (Volume-First):")
        log("  VOLUME (40 pts) - PRIMARY SIGNAL, hard block if < 1.5x")
        log("  SLOPE (30 pts) - Direction from SMA slope, full points if |slope| > 0.3%")
        log("  MOMENTUM (20 pts) - BB%B (10) + RSI (10), confirms direction")
        log("  Z-SCORE (10 pts) - Abnormality confirmation")
        log("  VOLATILITY (20 pts) - Flat bonus based on 10%+ hourly move frequency")
        log(f"  THRESHOLD: {config.ENTRY_THRESHOLD} points minimum")
        log("")
        log("COLUMN GUIDE:")
        log("  Score    = Total points (0-120). Base (100) + Volatility bonus (20)")
        log("  Dir      = LONG (slope >+0.3%) | SHORT (slope <-0.3%) | BB%B+RSI if flat")
        log("  Vol/Slp/Mom/Zsc/Vlt = Component scores (debugging)")
        log("  RSI/BB%B/Z-Score/Vol = Raw indicator values")
        log("")
        log(f"{'>':<2} {'Rank':<6} {'Symbol':<15} {'Dir':<6} {'Score':<8} {'Vol':<6} {'Slp':<6} {'Mom':<6} {'Zsc':<6} {'Vlt':<6} | "
            f"{'RSI':<8} {'BB%B':<8} {'Z':<8} {'VolRatio':<10} {'Slope%':<10}")
        log("-" * 140)

        for i, sig in enumerate(all_scores[:30], 1):
            marker = ">" if i == 1 else " "
            log(f"{marker} {i:<5} {sig.symbol:<15} {sig.direction:<6} {sig.score:<8.1f} "
                f"{sig.volume_score:<6.1f} {sig.slope_score:<6.1f} {sig.momentum_score:<6.1f} "
                f"{sig.zscore_score:<6.1f} {sig.volatility_bonus:<6.1f} | "
                f"{sig.rsi:<8.2f} {sig.bb_pct_b:<8.2f} {sig.zscore:<8.2f} "
                f"{sig.volume_ratio:<10.2f} {sig.sma_slope_pct:<10.4f}")

        log("=" * 140)

        if signals:
            sig = signals[0]
            log(f"> ENTERING HIGHEST SCORE: {sig.symbol} {sig.direction} @ {sig.score:.1f} points")
            log(f"  Breakdown: Vol={sig.volume_score:.1f} + Slope={sig.slope_score:.1f} + "
                f"Momentum={sig.momentum_score:.1f} + Z={sig.zscore_score:.1f} + Volatility={sig.volatility_bonus:.1f}")
            if sig.score < 45:
                log(f"  [!] WARNING: Score is weak (<45). Higher risk.")
            elif sig.score < config.ENTRY_THRESHOLD:
                log(f"  [!] CAUTION: Score below threshold ({config.ENTRY_THRESHOLD}).")
            else:
                log(f"  [OK] Score is solid (>={config.ENTRY_THRESHOLD}). Good opportunity.")
        else:
            log(f"[X] NO SIGNALS ABOVE THRESHOLD ({config.ENTRY_THRESHOLD} points)")

        log("=" * 140)

        return signals

# Test with scanner output
if __name__ == "__main__":
    import asyncio
    from pair_scanner import PairScanner

    async def main():
        scanner = PairScanner()
        scorer = SignalScorer()

        try:
            # Scan pairs
            pair_data = await scanner.scan_all_pairs()

            # Score pairs
            signals = scorer.score_all_pairs(pair_data)

            print(f"\n{'='*80}")
            print(f"SIGNAL SCORER TEST")
            print(f"{'='*80}")
            print(f"Total signals above threshold: {len(signals)}")
            print(f"\nTop 10 signals:")
            print(f"{'Rank':<6} {'Symbol':<15} {'Dir':<6} {'Score':<8} {'Vol':<6} {'Slp':<6} {'Mom':<6}")
            print(f"{'-'*80}")

            for i, sig in enumerate(signals[:10], 1):
                print(f"{i:<6} {sig.symbol:<15} {sig.direction:<6} {sig.score:<8.1f} "
                      f"{sig.volume_score:<6.1f} {sig.slope_score:<6.1f} {sig.momentum_score:<6.1f}")

        finally:
            await scanner.close()

    asyncio.run(main())
