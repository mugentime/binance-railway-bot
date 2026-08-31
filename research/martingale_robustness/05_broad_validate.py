#!/usr/bin/env python3
"""
05_broad_validate.py -- extends Stage 5 after 03_validate.py's top-3 check revealed a serious
discrepancy: the top independent-signal candidates from 02_sweep.py (bb_len=20/14/10, tp=1.5%,
sl=6.0%) all showed OOS PF < 1.0 (0.92-0.96, i.e. LOSING net of costs) once run through the real
one-position-at-a-time state machine, despite showing PF 1.4-1.5 and 87%+ win rate in the
independent-signal sweep. Trade count also collapsed ~16-20x (e.g. 32,246 OOS "signals" -> 1,807
actual OOS trades) because most band touches happen while a prior position is still open and
can't be taken. Ranking candidates by independent-signal PF clearly does NOT predict full-state-
-machine profitability for this strategy -- so this script re-scans the WHOLE leverage-safe grid
(fixed SL <= 6.0%, all bb_len/bb_mult/tp_pct combos already computed in 02_sweep.py) through the
real sequential state machine, to find out honestly whether ANY combination in this real 36-symbol
/ 30-day dataset actually clears OOS PF > 1 once run for real -- rather than assuming the answer
from the (misleading) independent-signal numbers.

OPTIMIZATION vs 03_validate.py: rolling sma/std is computed ONCE per (symbol, bb_len, bb_mult) and
reused across every tp_pct/sl_val variant sharing those bands, instead of recomputing per config
(the bands don't depend on TP/SL) -- cuts redundant pandas rolling calls by ~severalfold since many
TP/SL variants share the same band combo.
"""
import json
import os
import time

import numpy as np
import pandas as pd

from lib import log, OUTPUT_DIR, TAKER_FEE, SLIPPAGE_BPS_TIER1
from importlib.util import spec_from_file_location, module_from_spec

spec = spec_from_file_location("validate", "03_validate.py")
validate = module_from_spec(spec)
spec.loader.exec_module(validate)

IS_FRACTION = 0.70
MIN_OOS_TRADES = 30  # full-state-machine trade counts are much lower than the independent-signal sweep


def main():
    t0 = time.time()
    with open(os.path.join(OUTPUT_DIR, "universe_meta.json")) as f:
        meta = json.load(f)
    with open(os.path.join(OUTPUT_DIR, "sweep_results.json")) as f:
        sweep_results = json.load(f)

    leverage_safe = [r for r in sweep_results if r["sl_type"] == "fixed" and r["sl_val"] <= 6.0]
    band_combos = sorted(set((r["bb_len"], r["bb_mult"]) for r in leverage_safe))
    log(f"{len(leverage_safe)} leverage-safe (SL<=6%) exit combos across {len(band_combos)} band combos")

    data, _ = validate.load_universe()
    cutoff_ms = meta["start_ms"] + int(IS_FRACTION * (meta["end_ms"] - meta["start_ms"]))

    all_results = []
    for bb_len, bb_mult in band_combos:
        # precompute bands once per symbol for this (bb_len, bb_mult)
        bands = {}
        for sym, d in data.items():
            s = pd.Series(d["close"])
            sma = s.rolling(bb_len).mean().to_numpy()
            std = s.rolling(bb_len).std(ddof=0).to_numpy()
            bands[sym] = (sma + bb_mult * std, sma - bb_mult * std)  # (upper, lower)

        variants = [r for r in leverage_safe if r["bb_len"] == bb_len and r["bb_mult"] == bb_mult]
        for r in variants:
            tp_pct, sl_val = r["tp_pct"], r["sl_val"]
            all_trades = []
            for sym, d in data.items():
                upper, lower = bands[sym]
                trades = simulate_with_bands(sym, d, upper, lower, tp_pct, sl_val, cutoff_ms)
                all_trades.extend(trades)
            oos_trades = [t for t in all_trades if t["is_oos"]]
            is_trades = [t for t in all_trades if not t["is_oos"]]
            overall = {
                "bb_len": bb_len, "bb_mult": bb_mult, "tp_pct": tp_pct, "sl_val": sl_val,
                "is": validate.summarize_trades(is_trades), "oos": validate.summarize_trades(oos_trades),
            }
            all_results.append(overall)
        log(f"  band combo ({bb_len},{bb_mult}): {len(variants)} exit variants done, "
            f"elapsed {time.time()-t0:.0f}s total")

    with open(os.path.join(OUTPUT_DIR, "broad_validate_results.json"), "w") as f:
        json.dump(all_results, f)
    log(f"Wrote output/broad_validate_results.json ({len(all_results)} configs, {time.time()-t0:.0f}s)")

    survivors = [r for r in all_results
                 if (r["oos"].get("n") or 0) >= MIN_OOS_TRADES and (r["oos"].get("pf") or 0) > 1.0
                 and (r["is"].get("n") or 0) >= MIN_OOS_TRADES and (r["is"].get("pf") or 0) > 1.0]
    survivors.sort(key=lambda r: min(r["is"]["pf"], r["oos"]["pf"]), reverse=True)

    log("=" * 100)
    log(f"FULL-STATE-MACHINE SURVIVORS (both IS and OOS PF > 1.0, >= {MIN_OOS_TRADES} trades each side): "
        f"{len(survivors)} / {len(all_results)}")
    log(f"{'bb_len':>6} {'mult':>5} {'tp%':>5} {'sl%':>5} | {'IS n':>5} {'IS win%':>8} {'IS PF':>6} | "
        f"{'OOS n':>5} {'OOS win%':>8} {'OOS PF':>6}")
    for r in survivors[:20]:
        isr, oosr = r["is"], r["oos"]
        log(f"{r['bb_len']:>6} {r['bb_mult']:>5.1f} {r['tp_pct']:>5.2f} {r['sl_val']:>5.1f} | "
            f"{isr['n']:>5} {isr['win_rate']:>7.1f}% {isr['pf']:>6.2f} | "
            f"{oosr['n']:>5} {oosr['win_rate']:>7.1f}% {oosr['pf']:>6.2f}")

    if not survivors:
        log("NO combination in the leverage-safe grid clears PF>1.0 on BOTH sides under the real "
            "sequential state machine. Showing the 15 closest-to-breakeven for reference:")
        near = sorted(all_results, key=lambda r: (r["oos"].get("pf") or 0) if (r["oos"].get("n") or 0) >= MIN_OOS_TRADES else -1, reverse=True)
        for r in near[:15]:
            isr, oosr = r["is"], r["oos"]
            if not oosr.get("n"):
                continue
            log(f"{r['bb_len']:>6} {r['bb_mult']:>5.1f} {r['tp_pct']:>5.2f} {r['sl_val']:>5.1f} | "
                f"IS n={isr.get('n')} win={isr.get('win_rate')} PF={isr.get('pf')} | "
                f"OOS n={oosr.get('n')} win={oosr.get('win_rate')} PF={oosr.get('pf')}")

    with open(os.path.join(OUTPUT_DIR, "broad_validate_survivors.json"), "w") as f:
        json.dump(survivors, f, indent=2)


def simulate_with_bands(sym, d, upper, lower, tp_pct, sl_val, cutoff_ms):
    close, high, low, open_ = d["close"], d["high"], d["low"], d["open"]
    open_time = d["open_time"]
    n = len(close)
    trades = []
    position = None
    i = 0
    # find first valid index
    valid_start = np.argmax(~np.isnan(lower)) if np.any(~np.isnan(lower)) else n
    i = max(valid_start, 1)
    while i < n - 1:
        if position is None:
            if not (np.isnan(lower[i - 1]) or np.isnan(lower[i]) or np.isnan(upper[i - 1]) or np.isnan(upper[i])):
                cross_up = close[i - 1] <= lower[i - 1] and close[i] > lower[i]
                cross_down = close[i - 1] >= upper[i - 1] and close[i] < upper[i]
            else:
                cross_up = cross_down = False
            if cross_up or cross_down:
                direction = 1 if cross_up else -1
                fill_idx = i + 1
                raw_price = open_[fill_idx]
                fill_price = raw_price * (1 + SLIPPAGE_BPS_TIER1 * direction)
                risk_frac = sl_val / 100.0
                tp_price = fill_price * (1 + tp_pct / 100.0 * direction)
                sl_price = fill_price * (1 - risk_frac * direction)
                position = {
                    "direction": direction, "entry_price": fill_price, "entry_bar": fill_idx,
                    "entry_time": open_time[fill_idx], "tp_price": tp_price, "sl_price": sl_price,
                }
                i = fill_idx
                continue
            i += 1
            continue

        bar = i
        if bar <= position["entry_bar"]:
            i += 1
            continue
        direction = position["direction"]
        hit_sl = (low[bar] <= position["sl_price"]) if direction == 1 else (high[bar] >= position["sl_price"])
        hit_tp = (high[bar] >= position["tp_price"]) if direction == 1 else (low[bar] <= position["tp_price"])
        exit_price = None
        if hit_sl:
            lvl = position["sl_price"]
            exit_price = open_[bar] if ((open_[bar] <= lvl) if direction == 1 else (open_[bar] >= lvl)) else lvl
        elif hit_tp:
            lvl = position["tp_price"]
            exit_price = open_[bar] if ((open_[bar] >= lvl) if direction == 1 else (open_[bar] <= lvl)) else lvl
        if exit_price is not None:
            gross_frac = (exit_price - position["entry_price"]) / position["entry_price"] * direction
            net_frac = gross_frac - 2 * TAKER_FEE
            trades.append({
                "net_pnl_frac": net_frac,
                "is_oos": bool(position["entry_time"] >= cutoff_ms),
                "duration_min": (int(open_time[bar]) - int(position["entry_time"])) / 60000.0,
            })
            position = None
        i += 1
    return trades


if __name__ == "__main__":
    main()
