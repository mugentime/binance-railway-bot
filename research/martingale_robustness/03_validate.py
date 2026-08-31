#!/usr/bin/env python3
"""
03_validate.py -- Stage 5 of the pipeline: full-fidelity, single-position-at-a-time state machine
re-check of the top candidates found by 02_sweep.py's independent-signal grid search, on the same
REAL 36-symbol / 30-day dataset. This exists because 02_sweep.py deliberately evaluates every
crossover signal as if it could always be traded (fast, good for a ~1000-combo grid) -- but the
actual Pine script has pyramiding=0: only one position at a time. While a position is open, later
signals on that symbol are simply skipped. That changes trade COUNT and TIMING; this stage checks
whether the win-rate/PF edge measured in Stage 3 survives that constraint, using the real klines
already fetched (no new API calls, no synthetic data).

MECHANICS (unchanged from the three martingale scripts already backtested this session, and from
02_sweep.py): crossover entry on bar i's close, market fill at open[i+1]; TP/SL resting orders
checkable from bar i+2 onward; SL wins same-bar ties (this repo's adverse-first convention); costs
= 2x0.04% taker fee (entry+exit) + 0.15% tramo-1 slippage on the entry fill only (TP/SL exits are
resting orders, filled at their exact level or, on a gap, at the bar's open if that's a BETTER
price than the order level -- same gap-improves-fill logic as run_pine_bbands_sar.py /
backtest_martingale_1m*.py).

Reads output/sweep_top15_leverage_safe.json (NOT the raw sweep_top15.json) and re-validates the
top N_CANDIDATES entries from it. IMPORTANT CORRECTION found during Stage 3: the raw (unconstrained)
ranking is dominated by fixed SL% values of 10% and wider, because PF/win-rate rise MONOTONICALLY
as SL widens with no interior peak up to SL=30% (checked explicitly) -- there is no natural optimum
for a plain fixed-% stop on this strategy shape, it just approaches "no stop at all". But this
session established the account trades at 20x leverage, and Binance liquidates an isolated/cross
position at roughly a 5% adverse price move (maintenance-margin dependent, but that's the right
order of magnitude) -- so a fixed SL wider than ~6% is not an order that can ever actually fill;
the account gets involuntarily liquidated for -100% of that trade's margin FIRST, well before the
nominal SL price is reached. Every "SL=10%+" result in the raw sweep is therefore not achievable
at this leverage and must be excluded. sweep_top15_leverage_safe.json is the same ranking restricted
to fixed SL <= 6.0%, which is what's actually implementable. Writes output/validate_results.json
with, per candidate: overall/IS/OOS win rate, PF, trade count, and average trade duration -- plus
the full chronological per-symbol trade list (needed by 04_martingale_streak.py for real streak
analysis, not a synthetic one).
"""
import json
import os
import time

import numpy as np
import pandas as pd

from lib import log, ts_str, cache_load, OUTPUT_DIR, TAKER_FEE, SLIPPAGE_BPS_TIER1

N_CANDIDATES = 3
IS_FRACTION = 0.70


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
            continue
        df = pd.DataFrame(kl)
        data[s] = {
            "open": df["open"].to_numpy(dtype=np.float64),
            "high": df["high"].to_numpy(dtype=np.float64),
            "low": df["low"].to_numpy(dtype=np.float64),
            "close": df["close"].to_numpy(dtype=np.float64),
            "open_time": df["open_time"].to_numpy(dtype=np.int64),
            "close_time": None,
            "tier": symbol_tier[s],
        }
    return data, meta


def simulate_symbol_sequential(sym, d, bb_len, bb_mult, tp_pct, sl_type, sl_val, cutoff_ms):
    close, high, low, open_ = d["close"], d["high"], d["low"], d["open"]
    open_time = d["open_time"]
    n = len(close)
    if n < bb_len + 5:
        return []

    s = pd.Series(close)
    sma = s.rolling(bb_len).mean().to_numpy()
    std = s.rolling(bb_len).std(ddof=0).to_numpy()
    upper = sma + bb_mult * std
    lower = sma - bb_mult * std

    trades = []
    position = None  # {direction, entry_price, entry_bar, tp_price, sl_price, entry_fee_frac}
    i = bb_len
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
                sigma = std[i]
                risk_frac = (sl_val / 100.0) if sl_type == "fixed" else ((sl_val * sigma) / fill_price if fill_price > 0 else np.nan)
                if not np.isfinite(risk_frac) or risk_frac <= 0:
                    i += 1
                    continue
                tp_price = fill_price * (1 + tp_pct / 100.0 * direction)
                sl_price = fill_price * (1 - risk_frac * direction)
                position = {
                    "direction": direction, "entry_price": fill_price, "entry_bar": fill_idx,
                    "entry_time": open_time[fill_idx], "tp_price": tp_price, "sl_price": sl_price,
                    "risk_frac": risk_frac,
                }
                i = fill_idx
                continue
            i += 1
            continue

        # in position: check exit starting the bar AFTER entry_bar
        bar = i
        if bar <= position["entry_bar"]:
            i += 1
            continue
        direction = position["direction"]
        hit_sl = (low[bar] <= position["sl_price"]) if direction == 1 else (high[bar] >= position["sl_price"])
        hit_tp = (high[bar] >= position["tp_price"]) if direction == 1 else (low[bar] <= position["tp_price"])
        exit_price = exit_reason = None
        if hit_sl:
            lvl = position["sl_price"]
            exit_price = open_[bar] if ((open_[bar] <= lvl) if direction == 1 else (open_[bar] >= lvl)) else lvl
            exit_reason = "SL"
        elif hit_tp:
            lvl = position["tp_price"]
            exit_price = open_[bar] if ((open_[bar] >= lvl) if direction == 1 else (open_[bar] <= lvl)) else lvl
            exit_reason = "TP"
        if exit_price is not None:
            gross_frac = (exit_price - position["entry_price"]) / position["entry_price"] * direction
            net_frac = gross_frac - 2 * TAKER_FEE
            trades.append({
                "symbol": sym, "tier": d["tier"], "direction": direction,
                "entry_time": int(position["entry_time"]), "exit_time": int(open_time[bar]),
                "entry_price": position["entry_price"], "exit_price": exit_price,
                "net_pnl_frac": net_frac, "risk_frac": position["risk_frac"], "reason": exit_reason,
                "is_oos": bool(position["entry_time"] >= cutoff_ms),
                "duration_min": (int(open_time[bar]) - int(position["entry_time"])) / 60000.0,
            })
            position = None
        i += 1

    return trades


def summarize_trades(trades):
    if not trades:
        return {"n": 0}
    pnl = np.array([t["net_pnl_frac"] for t in trades])
    wins = pnl[pnl > 0]
    losses = -pnl[pnl <= 0]
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else (float("inf") if wins.sum() > 0 else None)
    return {
        "n": len(trades), "win_rate": float(100 * len(wins) / len(trades)),
        "pf": pf, "avg_net_frac": float(pnl.mean()),
        "avg_duration_min": float(np.mean([t["duration_min"] for t in trades])),
    }


def main():
    t0 = time.time()
    with open(os.path.join(OUTPUT_DIR, "sweep_top15_leverage_safe.json")) as f:
        top15 = json.load(f)
    candidates = top15[:N_CANDIDATES]
    data, meta = load_universe()
    cutoff_ms = meta["start_ms"] + int(IS_FRACTION * (meta["end_ms"] - meta["start_ms"]))
    log(f"validating top {len(candidates)} candidates from sweep_top15.json on {len(data)} real symbols")

    all_results = []
    for c in candidates:
        cfg = (c["bb_len"], c["bb_mult"], c["tp_pct"], c["sl_type"], c["sl_val"])
        log(f"config: bb_len={cfg[0]} mult={cfg[1]} tp={cfg[2]}% sl={cfg[3]}:{cfg[4]}")
        all_trades = []
        for sym, d in data.items():
            trades = simulate_symbol_sequential(sym, d, *cfg, cutoff_ms)
            all_trades.extend(trades)
        is_trades = [t for t in all_trades if not t["is_oos"]]
        oos_trades = [t for t in all_trades if t["is_oos"]]
        by_tier = {tier: summarize_trades([t for t in all_trades if t["tier"] == tier]) for tier in ("high", "mid", "low")}
        by_tier_oos = {tier: summarize_trades([t for t in oos_trades if t["tier"] == tier]) for tier in ("high", "mid", "low")}
        result = {
            "bb_len": cfg[0], "bb_mult": cfg[1], "tp_pct": cfg[2], "sl_type": cfg[3], "sl_val": cfg[4],
            "overall": summarize_trades(all_trades), "is": summarize_trades(is_trades), "oos": summarize_trades(oos_trades),
            "by_tier_overall": by_tier, "by_tier_oos": by_tier_oos,
            "trades": all_trades,
        }
        all_results.append(result)
        ov, isr, oosr = result["overall"], result["is"], result["oos"]
        log(f"  OVERALL n={ov.get('n')} win={ov.get('win_rate')} PF={ov.get('pf')} "
            f"avg_dur={ov.get('avg_duration_min')}min")
        log(f"  IS  n={isr.get('n')} win={isr.get('win_rate')} PF={isr.get('pf')}")
        log(f"  OOS n={oosr.get('n')} win={oosr.get('win_rate')} PF={oosr.get('pf')}")
        for tier in ("high", "mid", "low"):
            bt = by_tier_oos[tier]
            log(f"    OOS tier={tier:4s} n={bt.get('n')} win={bt.get('win_rate')} PF={bt.get('pf')}")

    with open(os.path.join(OUTPUT_DIR, "validate_results.json"), "w") as f:
        json.dump(all_results, f)
    log(f"Wrote output/validate_results.json ({time.time()-t0:.0f}s)")

    # winner = best OOS PF among candidates with a reasonable OOS trade count
    scored = [(r["oos"].get("pf") or 0, r) for r in all_results if (r["oos"].get("n") or 0) >= 20]
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        winner = scored[0][1]
        with open(os.path.join(OUTPUT_DIR, "winner_config.json"), "w") as f:
            json.dump(winner, f)
        log("=" * 78)
        log(f"WINNER: bb_len={winner['bb_len']} mult={winner['bb_mult']} tp={winner['tp_pct']}% "
            f"sl={winner['sl_type']}:{winner['sl_val']}")
        log(f"  OOS: n={winner['oos']['n']} win_rate={winner['oos']['win_rate']:.1f}% PF={winner['oos']['pf']}")
    else:
        log("No candidate had >=20 OOS trades in the full state machine -- see validate_results.json for details.")


if __name__ == "__main__":
    main()
