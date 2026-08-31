#!/usr/bin/env python3
"""
02_sweep.py -- Stage 3+4 of the martingale-robustness pipeline: a broad grid search over
(BB length, BB mult, TP%, SL type+value) using REAL 1m klines fetched by 01_fetch_data.py, to find
which entry/exit combinations show a robust edge -- one that survives real Binance costs AND holds
up out-of-sample, not just an in-sample fluke.

SIMPLIFICATION USED HERE (deliberate, documented -- full-fidelity re-check happens in 03_validate.py):
for speed across a ~900-combo grid, each crossover signal is evaluated INDEPENDENTLY: does price
touch TP or SL first, scanning forward up to HORIZON_BARS from the entry fill (SL wins same-bar
ties, matching this repo's established adverse-first convention). This ignores that a real
pyramiding=0 strategy can only hold ONE position at a time, so it can't take every signal that
fires while a prior trade is still open -- that's exactly what 03_validate.py re-checks with the
proper sequential state machine for the handful of winning candidates this stage produces. Signal
counting/timing WILL change between this stage and 03; win rate / profit factor per triggered
signal should not (same entry/exit logic, just evaluated with vs without the "only one open
position" constraint).

MECHANICS (same as the three martingale scripts already backtested this session):
  Entry: ta.crossover(close, lower) long / ta.crossunder(close, upper) short, on bar i's close;
         fills at open[i+1].
  Exit : first touch of TP or SL scanning bars [i+2, i+2+HORIZON_BARS) -- exit orders are only
         checkable starting the bar AFTER the entry bar, per Pine's script-execution timing.
  SL   : swept both as a FIXED %, and as a DYNAMIC k*sigma, where sigma = population stdev(close,
         bb_len) AT THE ENTRY BAR (fixed at that value once set, not re-measured afterward -- like
         a real stop order would be).
  Costs: net_pnl_frac = gross_pnl_frac - ROUND_TRIP_COST_FRAC (2x0.04% taker fee + 0.15% tramo-1
         slippage on entry = 0.23% flat), matching this project's established cost model. Fills
         used here are the exact TP/SL price levels (no gap-through-improves-fill refinement --
         that's also deferred to 03_validate.py's full state machine).

SPLIT: in-sample = first 70% of the fetched calendar window, out-of-sample = the last 30%, split
by a single GLOBAL cutoff timestamp (not per-symbol) so all symbols share the same IS/OOS boundary
-- a coherent "period" comparison, not each symbol getting its own arbitrary cutoff.

Signals that never touch TP or SL within HORIZON_BARS are excluded from win-rate/PF (their
gross outcome is genuinely unknown at this stage) but their fraction is reported per combo so an
unusually high no-touch rate isn't hidden.

Selection for Stage 5 (03_validate.py): combos are ranked on OUT-OF-SAMPLE performance (not
in-sample), requiring a minimum resolved-signal count for statistical relevance -- picking on
in-sample win rate alone is exactly the overfitting trap this repo has hit before.
"""
import json
import os
import time

import numpy as np
import pandas as pd

from lib import log, ts_str, cache_load, OUTPUT_DIR

BB_LENS = [10, 14, 20, 30]
BB_MULTS = [1.5, 2.0, 2.5, 3.0]
TP_PCTS = [0.5, 0.75, 1.0, 1.5, 2.0, 2.5]
SL_SPECS = ([("fixed", v) for v in [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]]
            + [("dyn", k) for k in [1.5, 2.0, 2.5, 3.0, 4.0]])
# widened after a first pass (HORIZON_BARS=480, SL up to 6.0% only) showed the top-ranked combos
# ALL landing on SL=6.0% -- the edge of that grid -- which meant the true optimum hadn't been
# found yet, not that 6% was actually best. Also widened HORIZON_BARS 480->720 since that first
# pass showed 38-51% of signals never touching TP or SL within 8h -- worth checking with more room
# before concluding whether that no-touch rate is inherent to the strategy or an artifact of a
# too-short horizon.
HORIZON_BARS = 720  # 12h forward-scan cap for this broad stage
ROUND_TRIP_COST_FRAC = 2 * 0.0004 + 0.0015  # 2x taker fee + tramo-1 slippage on entry = 0.23%
IS_FRACTION = 0.70
MIN_OOS_RESOLVED = 80  # minimum pooled OOS resolved-signal count to even consider a combo


def load_universe():
    with open(os.path.join(OUTPUT_DIR, "universe_meta.json")) as f:
        meta = json.load(f)
    symbol_tier = {}
    for tier, syms in meta["tiers"].items():
        for s in syms:
            symbol_tier[s] = tier
    data = {}
    for s in sorted(symbol_tier):
        kl = cache_load(f"klines_{s}_{meta['start_ms']}_{meta['end_ms']}.json")
        if not kl or len(kl) < 100:
            log(f"  WARNING: {s} has no usable cached klines, skipping")
            continue
        df = pd.DataFrame(kl)
        data[s] = {
            "open": df["open"].to_numpy(dtype=np.float64),
            "high": df["high"].to_numpy(dtype=np.float64),
            "low": df["low"].to_numpy(dtype=np.float64),
            "close": df["close"].to_numpy(dtype=np.float64),
            "open_time": df["open_time"].to_numpy(dtype=np.int64),
            "tier": symbol_tier[s],
        }
    return data, meta


def compute_signals(data, bb_len, bb_mult, cutoff_ms):
    """Returns arrays: symbol(list[str]), start_idx(int array, the first bar exits are checkable
    -- i.e. entry_bar+1), direction(int8: 1/-1), entry_price(float), entry_sigma(float),
    is_oos(bool), tier(list[str])."""
    symbols, start_idx, direction, entry_price, entry_sigma, is_oos, tier = [], [], [], [], [], [], []
    for sym, d in data.items():
        close = d["close"]
        n = len(close)
        if n < bb_len + 5:
            continue
        s = pd.Series(close)
        sma = s.rolling(bb_len).mean().to_numpy()
        std = s.rolling(bb_len).std(ddof=0).to_numpy()
        upper = sma + bb_mult * std
        lower = sma - bb_mult * std

        valid = ~(np.isnan(lower[:-1]) | np.isnan(lower[1:]))
        cross_up = np.zeros(n, dtype=bool)
        cross_down = np.zeros(n, dtype=bool)
        cross_up[1:] = valid & (close[:-1] <= lower[:-1]) & (close[1:] > lower[1:])
        cross_down[1:] = valid & (close[:-1] >= upper[:-1]) & (close[1:] < upper[1:])

        # entry fills at open[i+1]; exits checkable from i+2 onward -> need i+2 < n
        idx_up = np.where(cross_up)[0]
        idx_up = idx_up[(idx_up + 2) < n]
        idx_dn = np.where(cross_down)[0]
        idx_dn = idx_dn[(idx_dn + 2) < n]

        for i in idx_up:
            symbols.append(sym); start_idx.append(i + 2); direction.append(1)
            entry_price.append(d["open"][i + 1]); entry_sigma.append(std[i])
            is_oos.append(d["open_time"][i] >= cutoff_ms); tier.append(d["tier"])
        for i in idx_dn:
            symbols.append(sym); start_idx.append(i + 2); direction.append(-1)
            entry_price.append(d["open"][i + 1]); entry_sigma.append(std[i])
            is_oos.append(d["open_time"][i] >= cutoff_ms); tier.append(d["tier"])

    return {
        "symbol": symbols, "start_idx": np.array(start_idx, dtype=np.int64),
        "direction": np.array(direction, dtype=np.int8),
        "entry_price": np.array(entry_price, dtype=np.float64),
        "entry_sigma": np.array(entry_sigma, dtype=np.float64),
        "is_oos": np.array(is_oos, dtype=bool), "tier": tier,
    }


def evaluate_combo(sig, data, tp_pct, sl_spec):
    """Vectorized-per-signal first-touch scan. Returns per-signal arrays: resolved(bool),
    net_pnl_frac(float), is_win(bool)."""
    n = len(sig["symbol"])
    resolved = np.zeros(n, dtype=bool)
    net_pnl = np.zeros(n, dtype=np.float64)
    sl_type, sl_val = sl_spec

    for j in range(n):
        sym = sig["symbol"][j]
        d = data[sym]
        st = sig["start_idx"][j]
        dirn = sig["direction"][j]
        ep = sig["entry_price"][j]
        sigma = sig["entry_sigma"][j]
        if sl_type == "fixed":
            risk_frac = sl_val / 100.0
        else:
            risk_frac = (sl_val * sigma) / ep if ep > 0 else np.nan
        if not np.isfinite(risk_frac) or risk_frac <= 0:
            continue
        tp_price = ep * (1 + tp_pct / 100.0 * dirn)
        sl_price = ep * (1 - risk_frac * dirn)

        end = min(st + HORIZON_BARS, len(d["high"]))
        if st >= end:
            continue
        highs_fwd = d["high"][st:end]
        lows_fwd = d["low"][st:end]

        if dirn == 1:
            hit_sl = lows_fwd <= sl_price
            hit_tp = highs_fwd >= tp_price
        else:
            hit_sl = highs_fwd >= sl_price
            hit_tp = lows_fwd <= tp_price
        combined = hit_sl | hit_tp
        if not combined.any():
            continue
        first = int(np.argmax(combined))
        resolved[j] = True
        if hit_sl[first]:
            gross = -risk_frac
        else:
            gross = tp_pct / 100.0
        net_pnl[j] = gross - ROUND_TRIP_COST_FRAC

    return resolved, net_pnl


def summarize(resolved, net_pnl, is_oos, tier_arr, tier_filter=None):
    mask = resolved.copy()
    if tier_filter is not None:
        mask &= (tier_arr == tier_filter)
    out = {}
    for label, sel in (("is", mask & ~is_oos), ("oos", mask & is_oos)):
        pnl = net_pnl[sel]
        n = len(pnl)
        if n == 0:
            out[label] = {"n": 0, "win_rate": None, "pf": None, "avg_net": None}
            continue
        wins = pnl[pnl > 0]
        losses = -pnl[pnl <= 0]
        pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else (float("inf") if wins.sum() > 0 else None)
        out[label] = {
            "n": int(n), "win_rate": float(100 * len(wins) / n), "pf": pf,
            "avg_net": float(pnl.mean()),
        }
    return out


JSONL_PATH = os.path.join(OUTPUT_DIR, "sweep_results.jsonl")
DONE_MARKERS_PATH = os.path.join(OUTPUT_DIR, "sweep_done_bandcombos.json")
WALL_BUDGET_SEC = 480  # leave headroom under a 10-minute tool-call cap; re-run this script to resume


def load_done_bandcombos():
    if not os.path.exists(DONE_MARKERS_PATH):
        return set()
    with open(DONE_MARKERS_PATH) as f:
        return set(tuple(x) for x in json.load(f))


def save_done_bandcombos(done):
    with open(DONE_MARKERS_PATH, "w") as f:
        json.dump(sorted(list(x) for x in done), f)


def main():
    t0 = time.time()
    data, meta = load_universe()
    cutoff_ms = meta["start_ms"] + int(IS_FRACTION * (meta["end_ms"] - meta["start_ms"]))
    log(f"loaded {len(data)} symbols. IS/OOS cutoff: {ts_str(cutoff_ms)} UTC "
        f"(IS={ts_str(meta['start_ms'])}->{ts_str(cutoff_ms)}, OOS={ts_str(cutoff_ms)}->{ts_str(meta['end_ms'])})")

    done = load_done_bandcombos()
    all_band_combos = [(bl, bm) for bl in BB_LENS for bm in BB_MULTS]
    remaining = [c for c in all_band_combos if list(c) not in [list(x) for x in done] and tuple(c) not in done]
    log(f"band combos done so far: {len(done)}/{len(all_band_combos)}. Resuming with {len(remaining)} remaining.")

    if not remaining:
        log("All band combos already processed. Skipping straight to ranking.")
    else:
        f_out = open(JSONL_PATH, "a")
        for bb_len, bb_mult in remaining:
            if time.time() - t0 > WALL_BUDGET_SEC:
                log(f"Wall-time budget ({WALL_BUDGET_SEC}s) reached, stopping here. "
                    f"{len(done)}/{len(all_band_combos)} band combos done -- re-run this script to continue.")
                break
            t_sig = time.time()
            sig = compute_signals(data, bb_len, bb_mult, cutoff_ms)
            tier_arr = np.array(sig["tier"])
            n_sig = len(sig["symbol"])
            log(f"bb_len={bb_len} bb_mult={bb_mult}: {n_sig} raw signals "
                f"({time.time()-t_sig:.1f}s to compute) -- sweeping {len(TP_PCTS)*len(SL_SPECS)} exit combos")
            for tp_pct in TP_PCTS:
                for sl_spec in SL_SPECS:
                    resolved, net_pnl = evaluate_combo(sig, data, tp_pct, sl_spec)
                    overall = summarize(resolved, net_pnl, sig["is_oos"], tier_arr)
                    by_tier = {t: summarize(resolved, net_pnl, sig["is_oos"], tier_arr, t) for t in ("high", "mid", "low")}
                    no_touch_frac = 1.0 - (resolved.sum() / n_sig if n_sig else 0.0)
                    row = {
                        "bb_len": bb_len, "bb_mult": bb_mult, "tp_pct": tp_pct,
                        "sl_type": sl_spec[0], "sl_val": sl_spec[1],
                        "n_signals": n_sig, "no_touch_frac": round(no_touch_frac, 4),
                        "is": overall["is"], "oos": overall["oos"], "by_tier": by_tier,
                    }
                    f_out.write(json.dumps(row) + "\n")
            f_out.flush()
            done.add((bb_len, bb_mult))
            save_done_bandcombos(done)
            log(f"  ... bb_len={bb_len} bb_mult={bb_mult} done, elapsed {time.time()-t0:.0f}s this invocation, "
                f"{len(done)}/{len(all_band_combos)} band combos total")
        f_out.close()

    if len(done) < len(all_band_combos):
        log(f"NOT YET COMPLETE: {len(done)}/{len(all_band_combos)} band combos done. Run this script again to continue.")
        return

    results = []
    with open(JSONL_PATH) as f:
        for line in f:
            results.append(json.loads(line))
    with open(os.path.join(OUTPUT_DIR, "sweep_results.json"), "w") as f:
        json.dump(results, f)
    log(f"ALL {len(all_band_combos)} band combos complete -- {len(results)} total exit-combo rows "
        f"written to output/sweep_results.json")

    # ranking: require min pooled OOS resolved count, then sort by min(PF_is, PF_oos), tie-break win_rate_oos
    def score(r):
        oos, is_ = r["oos"], r["is"]
        if oos["n"] is None or oos["n"] < MIN_OOS_RESOLVED or is_["n"] is None or is_["n"] < MIN_OOS_RESOLVED:
            return None
        if oos["pf"] is None or is_["pf"] is None:
            return None
        pf_oos = min(oos["pf"], 10.0) if np.isfinite(oos["pf"]) else 10.0
        pf_is = min(is_["pf"], 10.0) if np.isfinite(is_["pf"]) else 10.0
        return min(pf_is, pf_oos), oos["win_rate"]

    scored = [(score(r), r) for r in results]
    scored = [(sc, r) for sc, r in scored if sc is not None]
    scored.sort(key=lambda x: x[0], reverse=True)

    top = scored[:15]
    with open(os.path.join(OUTPUT_DIR, "sweep_top15.json"), "w") as f:
        json.dump([r for _, r in top], f, indent=2)

    log("=" * 100)
    log(f"TOP {len(top)} CANDIDATES (ranked by min(PF_is,PF_oos), min {MIN_OOS_RESOLVED} resolved signals each side):")
    log(f"{'bb_len':>6} {'mult':>5} {'tp%':>5} {'sl':>10} | {'IS n':>6} {'IS win%':>8} {'IS PF':>7} | "
        f"{'OOS n':>6} {'OOS win%':>8} {'OOS PF':>7} | no_touch%")
    for sc, r in top:
        sl_str = f"{r['sl_val']:.1f}%" if r["sl_type"] == "fixed" else f"{r['sl_val']:.1f}sig"
        isr, oosr = r["is"], r["oos"]
        pf_is_str = f"{isr['pf']:.2f}" if isr["pf"] not in (None, float("inf")) else str(isr["pf"])
        pf_oos_str = f"{oosr['pf']:.2f}" if oosr["pf"] not in (None, float("inf")) else str(oosr["pf"])
        log(f"{r['bb_len']:>6} {r['bb_mult']:>5.1f} {r['tp_pct']:>5.2f} {sl_str:>10} | "
            f"{isr['n']:>6} {isr['win_rate']:>7.1f}% {pf_is_str:>7} | "
            f"{oosr['n']:>6} {oosr['win_rate']:>7.1f}% {pf_oos_str:>7} | {r['no_touch_frac']*100:.1f}%")

    log(f"Total wall time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
