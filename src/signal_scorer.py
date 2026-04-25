"""
Martingale Signal Scanner - Signal Scorer (Backtest-Optimized)
Weighted scoring based on empirical backtest data
Entry gate: volume_ratio > 1.5 (hard requirement)
Direction: Inverted momentum (mean-reversion)
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
    score: float         # 0-100 (weighted sum)
    rsi: float
    bb_pct_b: float
    zscore: float
    volume_ratio: float
    spread_pct: float
    funding_rate: float
    sma_slope_pct: float = 0.0
    volume_24h: float = 0.0
    volume_score: float = 0.0      # Individual component scores for debugging
    rsi_score: float = 0.0
    bb_score: float = 0.0
    zscore_score: float = 0.0

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
        VOLUME SCORE (40 points max, 40% weight)
        Most predictive indicator from backtest data

        Linear scoring from 1.5x (minimum) to 5.0x+ (maximum)
        1.5x → 0 points (entry threshold, but contributes to score)
        3.0x → 20 points (midpoint)
        5.0x+ → 40 points (max)
        """
        if volume_ratio >= 5.0:
            return 40.0
        elif volume_ratio >= 1.5:
            # Linear scale from 1.5 to 5.0: 0 to 40 points
            return ((volume_ratio - 1.5) / 3.5) * 40.0
        else:
            # Below 1.5x: no score (will be gated out)
            return 0.0

    @staticmethod
    def calculate_rsi_score(rsi: float) -> Tuple[float, Optional[str]]:
        """
        RSI EXTREME SCORE (25 points max, 25% weight)
        INVERTED MOMENTUM (mean-reversion strategy)

        RSI > 65 → SHORT signal (overbought, expect reversal down)
        RSI < 35 → LONG signal (oversold, expect reversal up)

        Scoring:
        - RSI > 65: 0-25 points (65→0pts, 80→25pts max)
        - RSI < 35: 0-25 points (35→0pts, 20→25pts max)
        - RSI 35-65: 0 points (neutral zone)

        Returns: (score, direction or None)
        """
        if rsi > 65:
            # Overbought → SHORT signal
            # Linear scale: 65→0, 80→25
            score = min(25.0, ((rsi - 65) / 15.0) * 25.0)
            return score, "SHORT"
        elif rsi < 35:
            # Oversold → LONG signal
            # Linear scale: 35→0, 20→25
            score = min(25.0, ((35 - rsi) / 15.0) * 25.0)
            return score, "LONG"
        else:
            # Neutral zone
            return 0.0, None

    @staticmethod
    def calculate_bb_score(bb_pct_b: float) -> Tuple[float, Optional[str]]:
        """
        BOLLINGER BAND POSITION SCORE (20 points max, 20% weight)
        INVERTED MOMENTUM (mean-reversion strategy)

        BB%B > 0.8 → SHORT signal (near upper band, overbought)
        BB%B < 0.2 → LONG signal (near lower band, oversold)

        Scoring:
        - BB%B > 0.8: 0-20 points (0.8→0pts, 1.0→20pts max)
        - BB%B < 0.2: 0-20 points (0.2→0pts, 0.0→20pts max)
        - BB%B 0.2-0.8: 0 points (neutral zone)

        Returns: (score, direction or None)
        """
        if bb_pct_b > 0.8:
            # Near upper band → SHORT signal
            # Linear scale: 0.8→0, 1.0→20
            score = min(20.0, ((bb_pct_b - 0.8) / 0.2) * 20.0)
            return score, "SHORT"
        elif bb_pct_b < 0.2:
            # Near lower band → LONG signal
            # Linear scale: 0.2→0, 0.0→20
            score = min(20.0, ((0.2 - bb_pct_b) / 0.2) * 20.0)
            return score, "LONG"
        else:
            # Neutral zone
            return 0.0, None

    @staticmethod
    def calculate_zscore_score_directional(zscore: float) -> Tuple[float, Optional[str]]:
        """
        Z-SCORE DIRECTIONAL SCORE (15 points max, 15% weight)
        INVERTED MOMENTUM (mean-reversion strategy)

        Z-score > 1.0 → SHORT signal (price far above mean, expect reversal)
        Z-score < -1.0 → LONG signal (price far below mean, expect reversal)

        Scoring:
        - Z > 1.0: 0-15 points (1.0→0pts, 2.5→15pts max)
        - Z < -1.0: 0-15 points (-1.0→0pts, -2.5→15pts max)
        - Z -1.0 to 1.0: 0 points (neutral zone)

        Returns: (score, direction or None)
        """
        if zscore > 1.0:
            # Far above mean → SHORT signal
            # Linear scale: 1.0→0, 2.5→15
            score = min(15.0, ((zscore - 1.0) / 1.5) * 15.0)
            return score, "SHORT"
        elif zscore < -1.0:
            # Far below mean → LONG signal
            # Linear scale: -1.0→0, -2.5→15
            score = min(15.0, ((abs(zscore) - 1.0) / 1.5) * 15.0)
            return score, "LONG"
        else:
            # Neutral zone
            return 0.0, None

    def score_all_pairs(self, pair_data: Dict[str, dict], blacklisted_symbols: List[str] = None,
                       regime_data: dict = None, volatility_tracker=None) -> List[SignalResult]:
        """
        Score all pairs using backtest-optimized weighted scoring
        Returns sorted list (highest score first), filtered by ENTRY_THRESHOLD

        Entry gate: volume_ratio > 1.5 (hard requirement)
        Scoring: weighted sum of 4 components (max 100 points)
        Direction: inverted momentum (mean-reversion)

        Args:
            pair_data: Dictionary of pair market data
            blacklisted_symbols: List of symbols on cooldown (skip these)
            regime_data: DEPRECATED - not used
            volatility_tracker: DEPRECATED - not used
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

            # ENTRY GATE: volume_ratio > 1.5 (HARD REQUIREMENT)
            if volume_ratio <= 1.5:
                skipped_volume.append(f"{symbol} (vol={volume_ratio:.2f}x)")
                continue

            # COMPONENT 1: VOLUME RATIO (40% weight, 40 points max)
            volume_score = self.calculate_volume_score(volume_ratio)

            # COMPONENT 2: RSI EXTREME (25% weight, 25 points max)
            rsi_score, rsi_direction = self.calculate_rsi_score(rsi)

            # COMPONENT 3: BB POSITION (20% weight, 20 points max)
            bb_score, bb_direction = self.calculate_bb_score(bb_pct_b)

            # COMPONENT 4: Z-SCORE (15% weight, 15 points max)
            zscore_score, zscore_direction = self.calculate_zscore_score_directional(zscore)

            # TOTAL SCORE (100 points max)
            total_score = volume_score + rsi_score + bb_score + zscore_score

            # DETERMINE DIRECTION (inverted momentum / mean-reversion)
            # Collect all directional signals
            directional_votes = []
            if rsi_direction:
                directional_votes.append((rsi_direction, rsi_score))
            if bb_direction:
                directional_votes.append((bb_direction, bb_score))
            if zscore_direction:
                directional_votes.append((zscore_direction, zscore_score))

            # Determine final direction by weighted vote
            if not directional_votes:
                # No directional signals - skip this pair
                continue

            # Sum scores for LONG and SHORT
            long_score = sum(score for direction, score in directional_votes if direction == "LONG")
            short_score = sum(score for direction, score in directional_votes if direction == "SHORT")

            # Direction with higher total score wins
            final_direction = "LONG" if long_score > short_score else "SHORT"

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
                rsi_score=rsi_score,
                bb_score=bb_score,
                zscore_score=zscore_score,
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
        log(f"SCAN RESULTS (Backtest-Optimized Scorer) - Top 30 of {len(all_scores)} total signals")
        log("=" * 140)
        log("")

        if skipped_blacklist:
            log(f"BLACKLISTED ({len(skipped_blacklist)}): {', '.join(skipped_blacklist)}")
            log("")

        if skipped_volume:
            log(f"VOLUME GATED ({len(skipped_volume)}): Volume <= 1.5x average (hard requirement)")
            log(f"  Blocked: {', '.join(skipped_volume[:10])}")
            if len(skipped_volume) > 10:
                log(f"  ... and {len(skipped_volume) - 10} more")
            log("")

        log("SCORING SYSTEM (Backtest-Optimized):")
        log("  ENTRY GATE: volume_ratio > 1.5 (hard requirement)")
        log("  VOLUME RATIO (40 pts, 40%) - Most predictive indicator")
        log("  RSI EXTREME (25 pts, 25%) - >65 for SHORT, <35 for LONG")
        log("  BB POSITION (20 pts, 20%) - >0.8 for SHORT, <0.2 for LONG")
        log("  Z-SCORE (15 pts, 15%) - >1.0 for SHORT, <-1.0 for LONG")
        log("  DIRECTION: Inverted momentum (mean-reversion)")
        log(f"  THRESHOLD: {config.ENTRY_THRESHOLD} points minimum")
        log("")
        log("COLUMN GUIDE:")
        log("  Score    = Total points (0-100). Weighted sum of all components")
        log("  Dir      = LONG (oversold) | SHORT (overbought) - mean-reversion")
        log("  Vol/RSI/BB/Zsc = Component scores (debugging)")
        log("  RSI/BB%B/Z-Score/Vol = Raw indicator values")
        log("")
        log(f"{'>':<2} {'Rank':<6} {'Symbol':<15} {'Dir':<6} {'Score':<8} {'Vol':<6} {'RSI':<6} {'BB':<6} {'Zsc':<6} | "
            f"{'RSI':<8} {'BB%B':<8} {'Z':<8} {'VolRatio':<10}")
        log("-" * 140)

        for i, sig in enumerate(all_scores[:30], 1):
            marker = ">" if i == 1 else " "
            log(f"{marker} {i:<5} {sig.symbol:<15} {sig.direction:<6} {sig.score:<8.1f} "
                f"{sig.volume_score:<6.1f} {sig.rsi_score:<6.1f} {sig.bb_score:<6.1f} "
                f"{sig.zscore_score:<6.1f} | "
                f"{sig.rsi:<8.2f} {sig.bb_pct_b:<8.2f} {sig.zscore:<8.2f} "
                f"{sig.volume_ratio:<10.2f}")

        log("=" * 140)

        if signals:
            sig = signals[0]
            log(f"> ENTERING HIGHEST SCORE: {sig.symbol} {sig.direction} @ {sig.score:.1f} points")
            log(f"  Breakdown: Vol={sig.volume_score:.1f} + RSI={sig.rsi_score:.1f} + "
                f"BB={sig.bb_score:.1f} + Z={sig.zscore_score:.1f}")
            log(f"  Indicators: RSI={sig.rsi:.1f}, BB%B={sig.bb_pct_b:.2f}, Z={sig.zscore:.2f}, VolRatio={sig.volume_ratio:.2f}x")
            if sig.score < 50:
                log(f"  [!] WARNING: Score is weak (<50). Higher risk.")
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
