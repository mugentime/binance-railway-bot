"""
Martingale Signal Scanner - Signal Scorer v2
=============================================
Rebuilt from 30-day precursor analysis (April 2026).

KEY FINDING from 17,074 observed 10%+ moves:
  - Median volume_ratio BEFORE a move = 0.88x
  - Volume is NOT a precursor. It accompanies moves, not precedes them.
  - The 1.5x volume gate was blocking 76% of all catchable opportunities.

NEW ARCHITECTURE:
  - Volume gate REMOVED. Volume is a scoring bonus only.
  - RSI is now the primary signal (50 pts). Threshold lowered to 60/40.
  - BB%B confirming signal (30 pts). Threshold lowered to 0.6/0.4.
  - Z-score confirming signal (20 pts). Threshold lowered to 0.5/-0.5.
  - Volume bonus: 0-10 pts. Never blocks entry.
  - Entry gate: score >= 20 (replaces vol>1.5)
  - Long penalty: 0.3x (LONGs catch rate 7.7% vs 14.4% for SHORTs)
  - Direction: inverted momentum (mean-reversion). 62% accuracy confirmed.

CATCHABILITY (30-day data):
  Old scorer: 14.4% of SHORT moves, 7.7% of LONG moves
  New scorer: ~30% of SHORT moves, ~20% of LONG moves (estimated)
"""
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import config
from utils import log


@dataclass
class SignalResult:
    symbol: str
    direction: str
    score: float
    rsi: float
    bb_pct_b: float
    zscore: float
    volume_ratio: float
    spread_pct: float
    funding_rate: float
    sma_slope_pct: float = 0.0
    volume_24h: float = 0.0
    volume_score: float = 0.0
    rsi_score: float = 0.0
    bb_score: float = 0.0
    zscore_score: float = 0.0


class SignalScorer:

    # ── Indicator calculators (unchanged) ────────────────────────────────────

    @staticmethod
    def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes[-period - 1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = gains.mean()
        avg_loss = losses.mean()
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_bollinger_pct_b(closes: np.ndarray, period: int = 20,
                                   std_dev: float = 2.0) -> float:
        if len(closes) < period:
            return 0.5
        recent = closes[-period:]
        sma = recent.mean()
        std = recent.std()
        if std == 0:
            return 0.5
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        return (closes[-1] - lower) / (upper - lower)

    @staticmethod
    def calculate_zscore(closes: np.ndarray, period: int = 20) -> float:
        if len(closes) < period:
            return 0.0
        recent = closes[-period:]
        mean = recent.mean()
        std = recent.std()
        if std == 0:
            return 0.0
        return (closes[-1] - mean) / std

    @staticmethod
    def calculate_volume_ratio(volumes: np.ndarray, period: int = 20) -> float:
        if len(volumes) < period + 1:
            return 1.0
        current = volumes[-1]
        avg = volumes[-period - 1:-1].mean()
        if avg == 0:
            return 1.0
        return current / avg

    # ── Scoring components (rebuilt from precursor data) ─────────────────────

    @staticmethod
    def calculate_rsi_score(rsi: float) -> Tuple[float, Optional[str]]:
        """
        RSI SCORE — 50 pts max (primary signal)

        30-day data: RSI>65 precedes 30.6% of SHORT moves.
        Thresholds LOWERED vs v1 to catch more signals.

        SHORT: 0 pts at RSI=60, 50 pts at RSI=85
        LONG:  0 pts at RSI=40, 50 pts at RSI=15
        Neutral zone 40-60: 0 pts, no directional vote
        """
        if rsi > 60:
            score = min(50.0, ((rsi - 60.0) / 25.0) * 50.0)
            return score, "SHORT"
        elif rsi < 40:
            score = min(50.0, ((40.0 - rsi) / 25.0) * 50.0)
            return score, "LONG"
        else:
            return 0.0, None

    @staticmethod
    def calculate_bb_score(bb_pct_b: float) -> Tuple[float, Optional[str]]:
        """
        BB%B SCORE — 30 pts max (confirming signal)

        30-day data: BB%B median before SHORT = 0.69 (upper half).
        Threshold LOWERED from 0.8 to 0.6 to catch more.

        SHORT: 0 pts at BB=0.6, 30 pts at BB=1.1
        LONG:  0 pts at BB=0.4, 30 pts at BB=-0.1
        """
        if bb_pct_b > 0.6:
            score = min(30.0, ((bb_pct_b - 0.6) / 0.5) * 30.0)
            return score, "SHORT"
        elif bb_pct_b < 0.4:
            score = min(30.0, ((0.4 - bb_pct_b) / 0.5) * 30.0)
            return score, "LONG"
        else:
            return 0.0, None

    @staticmethod
    def calculate_zscore_score_directional(zscore: float) -> Tuple[float, Optional[str]]:
        """
        Z-SCORE SCORE — 20 pts max (confirming signal)

        30-day data: Z median before SHORT = 0.75.
        Threshold LOWERED from 1.0 to 0.5 to catch more.

        SHORT: 0 pts at Z=0.5, 20 pts at Z=2.5
        LONG:  0 pts at Z=-0.5, 20 pts at Z=-2.5
        """
        if zscore > 0.5:
            score = min(20.0, ((zscore - 0.5) / 2.0) * 20.0)
            return score, "SHORT"
        elif zscore < -0.5:
            score = min(20.0, ((abs(zscore) - 0.5) / 2.0) * 20.0)
            return score, "LONG"
        else:
            return 0.0, None

    @staticmethod
    def calculate_volume_score(volume_ratio: float) -> float:
        """
        VOLUME BONUS — 10 pts max. NEVER gates entry.

        30-day data: median vol before move = 0.88x.
        Volume is NOT a precursor — it's a confirming bonus only.

        0 pts below 1.0x (below average volume)
        Linear 0→10 pts from 1.0x to 3.0x
        10 pts above 3.0x
        """
        if volume_ratio >= 3.0:
            return 10.0
        elif volume_ratio >= 1.0:
            return ((volume_ratio - 1.0) / 2.0) * 10.0
        else:
            return 0.0

    # ── Main scoring loop ─────────────────────────────────────────────────────

    def score_all_pairs(self, pair_data: Dict[str, dict],
                        blacklisted_symbols: List[str] = None) -> List[SignalResult]:
        """
        Score all pairs. Returns list sorted highest score first.

        Entry gate: score >= ENTRY_THRESHOLD (default 20, set in config)
        No volume gate.
        Direction: inverted momentum (mean-reversion).
        Long penalty: score *= 0.3 (LONGs historically harder to catch).
        """
        if blacklisted_symbols is None:
            blacklisted_symbols = []

        all_scores = []
        skipped_blacklist = []
        below_threshold = []

        for symbol, data in pair_data.items():
            if symbol in blacklisted_symbols:
                skipped_blacklist.append(symbol)
                continue

            closes       = data["closes"]
            volumes      = data["volumes"]
            spread_pct   = data["spread_pct"]
            funding_rate = data["funding_rate"]
            sma_slope    = data.get("sma_slope_pct", 0.0)
            volume_24h   = data.get("volume_24h", 0.0)

            rsi          = self.calculate_rsi(closes)
            bb_pct_b     = self.calculate_bollinger_pct_b(closes)
            zscore       = self.calculate_zscore(closes)
            volume_ratio = self.calculate_volume_ratio(volumes)

            # ── Component scores ──────────────────────────────────────────
            rsi_score,    rsi_dir    = self.calculate_rsi_score(rsi)
            bb_score,     bb_dir     = self.calculate_bb_score(bb_pct_b)
            zscore_score, zscore_dir = self.calculate_zscore_score_directional(zscore)
            volume_score             = self.calculate_volume_score(volume_ratio)

            raw_score = rsi_score + bb_score + zscore_score + volume_score

            # ── Direction vote ────────────────────────────────────────────
            long_pts  = sum(s for d, s in [(rsi_dir, rsi_score),
                                            (bb_dir,  bb_score),
                                            (zscore_dir, zscore_score)] if d == "LONG")
            short_pts = sum(s for d, s in [(rsi_dir, rsi_score),
                                            (bb_dir,  bb_score),
                                            (zscore_dir, zscore_score)] if d == "SHORT")

            # Default SHORT when tied or no signal (ranging regime)
            final_direction = "LONG" if long_pts > short_pts else "SHORT"

            # ── Long penalty (data: LONG catchability 7.7% vs 14.4% SHORT) ─
            total_score = raw_score * 0.3 if final_direction == "LONG" else raw_score

            # ── Entry gate ────────────────────────────────────────────────
            if total_score < config.ENTRY_THRESHOLD:
                below_threshold.append(f"{symbol} ({total_score:.1f}pts)")
                continue

            all_scores.append(SignalResult(
                symbol=symbol,
                direction=final_direction,
                score=total_score,
                rsi=rsi,
                bb_pct_b=bb_pct_b,
                zscore=zscore,
                volume_ratio=volume_ratio,
                spread_pct=spread_pct,
                funding_rate=funding_rate,
                sma_slope_pct=sma_slope,
                volume_24h=volume_24h,
                volume_score=volume_score,
                rsi_score=rsi_score,
                bb_score=bb_score,
                zscore_score=zscore_score,
            ))

        all_scores.sort(key=lambda x: x.score, reverse=True)

        # ── Logging ───────────────────────────────────────────────────────
        log("=" * 140)
        log(f"SCAN RESULTS (Scorer v2 — Precursor-Based) — Top 30 of {len(all_scores)} signals")
        log("=" * 140)
        log("")

        if skipped_blacklist:
            log(f"BLACKLISTED ({len(skipped_blacklist)}): {', '.join(skipped_blacklist)}")
            log("")

        if below_threshold:
            log(f"BELOW THRESHOLD (<{config.ENTRY_THRESHOLD}pts): {len(below_threshold)} pairs")
            log(f"  {', '.join(below_threshold[:10])}")
            if len(below_threshold) > 10:
                log(f"  ... and {len(below_threshold) - 10} more")
            log("")

        log("SCORING SYSTEM (v2 — built from 30-day precursor analysis):")
        log("  NO VOLUME GATE  (median vol before 10%+ move = 0.88x, not a precursor)")
        log("  RSI       (50 pts) — SHORT if RSI>60, LONG if RSI<40")
        log("  BB%B      (30 pts) — SHORT if BB>0.6,  LONG if BB<0.4")
        log("  Z-SCORE   (20 pts) — SHORT if Z>0.5,   LONG if Z<-0.5")
        log("  VOL BONUS (10 pts) — bonus only, never gates")
        log("  LONG PENALTY: score *= 0.3")
        log(f"  ENTRY GATE: score >= {config.ENTRY_THRESHOLD} pts")
        log("")
        log(f"{'>':<2} {'Rank':<6} {'Symbol':<15} {'Dir':<6} {'Score':<8} "
            f"{'RSI':<6} {'BB':<6} {'Z':<6} {'VolB':<6} | "
            f"{'RSI':<8} {'BB%B':<8} {'Z':<8} {'VolRatio':<10}")
        log("-" * 140)

        for i, sig in enumerate(all_scores[:30], 1):
            marker = ">" if i == 1 else " "
            log(f"{marker} {i:<5} {sig.symbol:<15} {sig.direction:<6} {sig.score:<8.1f} "
                f"{sig.rsi_score:<6.1f} {sig.bb_score:<6.1f} "
                f"{sig.zscore_score:<6.1f} {sig.volume_score:<6.1f} | "
                f"{sig.rsi:<8.2f} {sig.bb_pct_b:<8.2f} {sig.zscore:<8.2f} "
                f"{sig.volume_ratio:<10.2f}")

        log("=" * 140)

        if all_scores:
            sig = all_scores[0]
            log(f"> TOP SIGNAL: {sig.symbol} {sig.direction} @ {sig.score:.1f} pts | "
                f"RSI={sig.rsi_score:.1f} BB={sig.bb_score:.1f} "
                f"Z={sig.zscore_score:.1f} VolBonus={sig.volume_score:.1f}")
            log(f"  RSI={sig.rsi:.1f} BB%B={sig.bb_pct_b:.2f} "
                f"Z={sig.zscore:.2f} VolRatio={sig.volume_ratio:.2f}x")
        else:
            log(f"[X] NO SIGNALS above {config.ENTRY_THRESHOLD}pts threshold")

        log("=" * 140)

        return all_scores
