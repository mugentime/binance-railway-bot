"""
Martingale Signal Scanner - Signal Scorer
Computes composite mean-reversion score for each pair
"""
import numpy as np
from dataclasses import dataclass
from typing import List, Dict
import config
from utils import log

@dataclass
class SignalResult:
    symbol: str
    direction: str       # "LONG" or "SHORT"
    score: float         # 0-100
    rsi: float
    bb_pct_b: float
    zscore: float
    volume_ratio: float
    spread_pct: float
    funding_rate: float
    sma_slope_pct: float = 0.0  # SMA slope percentage per candle
    volume_24h: float = 0.0      # 24h quote volume in USD

class SignalScorer:
    @staticmethod
    def get_actual_direction(original_direction: str, signal_direction: str = None) -> str:
        """
        Get actual direction based on signal inversion setting.
        In inverted mode: oversold → SHORT, overbought → LONG
        Args:
            original_direction: "LONG" or "SHORT"
            signal_direction: Override config (for dynamic regime detection)
        """
        direction_mode = signal_direction if signal_direction is not None else config.SIGNAL_DIRECTION
        if direction_mode == "inverted":
            return "SHORT" if original_direction == "LONG" else "LONG"
        return original_direction

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
    def normalize_long_score(rsi: float, bb_pct_b: float, zscore: float,
                           volume_ratio: float, spread_pct: float, funding_rate: float) -> Dict[str, float]:
        """Normalize indicators to 0-100 score for LONG signals"""

        # RSI: oversold condition (RSI < threshold)
        rsi_threshold = config.RSI_LONG_THRESHOLD
        if rsi >= rsi_threshold:
            rsi_score = 0.0
        else:
            rsi_score = min(100.0, (rsi_threshold - rsi) / 20 * 100)

        # Bollinger: below lower band (%B < 0)
        if bb_pct_b >= 0:
            bb_score = 0.0
        else:
            bb_score = min(100.0, abs(bb_pct_b) * 100)

        # Z-score: strong deviation below mean (Z < -1.5)
        if zscore >= -1.5:
            zscore_score = 0.0
        else:
            zscore_score = min(100.0, (abs(zscore) - 1.5) / 2.5 * 100)

        # Volume: spike above average (ratio > 1.5)
        if volume_ratio < 1.5:
            volume_score = 0.0
        else:
            volume_score = min(100.0, (volume_ratio - 1.5) / 3.5 * 100)

        # Spread: tighter is better (< 0.1%)
        if spread_pct >= 0.1:
            spread_score = 0.0
        else:
            spread_score = (0.1 - spread_pct) / 0.09 * 100

        # Funding: negative funding (shorts paying longs)
        if funding_rate >= 0:
            funding_score = 0.0
        else:
            funding_score = min(100.0, abs(funding_rate) / 0.001 * 100)

        return {
            "rsi": rsi_score,
            "bollinger": bb_score,
            "zscore": zscore_score,
            "volume": volume_score,
            "spread": spread_score,
            "funding": funding_score,
        }

    @staticmethod
    def normalize_short_score(rsi: float, bb_pct_b: float, zscore: float,
                            volume_ratio: float, spread_pct: float, funding_rate: float) -> Dict[str, float]:
        """Normalize indicators to 0-100 score for SHORT signals"""

        # RSI: overbought condition (RSI > threshold)
        rsi_threshold = config.RSI_SHORT_THRESHOLD
        if rsi <= rsi_threshold:
            rsi_score = 0.0
        else:
            rsi_score = min(100.0, (rsi - rsi_threshold) / 20 * 100)

        # Bollinger: above upper band (%B > 1)
        if bb_pct_b <= 1:
            bb_score = 0.0
        else:
            bb_score = min(100.0, (bb_pct_b - 1) * 100)

        # Z-score: strong deviation above mean (Z > 1.5)
        if zscore <= 1.5:
            zscore_score = 0.0
        else:
            zscore_score = min(100.0, (zscore - 1.5) / 2.5 * 100)

        # Volume: same as longs
        if volume_ratio < 1.5:
            volume_score = 0.0
        else:
            volume_score = min(100.0, (volume_ratio - 1.5) / 3.5 * 100)

        # Spread: same as longs
        if spread_pct >= 0.1:
            spread_score = 0.0
        else:
            spread_score = (0.1 - spread_pct) / 0.09 * 100

        # Funding: positive funding (longs paying shorts)
        if funding_rate <= 0:
            funding_score = 0.0
        else:
            funding_score = min(100.0, funding_rate / 0.001 * 100)

        return {
            "rsi": rsi_score,
            "bollinger": bb_score,
            "zscore": zscore_score,
            "volume": volume_score,
            "spread": spread_score,
            "funding": funding_score,
        }

    @staticmethod
    def calculate_composite_score(sub_scores: Dict[str, float]) -> float:
        """Calculate weighted composite score"""
        composite = (
            sub_scores["rsi"] * config.WEIGHTS["rsi"] +
            sub_scores["bollinger"] * config.WEIGHTS["bollinger"] +
            sub_scores["zscore"] * config.WEIGHTS["zscore"] +
            sub_scores["volume"] * config.WEIGHTS["volume"] +
            sub_scores["spread"] * config.WEIGHTS["spread"] +
            sub_scores["funding"] * config.WEIGHTS["funding"]
        )
        return composite

    def score_all_pairs(self, pair_data: Dict[str, dict], blacklisted_symbols: List[str] = None, regime_data: dict = None) -> List[SignalResult]:
        """
        Score all pairs for both LONG and SHORT
        Returns sorted list (highest score first), filtered by ENTRY_THRESHOLD

        Args:
            pair_data: Dictionary of pair market data
            blacklisted_symbols: List of symbols on cooldown (skip these)
            regime_data: Dict with 'regime', 'slope_pct', etc. (for logging only)
        """
        if blacklisted_symbols is None:
            blacklisted_symbols = []

        # Extract regime for logging (not used for penalties anymore)
        regime = 'ranging'
        if regime_data is not None:
            regime = regime_data.get('regime', 'ranging')

        all_scores = []  # Store ALL scores (even below threshold)
        signals = []     # Store only above-threshold signals
        skipped_blacklist = []  # Track skipped symbols
        skipped_trend_filter = []  # Track trend-filtered symbols

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

            # Z-score extreme filter - skip if move is too extreme
            if config.FILTER_ZSCORE_EXTREME and abs(zscore) > config.ZSCORE_EXTREME_THRESHOLD:
                continue  # Skip this pair entirely

            # Score LONG
            # STRATEGY MODE: If TREND_FOLLOWING, use SHORT scoring logic for LONG signals
            if config.STRATEGY_MODE == "TREND_FOLLOWING":
                long_scores = self.normalize_short_score(  # REVERSED for trend-following
                    rsi, bb_pct_b, zscore, volume_ratio, spread_pct, funding_rate
                )
            else:
                long_scores = self.normalize_long_score(  # Normal mean-reversion
                    rsi, bb_pct_b, zscore, volume_ratio, spread_pct, funding_rate
                )
            long_composite = self.calculate_composite_score(long_scores)

            # RANGING MARKET PENALTY: Heavily penalize LONG signals in ranging markets
            # This is the ORIGINAL logic - always penalize longs in ranging markets
            if regime == 'ranging':
                long_composite *= 0.3

            # TREND FILTER: Block LONG only if slope is STRONGLY negative (< -threshold)
            if sma_slope_pct < -config.SMA_SLOPE_THRESHOLD:
                long_composite = 0.0  # Zero out score
                skipped_trend_filter.append(f"{symbol} LONG (slope={sma_slope_pct:.4f}%)")

            # Get actual direction (kept for backwards compatibility)
            actual_long_direction = "LONG"

            # Store ALL LONG scores
            long_result = SignalResult(
                symbol=symbol,
                direction=actual_long_direction,  # Use inverted direction if configured
                score=long_composite,
                rsi=rsi,
                bb_pct_b=bb_pct_b,
                zscore=zscore,
                volume_ratio=volume_ratio,
                spread_pct=spread_pct,
                funding_rate=funding_rate,
                sma_slope_pct=sma_slope_pct,
                volume_24h=volume_24h,
            )
            all_scores.append(long_result)

            if long_composite >= config.ENTRY_THRESHOLD:
                signals.append(long_result)

            # Score SHORT
            # STRATEGY MODE: If TREND_FOLLOWING, use LONG scoring logic for SHORT signals
            if config.STRATEGY_MODE == "TREND_FOLLOWING":
                short_scores = self.normalize_long_score(  # REVERSED for trend-following
                    rsi, bb_pct_b, zscore, volume_ratio, spread_pct, funding_rate
                )
            else:
                short_scores = self.normalize_short_score(  # Normal mean-reversion
                    rsi, bb_pct_b, zscore, volume_ratio, spread_pct, funding_rate
                )
            short_composite = self.calculate_composite_score(short_scores)

            # NO PENALTY for SHORT signals (original logic)
            # SHORT signals are never penalized

            # TREND FILTER: Block SHORT only if slope is STRONGLY positive (> +threshold)
            if sma_slope_pct > config.SMA_SLOPE_THRESHOLD:
                short_composite = 0.0  # Zero out score
                skipped_trend_filter.append(f"{symbol} SHORT (slope={sma_slope_pct:.4f}%)")

            # Get actual direction (kept for backwards compatibility)
            actual_short_direction = "SHORT"

            # Store ALL SHORT scores
            short_result = SignalResult(
                symbol=symbol,
                direction=actual_short_direction,  # Use inverted direction if configured
                score=short_composite,
                rsi=rsi,
                bb_pct_b=bb_pct_b,
                zscore=zscore,
                volume_ratio=volume_ratio,
                spread_pct=spread_pct,
                funding_rate=funding_rate,
                sma_slope_pct=sma_slope_pct,
                volume_24h=volume_24h,
            )
            all_scores.append(short_result)

            if short_composite >= config.ENTRY_THRESHOLD:
                signals.append(short_result)

        # Sort all scores by score (highest first)
        all_scores.sort(key=lambda x: x.score, reverse=True)

        # ALWAYS return the top signal, regardless of threshold
        if all_scores:
            signals = [all_scores[0]]  # Always pick #1 highest score
        else:
            signals = []

        # Log detailed output - TOP 30 scores
        log("=" * 120)
        log(f"SCAN RESULTS - Top 30 of {len(all_scores)} total signals")
        log("=" * 120)
        log("")

        # Show regime penalty (original logic restored)
        if regime == 'ranging':
            log(f"REGIME PENALTY: RANGING → LONGS penalized (-70%), SHORTS no penalty")
        else:
            log(f"REGIME PENALTY: TRENDING → No penalties applied")
        log("")

        if skipped_blacklist:
            log(f"BLACKLISTED ({len(skipped_blacklist)}): {', '.join(skipped_blacklist)}")
            log("")
        if skipped_trend_filter:
            log(f"TREND FILTERED ({len(skipped_trend_filter)}): Strong trend blocks counter-trend signals (threshold ±{config.SMA_SLOPE_THRESHOLD}%)")
            log(f"  Blocked: {', '.join(skipped_trend_filter[:10])}")
            if len(skipped_trend_filter) > 10:
                log(f"  ... and {len(skipped_trend_filter) - 10} more")
            log("")
        log("STRATEGY: Always pick HIGHEST SCORE (ignoring threshold)")
        log("")
        log("COLUMN GUIDE:")
        log("  Score    = Signal strength (0-100). Higher = stronger signal")
        log("  Dir      = LONG (buy, expect rise) | SHORT (sell, expect drop)")
        log("  RSI      = Overbought/Oversold. >70 = overbought, <30 = oversold")
        log("  BB%B     = Price position. >1.0 = above range (high), <0.0 = below range (low)")
        log("  Z-Score  = Deviation from normal. >2 = abnormally high, <-2 = abnormally low")
        log("  Vol      = Volume vs average. >1.5 = high activity")
        log("  Spread%  = Trading cost. Lower = better (easier to trade)")
        log("  Fund%    = Funding rate. Positive = longs pay shorts (bearish)")
        log(f"  Slope%   = SMA trend. Only blocks if |slope| > {config.SMA_SLOPE_THRESHOLD}% (strong trend)")
        log("")
        log(f"{'>':<2} {'Rank':<6} {'Symbol':<15} {'Dir':<6} {'Score':<8} {'RSI':<8} {'BB%B':<8} {'Z-Score':<10} {'Vol':<8} {'Spread%':<10} {'Fund%':<10} {'Slope%':<10}")
        log("-" * 130)

        for i, sig in enumerate(all_scores[:30], 1):
            marker = ">" if i == 1 else " "  # Arrow marks the #1 pick
            log(f"{marker} {i:<5} {sig.symbol:<15} {sig.direction:<6} {sig.score:<8.2f} "
                f"{sig.rsi:<8.2f} {sig.bb_pct_b:<8.2f} {sig.zscore:<10.2f} "
                f"{sig.volume_ratio:<8.2f} {sig.spread_pct*100:<10.4f} {sig.funding_rate*100:<10.4f} "
                f"{sig.sma_slope_pct:<10.4f}")

        log("=" * 120)

        if signals:
            log(f"> ENTERING HIGHEST SCORE: {signals[0].symbol} {signals[0].direction} @ {signals[0].score:.2f}")
            if signals[0].score < 30:
                log(f"  [!] WARNING: Score is weak (<30). Higher risk of loss.")
            elif signals[0].score < 45:
                log(f"  [!] CAUTION: Score is moderate (30-45). Proceed with care.")
            else:
                log(f"  [OK] Score is decent (45+). Good trading opportunity.")
        else:
            log(f"[X] NO SIGNALS AVAILABLE (no pairs scanned)")

        log("=" * 120)

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
            print(f"{'Rank':<6} {'Symbol':<15} {'Dir':<6} {'Score':<8} {'RSI':<8} {'BB%B':<8} {'Z':<8} {'Vol':<8}")
            print(f"{'-'*80}")

            for i, sig in enumerate(signals[:10], 1):
                print(f"{i:<6} {sig.symbol:<15} {sig.direction:<6} {sig.score:<8.2f} "
                      f"{sig.rsi:<8.2f} {sig.bb_pct_b:<8.2f} {sig.zscore:<8.2f} {sig.volume_ratio:<8.2f}")

        finally:
            await scanner.close()

    asyncio.run(main())
