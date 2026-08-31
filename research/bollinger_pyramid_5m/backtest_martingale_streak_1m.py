#!/usr/bin/env python3
"""
backtest_martingale_streak_1m.py -- backtest of the newly pasted "Bollinger Bands Martingale by
Streak" Pine script (a variant of the two earlier martingale scripts in this folder) on real
AUCTIONUSDT 1m Binance futures data, last 7 days.

WHAT'S DIFFERENT FROM backtest_martingale_1m_lev20_sl4.py (read the pasted source carefully --
this is NOT the same martingale-reset rule as before):
  var streakProfit = 0.0
  on each closed trade: streakProfit += lastTradeProfit
      if streakProfit > 0: streakProfit := 0; mgStep := 0
      else: mgStep += 1 (capped at maxSteps)
  This resets mgStep only once the CUMULATIVE PnL of the current losing streak turns net positive
  again -- a single winning trade does NOT reset mgStep if the streak is still underwater overall.
  That's a materially more aggressive escalation than "reset after any win": while recovering from
  a deep hole, mgStep keeps climbing even on trades that individually made money, as long as the
  running streak total is still <= 0.
  ALSO REMOVED vs the earlier scripts: there is no equity-drawdown kill switch anywhere in this
  source -- entries are only gated by `strategy.position_size == 0`. Max drawdown is still computed
  and reported below for information, but it does NOT block any entry in this simulation, because
  it doesn't in the pasted script either.

PARAMS for this run (from the request): bb length=10, bb mult=2, martingale multiplier=1.5,
TP=1.5%, SL=4% (useTP=true, useSL=true -- both given explicit percentages this time, unlike the
very first pasted script which had useSL=false by default).

"base qty 1%" -- ASSUMPTION: continuing the sizing convention established in the previous request
(margin-based, not raw-asset-unit), this is read as "base margin per entry = 1% of CURRENT account
equity" (not a fixed dollar amount -- it compounds/shrinks as equity moves), carrying forward the
$100 initial_capital and 20x leverage from the prior request since this message didn't restate
them. So base entry notional = current_equity * 1% * 20x, scaled further by 1.5^mgStep. This is an
assumption about unstated inputs, not a value pulled from anywhere else -- flagged in the output.

Mechanics carried over unchanged from the prior scripts: crossover entry, market-fill-next-bar-open,
TP/SL as resting orders checkable from the bar after entry onward (SL wins same-bar ties, this
repo's existing adverse-first convention), entry margin capped at available equity (real accounts
can't post margin they don't have), loss floored at -100% of posted margin (approximate
liquidation, maintenance-margin buffers not modeled).
"""
import asyncio

import httpx
import numpy as np

import backtest_bollinger_5m as bt
from run_pine_bbands_sar import compute_bands

SYMBOL = "AUCTIONUSDT"
BB_LEN = 10
BB_MULT = 2.0
BASE_MARGIN_PCT = 0.01     # ASSUMPTION: "base qty 1%" = 1% of current equity as margin
LEVERAGE = 20.0            # carried forward from the previous request, not restated here
MG_MULT = 1.5
MAX_STEPS = 20
TP_PERC = 1.5
SL_PERC = 4.0
INITIAL_CAPITAL = 100.0    # carried forward from the previous request, not restated here
WARMUP_MS = 60 * 60 * 1000
WINDOW_MS = 7 * 24 * 60 * 60 * 1000


async def fetch_1m_range(client, symbol, start_ms, end_ms):
    out = []
    cursor = start_ms
    while cursor < end_ms:
        r = await bt.get_json(client, "/fapi/v1/klines", {
            "symbol": symbol, "interval": "1m", "startTime": cursor, "endTime": end_ms, "limit": 1500,
        })
        if not r:
            break
        out.extend(r)
        last_close = int(r[-1][6])
        if last_close <= cursor or len(r) < 2:
            break
        cursor = last_close + 1
    return out


def simulate(klines, zero_cost, cap_margin):
    n = len(klines)
    opens = np.array([k["open"] for k in klines])
    highs = np.array([k["high"] for k in klines])
    lows = np.array([k["low"] for k in klines])
    closes = np.array([k["close"] for k in klines])
    open_times = [k["open_time"] for k in klines]
    upper, lower = compute_bands(closes, BB_LEN, BB_MULT)

    fee = 0.0 if zero_cost else bt.TAKER_FEE
    entry_slip = 0.0 if zero_cost else bt.slippage_frac(1)

    trades = []
    position = None            # {direction, entry_price, entry_bar, qty, margin_usd, entry_fee}
    tp_price = sl_price = None
    pending_entry = None       # {direction, signal_bar}
    mg_step = 0
    streak_profit = 0.0
    realized_pnl = 0.0
    peak_equity = INITIAL_CAPITAL
    max_dd_perc_seen = 0.0
    rejected_margin_calls = 0
    liq_floor_hits = 0

    for i in range(BB_LEN, n):
        # 1) fill a pending market entry queued from the previous bar's signal, at THIS bar's open
        if pending_entry is not None and pending_entry["signal_bar"] == i - 1:
            direction = pending_entry["direction"]
            current_equity = INITIAL_CAPITAL + realized_pnl
            margin_usd = current_equity * BASE_MARGIN_PCT * (MG_MULT ** mg_step)
            if cap_margin and margin_usd > current_equity:
                rejected_margin_calls += 1
                pending_entry = None
            else:
                raw_price = opens[i]
                fill_price = raw_price * (1 + entry_slip * direction)
                notional_usd = margin_usd * LEVERAGE
                qty = notional_usd / fill_price
                entry_fee = qty * fill_price * fee
                position = {"direction": direction, "entry_price": fill_price, "entry_bar": i,
                            "qty": qty, "margin_usd": margin_usd, "entry_fee": entry_fee}
                tp_price = fill_price * (1 + TP_PERC / 100.0) if direction == 1 else fill_price * (1 - TP_PERC / 100.0)
                sl_price = fill_price * (1 - SL_PERC / 100.0) if direction == 1 else fill_price * (1 + SL_PERC / 100.0)
                pending_entry = None

        # 2) check SL/TP fill (checkable from the bar AFTER the entry bar onward); SL wins ties
        if position is not None and i > position["entry_bar"]:
            direction = position["direction"]
            hit_sl = (lows[i] <= sl_price) if direction == 1 else (highs[i] >= sl_price)
            hit_tp = (highs[i] >= tp_price) if direction == 1 else (lows[i] <= tp_price)
            exit_price = exit_reason = None
            if hit_sl:
                exit_price = opens[i] if (opens[i] <= sl_price if direction == 1 else opens[i] >= sl_price) else sl_price
                exit_reason = "SL"
            elif hit_tp:
                exit_price = opens[i] if (opens[i] >= tp_price if direction == 1 else opens[i] <= tp_price) else tp_price
                exit_reason = "TP"
            if exit_price is not None:
                exit_fee = position["qty"] * exit_price * fee
                gross = position["qty"] * (exit_price - position["entry_price"]) * direction
                net = gross - position["entry_fee"] - exit_fee
                floored = False
                if net < -position["margin_usd"]:
                    net = -position["margin_usd"]
                    floored = True
                    liq_floor_hits += 1
                realized_pnl += net

                # martingale-by-streak update
                streak_profit += net
                if streak_profit > 0:
                    streak_profit = 0.0
                    mg_step = 0
                else:
                    mg_step = min(mg_step + 1, MAX_STEPS)

                trades.append({"entry_time": open_times[position["entry_bar"]], "exit_time": open_times[i],
                                "direction": direction, "qty": position["qty"], "margin_usd": position["margin_usd"],
                                "net_pnl": net, "mg_step_used": mg_step, "reason": exit_reason, "floored": floored,
                                "streak_profit_after": streak_profit})
                position = None
                tp_price = sl_price = None

        # 3) mark equity at this bar's close -- informational only, does NOT gate entries (no kill
        # switch in this script)
        unrealized = 0.0
        if position is not None:
            unrealized = position["qty"] * (closes[i] - position["entry_price"]) * position["direction"]
        current_equity = INITIAL_CAPITAL + realized_pnl + unrealized
        if current_equity > peak_equity:
            peak_equity = current_equity
        dd = (peak_equity - current_equity) / peak_equity * 100.0 if peak_equity > 0 else 100.0
        max_dd_perc_seen = max(max_dd_perc_seen, dd)

        # 4) look for a fresh signal on this bar's confirmed close (only if flat, no order in flight)
        if position is None and pending_entry is None:
            if not (np.isnan(lower[i - 1]) or np.isnan(lower[i]) or np.isnan(upper[i - 1]) or np.isnan(upper[i])):
                cross_up = closes[i - 1] <= lower[i - 1] and closes[i] > lower[i]
                cross_down = closes[i - 1] >= upper[i - 1] and closes[i] < upper[i]
                if cross_up:
                    pending_entry = {"direction": 1, "signal_bar": i}
                elif cross_down:
                    pending_entry = {"direction": -1, "signal_bar": i}

    open_unrealized = None
    if position is not None:
        mark = closes[n - 1]
        open_unrealized = position["qty"] * (mark - position["entry_price"]) * position["direction"]

    final_equity = INITIAL_CAPITAL + realized_pnl + (open_unrealized or 0.0)
    return {
        "trades": trades, "open_unrealized": open_unrealized, "max_dd_perc_seen": max_dd_perc_seen,
        "rejected_margin_calls": rejected_margin_calls, "liq_floor_hits": liq_floor_hits,
        "final_equity": final_equity,
    }


def report(label, res):
    trades = res["trades"]
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    sl_hits = sum(1 for t in trades if t["reason"] == "SL")
    tp_hits = sum(1 for t in trades if t["reason"] == "TP")
    net_closed = sum(t["net_pnl"] for t in trades)
    gross_win = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = -sum(t["net_pnl"] for t in trades if t["net_pnl"] <= 0)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    pf_str = "inf" if pf == float("inf") else f"{pf:.3f}"
    win_rate = 100 * wins / len(trades) if trades else 0.0
    max_mg = max((t["mg_step_used"] for t in trades), default=0)
    print(f"\n== {label} ==")
    print(f"Closed trades: {len(trades)}  win={win_rate:.1f}% ({wins}/{len(trades)}, TP={tp_hits} SL={sl_hits})  PF={pf_str}")
    print(f"Net PnL (closed only): ${net_closed:+.4f}")
    if res["open_unrealized"] is not None:
        print(f"Position still open at data end, unrealized: ${res['open_unrealized']:+.4f}")
    print(f"Final equity: ${res['final_equity']:.4f} (started ${INITIAL_CAPITAL:.2f}, "
          f"{(res['final_equity']/INITIAL_CAPITAL-1)*100:+.2f}%)")
    print(f"Max martingale step reached: {max_mg}  (multiplier {MG_MULT**max_mg:.2f}x base margin)")
    print(f"Max drawdown observed (informational -- this script has no kill switch): "
          f"{res['max_dd_perc_seen']:.2f}%")
    if res["rejected_margin_calls"]:
        print(f"Entries REJECTED for insufficient margin: {res['rejected_margin_calls']}")
    if res["liq_floor_hits"]:
        print(f"Trades where loss was floored at -100% margin (would-be liquidation): {res['liq_floor_hits']}")


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        latest = await bt.get_json(client, "/fapi/v1/klines", {"symbol": SYMBOL, "interval": "1m", "limit": 1})
        end_ms = int(latest[0][6])
        start_ms = end_ms - WINDOW_MS
        raw = await fetch_1m_range(client, SYMBOL, start_ms - WARMUP_MS, end_ms)

    klines = [{
        "open_time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
        "low": float(k[3]), "close": float(k[4]), "close_time": int(k[6]),
    } for k in raw]
    print(f"Fetched {len(klines)} real 1m candles for {SYMBOL} (Binance USDT-M futures)")
    print(f"Window (excl. warmup): {bt.ts_str(start_ms)} -> {bt.ts_str(end_ms)} UTC (last 7 days)")
    print(f"Params: bb_len={BB_LEN} mult={BB_MULT} martingale_mult={MG_MULT} maxSteps={MAX_STEPS} "
          f"TP={TP_PERC}% SL={SL_PERC}% | base margin={BASE_MARGIN_PCT*100:.0f}% of equity, "
          f"leverage={LEVERAGE:.0f}x, initial_capital=${INITIAL_CAPITAL:.0f} (both carried over, assumed)")

    res_unconstrained = simulate(klines, zero_cost=True, cap_margin=False)
    res_realistic = simulate(klines, zero_cost=False, cap_margin=True)

    report("Unconstrained (zero cost, every signal executes regardless of capital)", res_unconstrained)
    report("Realistic $100 account (real Binance fee+slippage, margin-capped entries)", res_realistic)


if __name__ == "__main__":
    asyncio.run(main())
