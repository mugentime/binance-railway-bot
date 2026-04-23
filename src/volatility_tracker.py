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
        self.valid_symbols: set = set()  # Symbols that pass volatility band filter
        self.excluded_too_slow: Dict[str, int] = {}  # Excluded: too few moves
        self.excluded_too_chaotic: Dict[str, int] = {}  # Excluded: too many moves
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

        # Filter symbols by volatility band
        self._filter_by_volatility_band()

        # Normalize only the valid symbols to 0-1 range
        self._normalize_scores()

        self.last_update_time = time.time()
        elapsed = time.time() - start_time

        # Log filtering statistics
        log("="*80)
        log("VOLATILITY BAND FILTER RESULTS")
        log("="*80)
        log(f"Total symbols analyzed: {len(symbols)}")
        log(f"Symbols with 10%+ moves: {len(self.raw_scores)}")
        log(f"")
        log(f"PASSED FILTER: {len(self.valid_symbols)} symbols")
        log(f"EXCLUDED (too slow < {config.MIN_VOLATILITY_INSTANCES}): {len(self.excluded_too_slow)} symbols")
        log(f"EXCLUDED (too chaotic > {config.MAX_VOLATILITY_INSTANCES}): {len(self.excluded_too_chaotic)} symbols")
        log(f"")

        # Show top excluded symbols for each category (if any)
        if self.excluded_too_slow:
            top_slow = sorted(self.excluded_too_slow.items(), key=lambda x: x[1], reverse=True)[:5]
            log(f"Top excluded (too slow):")
            for sym, count in top_slow:
                log(f"  {sym}: {count} hours")

        if self.excluded_too_chaotic:
            top_chaotic = sorted(self.excluded_too_chaotic.items(), key=lambda x: x[1], reverse=True)[:5]
            log(f"Top excluded (too chaotic):")
            for sym, count in top_chaotic:
                log(f"  {sym}: {count} hours")

        log(f"")
        log(f"Time elapsed: {elapsed:.1f}s")
        log("="*80)

    def _count_10pct_moves(self, symbol: str, client: httpx.Client, days: int = 7) -> int:
        """
        Count total instances of 10%+ moves using 1-minute klines with sliding 60-minute window
        Returns: total number of 1-minute candles where the 60-minute range exceeded 10%
        """
        end_time = int(time.time() * 1000)
        start_time = end_time - (days * 24 * 60 * 60 * 1000)

        try:
            # Fetch all 1-minute klines (may require multiple requests)
            all_klines = []
            current_start = start_time

            while current_start < end_time:
                params = {
                    "symbol": symbol,
                    "interval": "1m",
                    "startTime": current_start,
                    "endTime": end_time,
                    "limit": 1500  # Max per request
                }

                resp = client.get(
                    f"{config.BINANCE_BASE_URL}/fapi/v1/klines",
                    params=params
                )
                resp.raise_for_status()
                klines = resp.json()

                if not klines:
                    break

                all_klines.extend(klines)
                current_start = klines[-1][6] + 1  # Close time + 1ms

            if len(all_klines) < 60:
                return 0

            # Sliding window of 60 candles (60 minutes)
            count = 0
            for i in range(len(all_klines) - 59):
                window = all_klines[i:i+60]

                # Get high and low within this 60-minute window
                window_high = max(float(k[2]) for k in window)  # High price
                window_low = min(float(k[3]) for k in window)   # Low price

                # Calculate percentage move
                if window_low > 0:
                    move_pct = ((window_high - window_low) / window_low) * 100
                    if move_pct >= 10.0:
                        count += 1

            return count

        except Exception as e:
            return 0

    def _filter_by_volatility_band(self) -> None:
        """
        Filter symbols by volatility band (MIN to MAX instances)
        Excludes symbols that are too slow or too chaotic
        """
        self.valid_symbols = set()
        self.excluded_too_slow = {}
        self.excluded_too_chaotic = {}

        for symbol, count in self.raw_scores.items():
            if count < config.MIN_VOLATILITY_INSTANCES:
                self.excluded_too_slow[symbol] = count
            elif count > config.MAX_VOLATILITY_INSTANCES:
                self.excluded_too_chaotic[symbol] = count
            else:
                self.valid_symbols.add(symbol)

        # Remove excluded symbols from raw_scores for normalization
        # Keep original raw_scores for logging purposes
        original_raw_scores = self.raw_scores.copy()
        self.raw_scores = {
            symbol: count for symbol, count in original_raw_scores.items()
            if symbol in self.valid_symbols
        }

    def _normalize_scores(self) -> None:
        """Normalize raw scores to 0-1 range (only valid symbols)"""
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

        # Log top 10 normalized scores (only valid symbols that passed filter)
        top_10 = sorted(self.normalized_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        log("\nTop 10 Valid Symbols by Volatility Score:")
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

    def is_valid_symbol(self, symbol: str) -> bool:
        """
        Check if symbol should be allowed for trading
        Returns: False only if explicitly excluded (too slow/chaotic)
                 True for all other symbols (including those not in cache)
        """
        # Exclude only if explicitly found to be too slow or too chaotic
        if symbol in self.excluded_too_slow or symbol in self.excluded_too_chaotic:
            return False
        # Allow everything else (including symbols not in cache)
        return True
