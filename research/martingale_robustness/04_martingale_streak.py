#!/usr/bin/env python3
"""
04_martingale_streak.py -- Stage 6 of the pipeline: martingale-by-streak robustness check and
max_steps recommendation, built directly from the REAL chronological trade sequences produced by
03_validate.py's full state machine on the winning (bb_len, bb_mult, tp_pct, sl) config -- not a
synthetic/theoretical trade sequence.

MARTINGALE-BY-STREAK RULE (from the pasted "Bollinger Bands Martingale by Streak" Pine script,
same rule already implemented in bollinger_pyramid_5m/backtest_martingale_streak_1m.py):
  streak_profit += trade_net_pnl_frac  (accumulated after every closed trade)
  if streak_profit > 0: streak_profit = 0; mg_step = 0     (streak fully recovered -> reset)
  else: mg_step = min(mg_step + 1, MAX_STEPS)               (still underwater -> escalate)
A single winning trade does NOT reset mg_step unless it brings the cumulative streak back to
net-positive -- so "streak length" here means "how many consecutive closed trades before the
streak's running total turns net-positive again", not simply "consecutive losing trades". This
is measured PER SYMBOL on that symbol's own real, chronological OOS trade sequence (each symbol's
martingale state is independent, matching how a single Pine chart/strategy instance would run).

SIZING (carried over from this session's earlier $100/20x/1%-of-equity requests): margin_usd =
current_equity * BASE_MARGIN_PCT * MG_MULT^mg_step, notional = margin_usd * LEVERAGE, entries
rejected if margin_usd > current_equity (can't post margin you don't have), loss floored at
-100% of that trade's margin (approximate liquidation cap). MG_MULT=1.5 is kept as previously
established in this conversation, not re-swept here -- the brief was to find a step CAP for this
mechanism, not to re-optimize the multiplier itself.

WHAT THIS SCRIPT ACTUALLY MEASURES (the honest core of the "cappear los escalones" question):
  1. The REAL distribution of streak lengths (in consecutive trades, and mapped to mg_step
     reached) observed across all symbols' real OOS trade sequences -- pooled.
  2. The naive theoretical comparison: under an (unrealistic) i.i.d.-Bernoulli assumption at the
     REAL measured OOS win rate p, P(a naive same-direction losing run reaches length >= k) =
     (1-p)^k. This is NOT the same statistic as the real streak-profit-recovery rule above (the
     real rule can extend a streak past a single win), so it is reported as a labeled reference
     line, not treated as equivalent -- if reality is materially worse than this naive curve, that
     itself is the finding (regime clustering / correlated losses beating what independent-trials
     math would predict).
  3. Margin-affordability: for each mg_step, whether a $100/20x/1%-equity account can even AFFORD
     that step (margin_usd <= INITIAL_CAPITAL, ignoring compounding for this static check since
     it's evaluating the worst case of hitting deep steps early before any equity has been built
     up) -- the account cannot survive past whatever step first requires more margin than $100.
  4. A recommended MAX_STEPS_CAP = the smallest step count that both (a) covers >=95% of the real
     observed streak lengths in the data, and (b) is at or below the max step $100/20x can afford.
"""
import json
import os

import numpy as np

from lib import log, OUTPUT_DIR
from importlib.util import spec_from_file_location, module_from_spec

_spec = spec_from_file_location("validate", "03_validate.py")
validate = module_from_spec(_spec)
_spec.loader.exec_module(validate)

BASE_MARGIN_PCT = 0.01
LEVERAGE = 20.0
MG_MULT = 1.5
INITIAL_CAPITAL = 100.0
MAX_STEP_SEARCH = 30
COVERAGE_TARGET = 0.95


def max_affordable_step():
    for step in range(MAX_STEP_SEARCH + 1):
        margin = INITIAL_CAPITAL * BASE_MARGIN_PCT * (MG_MULT ** step)
        if margin > INITIAL_CAPITAL:
            return step - 1
    return MAX_STEP_SEARCH


def compute_streaks_for_symbol(trades_sorted):
    """trades_sorted: chronological list of {net_pnl_frac} for ONE symbol. Returns list of
    completed streak lengths (number of trades from just after a reset to the next reset,
    inclusive of the trade that triggers the reset) and the list of mg_step values reached."""
    streak_profit = 0.0
    mg_step = 0
    current_len = 0
    streak_lengths = []
    mg_steps_seen = []
    for t in trades_sorted:
        current_len += 1
        streak_profit += t["net_pnl_frac"]
        mg_steps_seen.append(mg_step)
        if streak_profit > 0:
            streak_lengths.append(current_len)
            streak_profit = 0.0
            mg_step = 0
            current_len = 0
        else:
            mg_step = min(mg_step + 1, MAX_STEP_SEARCH)
    # note: an in-progress (not yet recovered) streak at the end of data is NOT counted --
    # it's censored/incomplete, would bias the distribution toward the current unresolved streak.
    return streak_lengths, mg_steps_seen


def main():
    # Sourced from 05_broad_validate.py's real-state-machine survivor scan (NOT the independent-
    # signal sweep_top15 / winner_config.json, which 03_validate.py showed does not predict real
    # profitability -- see that script's docstring for why). Picks the best survivor by
    # min(IS PF, OOS PF); if the survivors file is empty (nothing cleared PF>1 on both sides), that
    # is itself the finding and gets reported rather than silently falling back to a losing config.
    survivors_path = os.path.join(OUTPUT_DIR, "broad_validate_survivors.json")
    with open(survivors_path) as f:
        survivors = json.load(f)
    if not survivors:
        log("No config in broad_validate_survivors.json cleared PF>1.0 on both IS and OOS under "
            "the real state machine. There is no legitimate 'winner' to run a martingale-safety "
            "check on -- layering martingale on top of a strategy with no positive edge would only "
            "make a losing strategy lose faster and bigger. Stopping here; see "
            "broad_validate_results.json for the full (losing) grid.")
        return
    winner_cfg = survivors[0]
    log(f"winning config (from real state-machine scan): bb_len={winner_cfg['bb_len']} "
        f"mult={winner_cfg['bb_mult']} tp={winner_cfg['tp_pct']}% sl=fixed:{winner_cfg['sl_val']}")
    log(f"  IS:  n={winner_cfg['is']['n']} win={winner_cfg['is']['win_rate']:.1f}% PF={winner_cfg['is']['pf']:.2f}")
    log(f"  OOS: n={winner_cfg['oos']['n']} win={winner_cfg['oos']['win_rate']:.1f}% PF={winner_cfg['oos']['pf']:.2f}")

    # regenerate the FULL trade list (with symbol + entry_time, needed for per-symbol streak
    # analysis) for this exact config -- 05_broad_validate.py only kept lightweight summaries
    data, meta = validate.load_universe()
    cutoff_ms = meta["start_ms"] + int(0.70 * (meta["end_ms"] - meta["start_ms"]))
    all_trades = []
    for sym, d in data.items():
        all_trades.extend(validate.simulate_symbol_sequential(
            sym, d, winner_cfg["bb_len"], winner_cfg["bb_mult"], winner_cfg["tp_pct"],
            "fixed", winner_cfg["sl_val"], cutoff_ms))
    oos_trades = [t for t in all_trades if t["is_oos"]]
    log(f"OOS trades available for streak analysis: {len(oos_trades)}")

    by_symbol = {}
    for t in oos_trades:
        by_symbol.setdefault(t["symbol"], []).append(t)
    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda t: t["entry_time"])

    all_streak_lengths = []
    all_mg_steps = []
    for sym, ts in by_symbol.items():
        lengths, mg_steps = compute_streaks_for_symbol(ts)
        all_streak_lengths.extend(lengths)
        all_mg_steps.extend(mg_steps)

    if not all_streak_lengths:
        log("Not enough OOS trades per symbol to observe any completed streaks. Cannot recommend a cap from real data.")
        return

    lengths_arr = np.array(all_streak_lengths)
    mg_arr = np.array(all_mg_steps)
    n_completed_streaks = len(lengths_arr)
    log(f"completed streaks observed (pooled across {len(by_symbol)} symbols): {n_completed_streaks}")
    log(f"streak length (trades) stats: mean={lengths_arr.mean():.2f} median={np.median(lengths_arr):.0f} "
        f"p90={np.percentile(lengths_arr,90):.0f} p95={np.percentile(lengths_arr,95):.0f} "
        f"p99={np.percentile(lengths_arr,99):.0f} max={lengths_arr.max()}")
    log(f"mg_step reached (per-trade, before that trade's outcome) stats: "
        f"mean={mg_arr.mean():.2f} p95={np.percentile(mg_arr,95):.0f} p99={np.percentile(mg_arr,99):.0f} max={mg_arr.max()}")

    overall_win_rate = winner_cfg["oos"]["win_rate"] / 100.0
    log(f"\nREAL vs NAIVE-GEOMETRIC comparison (OOS win rate p={overall_win_rate*100:.1f}%; "
        f"naive P(single-direction losing run >= k) = (1-p)^k -- NOT the same statistic as the "
        f"streak-recovery rule actually used, see docstring):")
    log(f"{'k':>4} {'naive_(1-p)^k':>15} {'real_P(streak>=k)':>18} {'real_n_at_or_past_k':>20}")
    max_k = min(int(np.percentile(lengths_arr, 99)) + 3, 25)
    for k in range(1, max_k + 1):
        naive_p = (1 - overall_win_rate) ** k
        real_p = float((lengths_arr >= k).mean())
        real_n = int((lengths_arr >= k).sum())
        log(f"{k:>4} {naive_p:>15.4%} {real_p:>18.4%} {real_n:>20d}")

    affordable_step = max_affordable_step()
    margin_table = [(s, INITIAL_CAPITAL * BASE_MARGIN_PCT * (MG_MULT ** s)) for s in range(0, affordable_step + 3)]
    log(f"\nMARGIN AFFORDABILITY ($100 capital, 20x leverage, 1% of equity base, mult={MG_MULT}x/step):")
    for s, m in margin_table:
        flag = "  <- max affordable" if s == affordable_step else ("  BLOWN (exceeds $100)" if m > INITIAL_CAPITAL else "")
        log(f"  step {s:2d}: margin required = ${m:.2f}{flag}")

    coverage_step = None
    for k in range(0, max_k + 1):
        coverage = float((mg_arr <= k).mean())
        if coverage >= COVERAGE_TARGET:
            coverage_step = k
            break
    if coverage_step is None:
        coverage_step = int(np.percentile(mg_arr, 99))

    recommended_cap = min(coverage_step, affordable_step) if affordable_step >= 0 else 0
    log(f"\nRECOMMENDATION: step covering >={COVERAGE_TARGET*100:.0f}% of real observed mg_step values = {coverage_step}. "
        f"Max step $100/20x account can afford = {affordable_step}.")
    log(f"MAX_STEPS_CAP recommended = {recommended_cap} "
        f"({'coverage-limited' if recommended_cap == coverage_step and coverage_step <= affordable_step else 'capital-limited'})")

    out = {
        "winner_config": {**{k: winner_cfg[k] for k in ("bb_len", "bb_mult", "tp_pct", "sl_val")}, "sl_type": "fixed"},
        "n_oos_trades": len(oos_trades), "n_completed_streaks": n_completed_streaks,
        "streak_length_stats": {
            "mean": float(lengths_arr.mean()), "median": float(np.median(lengths_arr)),
            "p90": float(np.percentile(lengths_arr, 90)), "p95": float(np.percentile(lengths_arr, 95)),
            "p99": float(np.percentile(lengths_arr, 99)), "max": int(lengths_arr.max()),
        },
        "affordable_step_100usd_20x": affordable_step,
        "coverage_95pct_step": coverage_step,
        "recommended_max_steps_cap": recommended_cap,
        "mg_mult": MG_MULT, "base_margin_pct": BASE_MARGIN_PCT, "leverage": LEVERAGE,
    }
    with open(os.path.join(OUTPUT_DIR, "martingale_cap_recommendation.json"), "w") as f:
        json.dump(out, f, indent=2)
    log(f"\nWrote output/martingale_cap_recommendation.json")


if __name__ == "__main__":
    main()
