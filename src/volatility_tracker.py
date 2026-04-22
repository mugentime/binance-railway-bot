"""
Volatility Tracker - Calculates and caches 10%+ hourly move frequency for symbols
"""
import time
import httpx
from typing import Dict, Optional
from utils import log
import config

class VolatilityTracker:
    """Track historical volatility (10%+ hourly moves) for scoring bonus"""

    def __init__(self, executor=None):
        self.executor = executor
        self.raw_scores: Dict[str, int] = {}  # {symbol: count of 10%+ moves}
        self.normalized_scores: Dict[str, float] = {}  # {symbol: 0-1 normalized score}
        self.last_update_time: float = 0.0
        self.refresh_interval = config.VOLATILITY_REFRESH_HOURS * 3600  # Convert to seconds

    def should_refresh(self) -> bool:
        """Check if volatility scores need refreshing"""
        if not self.raw_scores:
            return True  # No data yet

        elapsed = time.time() - self.last_update_time
        return elapsed >= self.refresh_interval

    def calculate_volatility_scores(self, symbols: list) -> None:
        """
        Calculate 10%+ hourly move frequency for each symbol over last 7 days
        Uses 1-hour klines for efficiency
        """
        log("="*80)
        log("VOLATILITY SCORING: Calculating 10%+ hourly move frequency (7 days)")
        log("="*80)

        start_time = time.time()
        self.raw_scores = {}

        with httpx.Client(timeout=60.0) as client:
            for idx, symbol in enumerate(symbols, 1):
                try:
                    count = self._count_10pct_moves(symbol, client)
                    if count > 0:
                        self.raw_scores[symbol] = count
                        log(f"  {symbol}: {count} hours with 10%+ moves")

                    # Progress update every 25 symbols
                    if idx % 25 == 0:
                        log(f"Progress: {idx}/{len(symbols)} symbols analyzed")

                    time.sleep(0.1)  # Rate limit protection

                except Exception as e:
                    log(f"  Error calculating volatility for {symbol}: {e}", "warning")
                    continue

        # Normalize scores to 0-1 range
        self._normalize_scores()

        self.last_update_time = time.time()
        elapsed = time.time() - start_time

        log("="*80)
        log(f"VOLATILITY SCORING COMPLETE: {len(self.raw_scores)} symbols with 10%+ moves")
        log(f"Time elapsed: {elapsed:.1f}s")
        log("="*80)

    def _count_10pct_moves(self, symbol: str, client: httpx.Client, days: int = 7) -> int:
        """
        Count how many 1-hour candles had 10%+ price range (high-low)
        Returns: count of qualifying hours
        """
        end_time = int(time.time() * 1000)
        start_time = end_time - (days * 24 * 60 * 60 * 1000)

        try:
            params = {
                "symbol": symbol,
                "interval": "1h",
                "startTime": start_time,
                "endTime": end_time,
                "limit": 1000  # 7 days = 168 hours, well under limit
            }

            resp = client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/klines",
                params=params
            )
            resp.raise_for_status()
            klines = resp.json()

            if not klines:
                return 0

            count = 0
            for kline in klines:
                high = float(kline[2])
                low = float(kline[3])

                if low > 0:
                    move_pct = ((high - low) / low) * 100
                    if move_pct >= 10.0:
                        count += 1

            return count

        except Exception as e:
            return 0

    def _normalize_scores(self) -> None:
        """Normalize raw scores to 0-1 range"""
        if not self.raw_scores:
            self.normalized_scores = {}
            return

        min_score = min(self.raw_scores.values())
        max_score = max(self.raw_scores.values())

        if max_score == min_score:
            # All symbols have same score, normalize to 0.5
            self.normalized_scores = {s: 0.5 for s in self.raw_scores.keys()}
        else:
            # Standard min-max normalization
            self.normalized_scores = {
                symbol: (count - min_score) / (max_score - min_score)
                for symbol, count in self.raw_scores.items()
            }

        # Log top 10 normalized scores
        top_10 = sorted(self.normalized_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        log("\nTop 10 Volatility Scores:")
        for symbol, norm_score in top_10:
            raw_count = self.raw_scores[symbol]
            log(f"  {symbol}: {norm_score:.3f} ({raw_count} hours)")

    def get_normalized_score(self, symbol: str) -> float:
        """
        Get normalized volatility score for symbol (0-1 range)
        Returns 0.0 if symbol not in scores
        """
        return self.normalized_scores.get(symbol, 0.0)

    def get_volatility_bonus(self, symbol: str) -> float:
        """
        Calculate volatility bonus multiplier for final score
        Returns: multiplier value (e.g., 0.15 for 50% normalized score with weight 0.3)
        """
        norm_score = self.get_normalized_score(symbol)
        bonus = config.VOLATILITY_WEIGHT * norm_score
        return bonus
