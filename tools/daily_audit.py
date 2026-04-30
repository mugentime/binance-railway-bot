"""
Daily Performance Audit
=======================
Fetches last 24h of 5m candles for all curated pairs.
Finds every 10%+ move that started in that window.
Scores the indicators at the candle BEFORE each move.
Reports: hit rate, direction accuracy, what we're missing, optimization hints.

Run standalone:
    python tools/daily_audit.py

Optional flags:
    --hours 48          look back N hours (default 24)
    --move-pct 0.10     move threshold (default 0.10 = 10%)
    --top 20            show top N missed/caught moves
    --export            write results to tools/audit_results.json
"""

import sys
import os
import asyncio
import json
import argparse
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

import numpy as np
import httpx

# ── path setup so we can import from src/ ────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config
from signal_scorer import SignalScorer

BINANCE_URL = config.BINANCE_BASE_URL
KLINE_INTERVAL = "5m"
CANDLES_PER_HOUR = 12  # 60 / 5


# ── data structures ──────────────────────────────────────────────────────────

@dataclass
class Move:
    symbol: str
    start_ts: int           # Unix ms of candle where move began
    start_price: float
    peak_price: float
    move_pct: float         # always positive
    direction: str          # "LONG" (price went up) or "SHORT" (price went down)
    candles_to_peak: int
    # Indicators computed at the candle BEFORE the move
    rsi: float
    bb_pct_b: float
    zscore: float
    volume_ratio: float
    # Scorer output
    score: float
    predicted_direction: str
    direction_correct: bool
    volume_gated: bool      # volume_ratio > 1.5


@dataclass
class AuditResult:
    run_at: str
    lookback_hours: int
    move_threshold_pct: float
    total_moves: int
    total_pairs_with_moves: int
    volume_gated_count: int
    volume_gated_pct: float
    direction_correct_count: int
    direction_correct_pct: float
    full_hit_count: int
    full_hit_pct: float
    top_missed: List[dict]
    top_caught: List[dict]
    scoring_histogram: dict
    moves: List[dict]


# ── Binance fetch helpers ─────────────────────────────────────────────────────

async def fetch_klines(
    client: httpx.AsyncClient,
    symbol: str,
    lookback_hours: int,
    semaphore: asyncio.Semaphore,
) -> Optional[np.ndarray]:
    """Returns array of shape (N, 6): [open_time, open, high, low, close, volume]"""
    limit = min(lookback_hours * CANDLES_PER_HOUR + 60, 1500)  # +60 for indicator warmup
    async with semaphore:
        try:
            resp = await client.get(
                f"{BINANCE_URL}/fapi/v1/klines",
                params={"symbol": symbol, "interval": KLINE_INTERVAL, "limit": limit},
                timeout=20.0,
            )
            resp.raise_for_status()
            raw = resp.json()
            arr = np.array(
                [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                 for k in raw]
            )
            return arr
        except Exception as e:
            print(f"  [WARN] {symbol}: {e}")
            return None


# ── Move detection ────────────────────────────────────────────────────────────

def find_moves(
    klines: np.ndarray,
    move_threshold: float,
    lookback_candles: int,
    max_candles_to_peak: int = 72,  # 6 hours
) -> List[Tuple[int, float, float, int, str]]:
    """
    For each candle in the lookback window, look forward up to max_candles_to_peak.
    If max abs move >= threshold, record it.
    Returns list of (candle_index, start_price, peak_price, candles_to_peak, direction)
    Deduplicates: only one move per 5-candle window (keeps largest).
    """
    n = len(klines)
    start_idx = max(50, n - lookback_candles)  # 50 candle warmup
    moves = []

    for i in range(start_idx, n - 2):
        start_price = klines[i, 4]  # close price = entry
        if start_price == 0:
            continue

        best_up = 0.0
        best_down = 0.0
        best_up_idx = i
        best_down_idx = i

        for j in range(i + 1, min(i + max_candles_to_peak + 1, n)):
            high = klines[j, 2]
            low = klines[j, 3]
            up_move = (high - start_price) / start_price
            down_move = (start_price - low) / start_price
            if up_move > best_up:
                best_up = up_move
                best_up_idx = j
            if down_move > best_down:
                best_down = down_move
                best_down_idx = j

        if best_up >= move_threshold and best_up >= best_down:
            moves.append((i, start_price, klines[best_up_idx, 2], best_up_idx - i, "LONG"))
        elif best_down >= move_threshold and best_down > best_up:
            moves.append((i, start_price, klines[best_down_idx, 3], best_down_idx - i, "SHORT"))

    if not moves:
        return moves

    # Deduplicate: within ±5 candles, keep only largest move
    moves.sort(key=lambda x: abs(x[2] - x[1]) / x[1], reverse=True)
    kept = []
    used_candles = set()

    for m in moves:
        start_i = m[0]
        if any(abs(start_i - u) <= 5 for u in used_candles):
            continue
        kept.append(m)
        used_candles.add(start_i)

    return kept


# ── Indicator computation ─────────────────────────────────────────────────────

def compute_indicators_at(klines: np.ndarray, candle_idx: int):
    """Compute RSI, BB%B, Z-score, volume_ratio at candle_idx using history up to that point."""
    closes = klines[:candle_idx + 1, 4]
    volumes = klines[:candle_idx + 1, 5]

    rsi = SignalScorer.calculate_rsi(closes, period=14)
    bb = SignalScorer.calculate_bollinger_pct_b(closes, period=20)
    z = SignalScorer.calculate_zscore(closes, period=20)
    vol_ratio = SignalScorer.calculate_volume_ratio(volumes, period=20)
    return rsi, bb, z, vol_ratio


def score_signal(rsi, bb, z, vol_ratio, actual_direction: str):
    """Run scorer v2 components and return (score, predicted_direction, dir_correct, above_threshold)."""
    scorer = SignalScorer

    rsi_score, rsi_dir = scorer.calculate_rsi_score(rsi)
    bb_score,  bb_dir  = scorer.calculate_bb_score(bb)
    z_score,   z_dir   = scorer.calculate_zscore_score_directional(z)
    volume_score       = scorer.calculate_volume_score(vol_ratio)

    raw = rsi_score + bb_score + z_score + volume_score

    long_s  = sum(s for d, s in [(rsi_dir, rsi_score), (bb_dir, bb_score), (z_dir, z_score)] if d == "LONG")
    short_s = sum(s for d, s in [(rsi_dir, rsi_score), (bb_dir, bb_score), (z_dir, z_score)] if d == "SHORT")
    predicted = "LONG" if long_s > short_s else "SHORT"

    # Long penalty (same as live bot)
    if predicted == "LONG":
        raw *= 0.3

    above_threshold = raw >= config.ENTRY_THRESHOLD  # 20 pts, no vol gate
    return raw, predicted, predicted == actual_direction, above_threshold


# ── Main audit logic ──────────────────────────────────────────────────────────

async def run_audit(lookback_hours: int, move_threshold: float, top_n: int, export: bool):
    symbols = config.CURATED_PAIR_LIST
    lookback_candles = lookback_hours * CANDLES_PER_HOUR + 60

    print(f"\n{'='*70}")
    print(f"  DAILY PERFORMANCE AUDIT")
    print(f"  Lookback: {lookback_hours}h | Move threshold: {move_threshold*100:.0f}%+")
    print(f"  Pairs: {len(symbols)}")
    print(f"{'='*70}\n")

    semaphore = asyncio.Semaphore(15)
    all_moves: List[Move] = []

    print("Fetching klines...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = {sym: fetch_klines(client, sym, lookback_hours, semaphore) for sym in symbols}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        klines_map = dict(zip(tasks.keys(), results))

    print(f"Processing moves...\n")

    for symbol, klines in klines_map.items():
        if klines is None or isinstance(klines, Exception) or len(klines) < 55:
            continue

        moves = find_moves(klines, move_threshold, lookback_candles)
        for (candle_idx, start_price, peak_price, candles_to_peak, direction) in moves:
            if candle_idx < 50:
                continue

            rsi, bb, z, vol_ratio = compute_indicators_at(klines, candle_idx)
            move_pct = abs(peak_price - start_price) / start_price
            score, predicted, dir_correct, above_threshold = score_signal(rsi, bb, z, vol_ratio, direction)

            all_moves.append(Move(
                symbol=symbol,
                start_ts=int(klines[candle_idx, 0]),
                start_price=start_price,
                peak_price=peak_price,
                move_pct=move_pct,
                direction=direction,
                candles_to_peak=candles_to_peak,
                rsi=rsi,
                bb_pct_b=bb,
                zscore=z,
                volume_ratio=vol_ratio,
                score=score,
                predicted_direction=predicted,
                direction_correct=dir_correct,
                volume_gated=above_threshold,
            ))

    if not all_moves:
        print("No 10%+ moves found. Try --hours 48 or --move-pct 0.05")
        return

    # ── Stats ─────────────────────────────────────────────────────────────────
    total = len(all_moves)
    vol_gated = [m for m in all_moves if m.volume_gated]
    dir_correct = [m for m in all_moves if m.volume_gated and m.direction_correct]
    full_hit = dir_correct

    pairs_with_moves = len(set(m.symbol for m in all_moves))
    vol_gated_pct = len(vol_gated) / total * 100
    dir_pct = len(dir_correct) / len(vol_gated) * 100 if vol_gated else 0
    hit_pct = len(full_hit) / total * 100

    # Score histogram for volume-gated moves
    histogram = {"0-10": 0, "10-20": 0, "20-30": 0, "30-40": 0, "40-50": 0, "50+": 0}
    for m in vol_gated:
        s = m.score
        if s < 10: histogram["0-10"] += 1
        elif s < 20: histogram["10-20"] += 1
        elif s < 30: histogram["20-30"] += 1
        elif s < 40: histogram["30-40"] += 1
        elif s < 50: histogram["40-50"] += 1
        else: histogram["50+"] += 1

    missed = [m for m in all_moves if not m.volume_gated or not m.direction_correct]
    missed.sort(key=lambda x: x.move_pct, reverse=True)
    caught = sorted(full_hit, key=lambda x: x.score, reverse=True)

    # ── Print report ──────────────────────────────────────────────────────────
    print(f"{'='*70}")
    print(f"  SUMMARY — last {lookback_hours}h | threshold {move_threshold*100:.0f}%+")
    print(f"{'='*70}")
    print(f"  Total moves found      : {total}")
    print(f"  Pairs with moves       : {pairs_with_moves}")
    print(f"")
    print(f"  Above threshold (score>={config.ENTRY_THRESHOLD})  : {len(vol_gated)}/{total}  ({vol_gated_pct:.1f}%)")
    print(f"  Direction correct      : {len(dir_correct)}/{len(vol_gated)}  ({dir_pct:.1f}%) [of above-threshold]")
    print(f"  ── FULL HIT RATE ──    : {len(full_hit)}/{total}  ({hit_pct:.1f}%)")
    print(f"")
    print(f"  Score distribution (vol-gated moves):")
    for bucket, count in histogram.items():
        bar = "█" * count
        print(f"    {bucket:>6} pts : {count:>3}  {bar}")
    print(f"")

    # ── Missed moves ──────────────────────────────────────────────────────────
    print(f"{'='*70}")
    print(f"  TOP {top_n} MISSED MOVES")
    print(f"{'='*70}")
    print(f"  {'Symbol':<15} {'Dir':<6} {'Move%':<8} {'VolRatio':<10} {'Score':<8} {'RSI':<6} {'BB%B':<6} {'Z':<6}  Reason")
    print(f"  {'-'*85}")
    for m in missed[:top_n]:
        reason = []
        if not m.volume_gated:
            reason.append(f"vol={m.volume_ratio:.2f}x<1.5")
        if m.volume_gated and not m.direction_correct:
            reason.append(f"predicted {m.predicted_direction} was {m.direction}")
        ts = datetime.utcfromtimestamp(m.start_ts / 1000).strftime("%H:%M")
        print(f"  {m.symbol:<15} {m.direction:<6} {m.move_pct*100:>6.1f}%  "
              f"{m.volume_ratio:>7.2f}x   {m.score:>6.1f}   "
              f"{m.rsi:>5.1f}  {m.bb_pct_b:>5.2f}  {m.zscore:>5.2f}  "
              f"@{ts}  {', '.join(reason)}")

    print(f"")

    # ── Caught moves ──────────────────────────────────────────────────────────
    print(f"{'='*70}")
    print(f"  TOP {top_n} CAUGHT MOVES")
    print(f"{'='*70}")
    print(f"  {'Symbol':<15} {'Dir':<6} {'Move%':<8} {'VolRatio':<10} {'Score':<8} {'RSI':<6} {'BB%B':<6} {'Z':<6}")
    print(f"  {'-'*75}")
    for m in caught[:top_n]:
        ts = datetime.utcfromtimestamp(m.start_ts / 1000).strftime("%H:%M")
        print(f"  {m.symbol:<15} {m.direction:<6} {m.move_pct*100:>6.1f}%  "
              f"{m.volume_ratio:>7.2f}x   {m.score:>6.1f}   "
              f"{m.rsi:>5.1f}  {m.bb_pct_b:>5.2f}  {m.zscore:>5.2f}  @{ts}")

    print(f"")

    # ── Miss analysis ─────────────────────────────────────────────────────────
    not_vol_gated = [m for m in all_moves if not m.volume_gated]
    wrong_dir = [m for m in all_moves if m.volume_gated and not m.direction_correct]

    print(f"{'='*70}")
    print(f"  MISS ANALYSIS")
    print(f"{'='*70}")
    print(f"  Below score threshold (<{config.ENTRY_THRESHOLD}pts)   : {len(not_vol_gated)} moves  ({len(not_vol_gated)/total*100:.0f}%)")
    if not_vol_gated:
        avg_vol = np.mean([m.volume_ratio for m in not_vol_gated])
        avg_score = np.mean([m.score for m in not_vol_gated])
        print(f"    Avg score of these moves  : {avg_score:.1f}pts")
        print(f"    Avg vol_ratio             : {avg_vol:.2f}x")
        print(f"    → No strong RSI/BB/Z signal before these moves started.")

    print(f"  Wrong direction prediction       : {len(wrong_dir)} moves  ({len(wrong_dir)/total*100:.0f}%)")
    if wrong_dir:
        longs_wrong = [m for m in wrong_dir if m.direction == "LONG"]
        shorts_wrong = [m for m in wrong_dir if m.direction == "SHORT"]
        print(f"    LONG moves predicted wrong     : {len(longs_wrong)}  (RSI was overbought but kept pumping)")
        print(f"    SHORT moves predicted wrong    : {len(shorts_wrong)}  (RSI was oversold but kept dumping)")
        if longs_wrong:
            avg_rsi = np.mean([m.rsi for m in longs_wrong])
            print(f"    Avg RSI of wrongly-predicted LONGs   : {avg_rsi:.1f}")
        if shorts_wrong:
            avg_rsi = np.mean([m.rsi for m in shorts_wrong])
            print(f"    Avg RSI of wrongly-predicted SHORTs  : {avg_rsi:.1f}")

    # ── Optimization hints ────────────────────────────────────────────────────
    print(f"")
    print(f"{'='*70}")
    print(f"  OPTIMIZATION HINTS")
    print(f"{'='*70}")

    if vol_gated_pct < 40:
        print(f"  ⚠  Volume gate (<1.5x) blocking {100-vol_gated_pct:.0f}% of moves.")
        print(f"     Consider lowering volume gate to 1.2x to capture more opportunities.")

    if dir_pct < 45 and vol_gated:
        print(f"  ⚠  Direction accuracy {dir_pct:.0f}% — inverted momentum working BELOW chance.")
        print(f"     Market may be trending. Consider reducing long_penalty or adjusting regime detection.")

    if dir_pct >= 55 and vol_gated:
        print(f"  ✓  Direction accuracy {dir_pct:.0f}% — inverted momentum working well.")

    avg_score_hits = np.mean([m.score for m in full_hit]) if full_hit else 0
    avg_score_miss_vol = np.mean([m.score for m in vol_gated if not m.direction_correct]) if [m for m in vol_gated if not m.direction_correct] else 0
    print(f"  Avg score of CAUGHT moves        : {avg_score_hits:.1f}")
    print(f"  Avg score of vol-gated MISSES    : {avg_score_miss_vol:.1f}")

    longs_caught = [m for m in full_hit if m.direction == "LONG"]
    shorts_caught = [m for m in full_hit if m.direction == "SHORT"]
    print(f"")
    print(f"  Caught LONG  moves : {len(longs_caught)}")
    print(f"  Caught SHORT moves : {len(shorts_caught)}")
    if longs_caught and len(shorts_caught) > 0 and len(longs_caught) / len(shorts_caught) < 0.15:
        print(f"  ⚠  Long penalty (0.3x) very aggressive — almost zero LONGs caught.")
        print(f"     If market is pumping, consider raising long_penalty multiplier (0.3 → 0.5).")

    print(f"\n{'='*70}\n")

    # ── Export ────────────────────────────────────────────────────────────────
    result = AuditResult(
        run_at=datetime.now(timezone.utc).isoformat(),
        lookback_hours=lookback_hours,
        move_threshold_pct=move_threshold,
        total_moves=total,
        total_pairs_with_moves=pairs_with_moves,
        volume_gated_count=len(vol_gated),
        volume_gated_pct=vol_gated_pct,
        direction_correct_count=len(dir_correct),
        direction_correct_pct=dir_pct,
        full_hit_count=len(full_hit),
        full_hit_pct=hit_pct,
        top_missed=[asdict(m) for m in missed[:top_n]],
        top_caught=[asdict(m) for m in caught[:top_n]],
        scoring_histogram=histogram,
        moves=[asdict(m) for m in all_moves],
    )

    if export:
        out_path = os.path.join(os.path.dirname(__file__), "audit_results.json")
        with open(out_path, "w") as f:
            json.dump(asdict(result), f, indent=2, default=str)
        print(f"Exported to {out_path}\n")

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daily performance audit")
    parser.add_argument("--hours", type=int, default=24, help="Lookback hours (default 24)")
    parser.add_argument("--move-pct", type=float, default=0.10, help="Move threshold 0-1 (default 0.10)")
    parser.add_argument("--top", type=int, default=20, help="Top N moves to show")
    parser.add_argument("--export", action="store_true", help="Export JSON to tools/audit_results.json")
    args = parser.parse_args()

    asyncio.run(run_audit(
        lookback_hours=args.hours,
        move_threshold=args.move_pct,
        top_n=args.top,
        export=args.export,
    ))


if __name__ == "__main__":
    main()
