"""
Precursor Analysis — What actually happens BEFORE a 10%+ move?
===============================================================
Fetches 30 days of 5m klines for all curated pairs.
Finds every 10%+ move. Measures indicator values at the candle BEFORE it starts.
Outputs the true distribution of RSI, BB%B, Z-score, and volume_ratio
that precede 10%+ moves — so we can build a scorer based on real data.

Run:
    python tools/analyze_precursors.py

Optional:
    --days 30           lookback (default 30)
    --move-pct 0.10     move threshold (default 0.10)
    --export            save tools/precursor_results.json
"""

import sys
import os
import asyncio
import json
import argparse
from datetime import datetime, timezone
from collections import defaultdict

import numpy as np
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config
from signal_scorer import SignalScorer

BINANCE_URL = config.BINANCE_BASE_URL
KLINE_INTERVAL = "5m"
CANDLES_PER_DAY = 288  # 60*24/5


# ── Fetch klines in pages ─────────────────────────────────────────────────────

async def fetch_klines_paged(
    client: httpx.AsyncClient,
    symbol: str,
    days: int,
    semaphore: asyncio.Semaphore,
) -> np.ndarray:
    """
    Fetch up to `days` days of 5m klines, paginating if needed.
    Returns array shape (N, 6): [open_time, open, high, low, close, volume]
    """
    limit_per_req = 1500
    total_candles = days * CANDLES_PER_DAY
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - (days * 24 * 3600 * 1000)

    all_rows = []
    current_start = start_ms

    async with semaphore:
        while current_start < end_ms and len(all_rows) < total_candles:
            try:
                resp = await client.get(
                    f"{BINANCE_URL}/fapi/v1/klines",
                    params={
                        "symbol": symbol,
                        "interval": KLINE_INTERVAL,
                        "startTime": current_start,
                        "endTime": end_ms,
                        "limit": limit_per_req,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                raw = resp.json()
                if not raw:
                    break
                for k in raw:
                    all_rows.append([int(k[0]), float(k[1]), float(k[2]),
                                     float(k[3]), float(k[4]), float(k[5])])
                current_start = raw[-1][6] + 1  # close_time + 1ms
                await asyncio.sleep(0.05)        # gentle rate limit
            except Exception as e:
                print(f"  [WARN] {symbol}: {e}")
                break

    if not all_rows:
        return None
    return np.array(all_rows)


# ── Move detection (same logic as daily_audit.py) ────────────────────────────

def find_moves(klines: np.ndarray, move_threshold: float,
               max_candles_to_peak: int = 72):
    """
    For each candle, look forward up to max_candles_to_peak.
    Return list of (candle_idx, start_price, peak_price, candles_to_peak, direction)
    Deduplicated: only one move per 5-candle window (largest).
    """
    n = len(klines)
    moves = []

    warmup = 50  # need 50 candles for indicators
    for i in range(warmup, n - 2):
        start_price = klines[i, 4]
        if start_price == 0:
            continue

        best_up = best_down = 0.0
        best_up_idx = best_down_idx = i

        for j in range(i + 1, min(i + max_candles_to_peak + 1, n)):
            up = (klines[j, 2] - start_price) / start_price
            dn = (start_price - klines[j, 3]) / start_price
            if up > best_up:
                best_up = up; best_up_idx = j
            if dn > best_down:
                best_down = dn; best_down_idx = j

        if best_up >= move_threshold and best_up >= best_down:
            moves.append((i, start_price, klines[best_up_idx, 2], best_up_idx - i, "LONG"))
        elif best_down >= move_threshold and best_down > best_up:
            moves.append((i, start_price, klines[best_down_idx, 3], best_down_idx - i, "SHORT"))

    if not moves:
        return moves

    # Deduplicate: keep only largest per 5-candle window
    moves.sort(key=lambda x: abs(x[2] - x[1]) / x[1], reverse=True)
    kept, used = [], set()
    for m in moves:
        if any(abs(m[0] - u) <= 5 for u in used):
            continue
        kept.append(m)
        used.add(m[0])
    return kept


# ── Indicator computation ─────────────────────────────────────────────────────

def indicators_at(klines: np.ndarray, idx: int):
    closes  = klines[:idx + 1, 4]
    volumes = klines[:idx + 1, 5]
    rsi     = SignalScorer.calculate_rsi(closes)
    bb      = SignalScorer.calculate_bollinger_pct_b(closes)
    z       = SignalScorer.calculate_zscore(closes)
    vol     = SignalScorer.calculate_volume_ratio(volumes)
    return rsi, bb, z, vol


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(days: int, move_pct: float, export: bool):
    symbols = [s for s in config.CURATED_PAIR_LIST
               if s not in config.EXCLUDED_SYMBOLS]

    print(f"\n{'='*70}")
    print(f"  PRECURSOR ANALYSIS — {days}-day lookback | {move_pct*100:.0f}%+ moves")
    print(f"  Pairs: {len(symbols)}")
    print(f"  Fetching klines (this takes ~3-5 min)...")
    print(f"{'='*70}\n")

    semaphore = asyncio.Semaphore(8)  # conservative — 30-day fetch is heavy
    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks = {s: fetch_klines_paged(client, s, days, semaphore) for s in symbols}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        klines_map = dict(zip(tasks.keys(), results))

    print(f"Klines fetched. Analyzing precursors...\n")

    # Collect precursor snapshots
    records = []  # list of dicts

    for symbol, klines in klines_map.items():
        if klines is None or isinstance(klines, Exception) or len(klines) < 55:
            continue

        moves = find_moves(klines, move_pct)
        for (idx, start_price, peak_price, candles_to_peak, direction) in moves:
            if idx < 50:
                continue
            rsi, bb, z, vol = indicators_at(klines, idx)
            move_size = abs(peak_price - start_price) / start_price
            records.append({
                "symbol": symbol,
                "direction": direction,
                "move_pct": move_size,
                "candles_to_peak": candles_to_peak,
                "rsi": rsi,
                "bb_pct_b": bb,
                "zscore": z,
                "volume_ratio": vol,
            })

    if not records:
        print("No moves found. Try --days 60.")
        return

    total = len(records)
    longs  = [r for r in records if r["direction"] == "LONG"]
    shorts = [r for r in records if r["direction"] == "SHORT"]

    def pct_above(arr, threshold):
        return sum(1 for x in arr if x >= threshold) / len(arr) * 100 if arr else 0

    def pct_below(arr, threshold):
        return sum(1 for x in arr if x <= threshold) / len(arr) * 100 if arr else 0

    def median(arr):
        return float(np.median(arr)) if arr else 0

    def p25(arr):
        return float(np.percentile(arr, 25)) if arr else 0

    def p75(arr):
        return float(np.percentile(arr, 75)) if arr else 0

    # ── Print report ──────────────────────────────────────────────────────────
    print(f"{'='*70}")
    print(f"  TOTAL MOVES FOUND: {total}  ({len(longs)} LONG / {len(shorts)} SHORT)")
    print(f"  Pairs contributing: {len(set(r['symbol'] for r in records))}")
    print(f"{'='*70}\n")

    for label, group in [("ALL MOVES", records), ("SHORT MOVES", shorts), ("LONG MOVES", longs)]:
        if not group:
            continue
        vols  = [r["volume_ratio"] for r in group]
        rsis  = [r["rsi"]          for r in group]
        bbs   = [r["bb_pct_b"]     for r in group]
        zs    = [r["zscore"]       for r in group]
        sizes = [r["move_pct"]     for r in group]

        print(f"  ── {label} (n={len(group)}) ──")
        print(f"  Avg move size: {np.mean(sizes)*100:.1f}%  "
              f"median: {median(sizes)*100:.1f}%")
        print()

        # Volume ratio
        print(f"  VOLUME RATIO at candle before move:")
        print(f"    median={median(vols):.2f}x  p25={p25(vols):.2f}x  p75={p75(vols):.2f}x")
        print(f"    > 1.5x : {pct_above(vols, 1.5):5.1f}%  ← current gate")
        print(f"    > 1.2x : {pct_above(vols, 1.2):5.1f}%")
        print(f"    > 1.0x : {pct_above(vols, 1.0):5.1f}%")
        print(f"    < 1.0x : {pct_below(vols, 1.0):5.1f}%  ← move on NO volume spike")
        print()

        # RSI
        if label in ("ALL MOVES", "SHORT MOVES"):
            print(f"  RSI at candle before move:")
            print(f"    median={median(rsis):.1f}  p25={p25(rsis):.1f}  p75={p75(rsis):.1f}")
            print(f"    > 70 (overbought): {pct_above(rsis, 70):5.1f}%")
            print(f"    > 65             : {pct_above(rsis, 65):5.1f}%")
            print(f"    50-65 (neutral)  : {sum(1 for r in rsis if 50 <= r <= 65)/len(rsis)*100:5.1f}%")
            print(f"    < 50             : {pct_below(rsis, 50):5.1f}%")
            print()

        if label in ("ALL MOVES", "LONG MOVES"):
            print(f"  RSI at candle before move:")
            print(f"    median={median(rsis):.1f}  p25={p25(rsis):.1f}  p75={p75(rsis):.1f}")
            print(f"    < 30 (oversold)  : {pct_below(rsis, 30):5.1f}%")
            print(f"    < 35             : {pct_below(rsis, 35):5.1f}%")
            print(f"    35-65 (neutral)  : {sum(1 for r in rsis if 35 <= r <= 65)/len(rsis)*100:5.1f}%")
            print(f"    > 65             : {pct_above(rsis, 65):5.1f}%")
            print()

        # BB%B
        print(f"  BB%B at candle before move:")
        print(f"    median={median(bbs):.2f}  p25={p25(bbs):.2f}  p75={p75(bbs):.2f}")
        print(f"    > 0.8 (near upper): {pct_above(bbs, 0.8):5.1f}%")
        print(f"    > 1.0 (above band): {pct_above(bbs, 1.0):5.1f}%")
        print(f"    0.2-0.8 (mid)     : {sum(1 for b in bbs if 0.2 <= b <= 0.8)/len(bbs)*100:5.1f}%")
        print(f"    < 0.2 (near lower): {pct_below(bbs, 0.2):5.1f}%")
        print()

        # Z-score
        print(f"  Z-SCORE at candle before move:")
        print(f"    median={median(zs):.2f}  p25={p25(zs):.2f}  p75={p75(zs):.2f}")
        print(f"    > 2.0 (very high) : {pct_above(zs, 2.0):5.1f}%")
        print(f"    > 1.0             : {pct_above(zs, 1.0):5.1f}%")
        print(f"    -1.0 to 1.0       : {sum(1 for z in zs if -1.0 <= z <= 1.0)/len(zs)*100:5.1f}%")
        print(f"    < -1.0            : {pct_below(zs, -1.0):5.1f}%")
        print(f"    < -2.0            : {pct_below(zs, -2.0):5.1f}%")
        print()

        # Combined signal quality
        if label == "SHORT MOVES":
            strong_signal = [r for r in group
                             if r["volume_ratio"] > 1.5
                             and r["rsi"] > 65
                             and r["bb_pct_b"] > 0.8]
            medium_signal = [r for r in group
                             if r["volume_ratio"] > 1.2
                             and r["rsi"] > 60]
            any_vol       = [r for r in group if r["volume_ratio"] > 1.5]
            print(f"  CATCHABLE (current scorer: vol>1.5 + RSI>65 + BB>0.8): "
                  f"{len(strong_signal)}/{len(group)} = {len(strong_signal)/len(group)*100:.1f}%")
            print(f"  WITH vol>1.2 + RSI>60: "
                  f"{len(medium_signal)}/{len(group)} = {len(medium_signal)/len(group)*100:.1f}%")
            print(f"  VOLUME ONLY (vol>1.5): "
                  f"{len(any_vol)}/{len(group)} = {len(any_vol)/len(group)*100:.1f}%")

        if label == "LONG MOVES":
            strong_signal = [r for r in group
                             if r["volume_ratio"] > 1.5
                             and r["rsi"] < 35
                             and r["bb_pct_b"] < 0.2]
            medium_signal = [r for r in group
                             if r["volume_ratio"] > 1.2
                             and r["rsi"] < 40]
            print(f"  CATCHABLE (current scorer: vol>1.5 + RSI<35 + BB<0.2): "
                  f"{len(strong_signal)}/{len(group)} = {len(strong_signal)/len(group)*100:.1f}%")
            print(f"  WITH vol>1.2 + RSI<40: "
                  f"{len(medium_signal)}/{len(group)} = {len(medium_signal)/len(group)*100:.1f}%")

        print()

    # ── Speed of move: how quickly do they resolve? ───────────────────────────
    print(f"{'='*70}")
    print(f"  SPEED ANALYSIS — candles to reach peak")
    print(f"{'='*70}")
    for label, group in [("ALL", records), ("SHORT", shorts), ("LONG", longs)]:
        if not group:
            continue
        ctps = [r["candles_to_peak"] for r in group]
        fast = sum(1 for c in ctps if c <= 12)   # ≤ 1 hour
        med  = sum(1 for c in ctps if 13 <= c <= 36)  # 1-3 hours
        slow = sum(1 for c in ctps if c > 36)
        print(f"  {label:<6}  ≤1h: {fast/len(ctps)*100:.0f}%  "
              f"1-3h: {med/len(ctps)*100:.0f}%  "
              f">3h: {slow/len(ctps)*100:.0f}%  "
              f"median={median(ctps):.0f} candles ({median(ctps)*5/60:.1f}h)")

    print()

    # ── Top pairs by catchability ──────────────────────────────────────────────
    print(f"{'='*70}")
    print(f"  TOP PAIRS — most catchable moves (vol>1.5 + correct direction indicators)")
    print(f"{'='*70}")
    by_pair = defaultdict(lambda: {"total": 0, "catchable": 0})
    for r in records:
        sym = r["symbol"]
        by_pair[sym]["total"] += 1
        is_short = r["direction"] == "SHORT" and r["rsi"] > 65 and r["volume_ratio"] > 1.5
        is_long  = r["direction"] == "LONG"  and r["rsi"] < 35 and r["volume_ratio"] > 1.5
        if is_short or is_long:
            by_pair[sym]["catchable"] += 1

    ranked = sorted(by_pair.items(), key=lambda x: x[1]["catchable"], reverse=True)
    print(f"  {'Symbol':<15} {'Total':>7} {'Catchable':>10} {'Rate':>8}")
    print(f"  {'-'*45}")
    for sym, d in ranked[:20]:
        rate = d["catchable"] / d["total"] * 100 if d["total"] else 0
        print(f"  {sym:<15} {d['total']:>7} {d['catchable']:>10} {rate:>7.0f}%")

    print(f"\n{'='*70}\n")

    if export:
        out = {
            "days": days,
            "move_pct": move_pct,
            "total_moves": total,
            "records": records,
        }
        path = os.path.join(os.path.dirname(__file__), "precursor_results.json")
        with open(path, "w") as f:
            json.dump(out, f, indent=2)
        print(f"Exported to {path}\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days",     type=int,   default=30)
    p.add_argument("--move-pct", type=float, default=0.10)
    p.add_argument("--export",   action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.days, args.move_pct, args.export))

if __name__ == "__main__":
    main()
