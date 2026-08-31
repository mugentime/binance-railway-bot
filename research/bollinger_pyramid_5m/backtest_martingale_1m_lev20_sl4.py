#!/usr/bin/env python3
"""
backtest_martingale_1m_lev20_sl4.py -- same pasted "Bollinger Bands Martingale" Pine script as
backtest_martingale_1m.py, but re-parameterized per a follow-up request: initial_capital=$100,
20x leverage, base entry = $20 notional (1 USD margin * 20x), and useSL=true at 4% (the original
pasted script had useSL=false -- this run turns it on, since with real fees TradingView's own
useSL=false version was still net positive and unhelpful for judging blow-up risk).

SIZING CHANGE from the literal script: the pasted Pine code sizes `currentQty` in raw base-asset
units (`baseQty=1.0` = 1 AUCTION). This run instead treats the martingale base unit as $1 of
MARGIN, so currentQty (in AUCTION) = (margin_usd * leverage) / entry_price, where
margin_usd = 1.0 * 2^mgStep. That is what "la entrada es de 20 usd notional (1*20)" specifies.
Everything else (crossover signal, TP-only-until-now exit logic, mgStep increment/reset rule,
20%-drawdown kill switch) is unchanged from the pasted script.

SL/TP SAME-BAR AMBIGUITY: when a single 1m candle's high/low range touches both the SL and TP
level (only possible on a volatile bar since SL=4% >> TP=1%, so this is rare but not impossible),
this backtest assumes SL fills first -- the same conservative "adverse-first" convention used by
backtest_bollinger_5m.py (comment there: "matches this repo's retest_trader.py adverse-first
convention elsewhere").

LIQUIDATION FLOOR: at 20x leverage a 5% adverse move (before fees) wipes out ~100% of the margin
posted for that entry (0.05 * 20 = 1.0). The 4% SL sits inside that buffer, so it should fire
first in the vast majority of cases -- but if a 1m candle gaps or wicks past both the SL and the
liquidation point in the same bar, this sim floors the realized loss on that trade at -margin_usd
(can't lose more than 100% of the margin actually posted, matching isolated-margin behavior) and
flags it. This is an approximation (real Binance liquidation triggers a bit before -100% margin
due to maintenance-margin buffers not modeled here), not an exact liquidation-engine replica.

TWO RUNS, both on real AUCTIONUSDT 1m Binance futures data, last 7 days:
  1) "Unconstrained" -- every signaled entry executes regardless of whether $100 could actually
     support it, zero commission/slippage. This isolates the pure signal/sizing math; I'm not
     asserting this is exactly what TradingView's margin-call engine would allow (its internals
     for margin_long/margin_short defaults aren't being guessed at here), just showing the
     unconstrained math as a reference point.
  2) "Realistic $100 account" -- real Binance taker fee + slippage on entries, AND entries are
     REJECTED if the required margin for the next martingale step exceeds currently available
     equity (100 + realized PnL while flat) -- because on an actual Binance account you cannot
     post margin you don't have. This is the answer to "would this actually survive on $100."
"""
import asyncio

import httpx
import numpy as np

import backtest_bollinger_5m as bt
from run_pine_bbands_sar import compute_bands

SYMBOL = "AUCTIONUSDT"
BB_LEN = 20
BB_MULT = 2.0
BASE_MARGIN_USD = 1.0
LEVERAGE = 20.0
MG_MULT = 2.0
MAX_STEPS = 10
TP_PERC = 1.0
SL_PERC = 4.0
MAX_DD_PERC = 20.0
INITIAL_CAPITAL = 100.0
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
    realized_pnl = 0.0
    peak_equity = INITIAL_CAPITAL
    kill_switch = False
    kill_switch_trips = 0
    rejected_margin_calls = 0
    liq_floor_hits = 0

    for i in range(BB_LEN, n):
        # 1) fill a pending market entry queued from the previous bar's signal, at THIS bar's open
        if pending_entry is not None and pending_entry["signal_bar"] == i - 1:
            direction = pending_entry["direction"]
            margin_usd = BASE_MARGIN_USD * (MG_MULT ** mg_step)
            current_equity = INITIAL_CAPITAL + realized_pnl
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

        # 2) check SL/TP fill (only checkable from the bar AFTER the entry bar onward); SL wins ties
        if position is not None and i > position["entry_bar"]:
            direction = position["direction"]
            hit_sl = (lows[i] <= sl_price) if direction == 1 else (highs[i] >= sl_price)
            hit_tp = (highs[i] >= tp_price) if direction == 1 else (lows[i] <= tp_price)
            exit_price = exit_reason = None
            if hit_sl:
                if direction == 1:
                    exit_price = opens[i] if opens[i] <= sl_price else sl_price
                else:
                    exit_price = opens[i] if opens[i] >= sl_price else sl_price
                exit_reason = "SL"
            elif hit_tp:
                if direction == 1:
                    exit_price = opens[i] if opens[i] >= tp_price else tp_price
                else:
                    exit_price = opens[i] if opens[i] <= tp_price else tp_price
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
                trades.append({"entry_time": open_times[position["entry_bar"]], "exit_time": open_times[i],
                                "direction": direction, "qty": position["qty"], "margin_usd": position["margin_usd"],
                                "net_pnl": net, "mg_step_used": mg_step, "reason": exit_reason, "floored": floored})
                mg_step = mg_step + 1 if net < 0 else 0
                mg_step = min(mg_step, MAX_STEPS)
                position = None
                tp_price = sl_price = None

        # 3) mark equity at this bar's close, update peak / drawdown / kill switch
        unrealized = 0.0
        if position is not None:
            unrealized = position["qty"] * (closes[i] - position["entry_price"]) * position["direction"]
        current_equity = INITIAL_CAPITAL + realized_pnl + unrealized
        if current_equity > peak_equity:
            peak_equity = current_equity
        drawdown_perc = (peak_equity - current_equity) / peak_equity * 100.0 if peak_equity > 0 else 100.0
        if drawdown_perc >= MAX_DD_PERC and not kill_switch:
            kill_switch = True
            kill_switch_trips += 1
        if current_equity >= peak_equity:
            kill_switch = False

        # 4) look for a fresh signal on this bar's confirmed close (only if flat, no order in flight)
        if position is None and pending_entry is None and not kill_switch:
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
        "trades": trades, "open_unrealized": open_unrealized, "kill_switch_trips": kill_switch_trips,
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
    max_margin_used = max((t["margin_usd"] for t in trades), default=BASE_MARGIN_USD)
    print(f"\n== {label} ==")
    print(f"Closed trades: {len(trades)}  win={win_rate:.1f}% ({wins}/{len(trades)}, TP={tp_hits} SL={sl_hits})  PF={pf_str}")
    print(f"Net PnL (closed only): ${net_closed:+.4f}")
    if res["open_unrealized"] is not None:
        print(f"Position still open at data end, unrealized: ${res['open_unrealized']:+.4f}")
    print(f"Final equity: ${res['final_equity']:.4f} (started ${INITIAL_CAPITAL:.2f}, {(res['final_equity']/INITIAL_CAPITAL-1)*100:+.2f}%)")
    print(f"Max martingale step reached: {max_mg}  (margin ${BASE_MARGIN_USD*MG_MULT**max_mg:.0f}, "
          f"notional ${BASE_MARGIN_USD*MG_MULT**max_mg*LEVERAGE:.0f} at {LEVERAGE:.0f}x)")
    print(f"Kill switch trips (20% DD from peak equity): {res['kill_switch_trips']}")
    if res["rejected_margin_calls"]:
        print(f"Entries REJECTED for insufficient margin: {res['rejected_margin_calls']} "
              f"(account couldn't afford the next martingale step)")
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
    print(f"Params: initial_capital=${INITIAL_CAPITAL:.0f}, leverage={LEVERAGE:.0f}x, "
          f"base entry=${BASE_MARGIN_USD*LEVERAGE:.0f} notional (${BASE_MARGIN_USD:.0f} margin), "
          f"TP={TP_PERC}%, SL={SL_PERC}%, martingale x{MG_MULT} up to step {MAX_STEPS}")

    res_unconstrained = simulate(klines, zero_cost=True, cap_margin=False)
    res_realistic = simulate(klines, zero_cost=False, cap_margin=True)

    report("Unconstrained (zero cost, every signal executes regardless of $100 capital)", res_unconstrained)
    report("Realistic $100 account (real Binance fee+slippage, entries blocked if margin unaffordable)",
           res_realistic)


if __name__ == "__main__":
    asyncio.run(main())
