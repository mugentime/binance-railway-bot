#!/usr/bin/env python3
"""
backtest_martingale_1m.py -- faithful backtest of the user-pasted Pine Script v6 strategy
("Bollinger Bands Martingale") on REAL Binance USDT-M futures 1m data for AUCTIONUSDT, last 7
days. This is a DIFFERENT script from the earlier "Bollinger Bands Strategy" SAR script in this
folder -- no stop-and-reverse, no OCA orders. Mechanics, read from the pasted source line by line:

  basis = SMA(close,20); dev = 2.0*stdev(close,20); upper=basis+dev; lower=basis-dev
  buyEntry  = crossover(close, lower)
  sellEntry = crossunder(close, upper)
  if position_size == 0 and not killSwitch:
      if buyEntry:  strategy.entry(long,  qty=currentQty)
      if sellEntry: strategy.entry(short, qty=currentQty)
  useTP=true (1.0%), useSL=false (default) -> only a TP limit exit, NO stop-loss. A losing trade
  can only close by eventually touching TP; until then it just sits open accumulating unrealized
  loss -- unbounded risk per trade is inherent to the pasted script's default inputs, not a bug in
  this backtest.
  currentQty = baseQty(1.0) * martingaleMult(2.0)^mgStep, mgStep += 1 after a losing CLOSED trade
  (capped at maxSteps=10, i.e. up to 1024x base size), resets to 0 after a non-losing closed trade.
  killSwitch: trips when equity drawdown from its running peak >= maxDrawdownPerc (20%); blocks new
  entries only (an already-open position/TP order is unaffected); clears the moment equity makes a
  new peak.

ORDER TIMING (standard Pine backtest semantics, not look-ahead):
  - strategy.entry() with no limit/stop = market order, filled at the OPEN of the bar AFTER the
    signal bar (script executes once per closed historical bar; orders queued that execution fill
    next bar).
  - strategy.exit(limit=TP) is set up in the script execution that first sees position_size != 0,
    which is the close of the ENTRY bar (one bar after the signal) -- so the TP limit order only
    becomes checkable starting the bar AFTER that, i.e. two bars after the original signal bar.

COSTS: the pasted strategy() call sets neither commission_value nor slippage, so TradingView's
Strategy Tester runs this at ZERO commission and ZERO slippage by default -- that is the faithful
replication and the number reported as primary. A second, clearly-labeled pass adds this project's
usual real-world cost model (0.04% taker fee + tramo-1 slippage on the market entry only; the TP
exit is a resting limit order so it fills at its exact price, no slippage) so the user can see the
gap between "what Pine reports" and "what this would actually cost on Binance." No funding is
added to either pass -- Pine's backtester does not model perpetual funding unless coded in, and
this script doesn't code it in, so including it would misrepresent what TradingView shows.

initial_capital: not overridden in the pasted script, so it uses Pine's documented default of
1,000,000 (this is an ASSUMPTION about an unset input, not fetched from anywhere -- flagged because
it only affects whether/when the killSwitch trips, not trade generation or per-trade PnL).

Data: real AUCTIONUSDT 1m klines from Binance USDT-M futures (fapi.binance.com/fapi/v1/klines),
paginated, anchored to the most recent closed candle on the exchange (not the local clock), minus 7
days, plus 1h warmup for the length=20 rolling calc.
"""
import asyncio
from datetime import datetime, timezone

import httpx
import numpy as np

import backtest_bollinger_5m as bt
from run_pine_bbands_sar import compute_bands

SYMBOL = "AUCTIONUSDT"
BB_LEN = 20
BB_MULT = 2.0
BASE_QTY = 1.0
MG_MULT = 2.0
MAX_STEPS = 10
TP_PERC = 1.0
MAX_DD_PERC = 20.0
INITIAL_CAPITAL = 1_000_000.0  # Pine default; not set explicitly in the pasted script
WARMUP_MS = 60 * 60 * 1000  # 1h of extra 1m candles before the 7d window, for the length=20 warmup
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


def simulate(klines, zero_cost):
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
    position = None          # {direction, entry_price, entry_bar, qty, entry_fee}
    tp_price = None
    pending_entry = None     # {direction, signal_bar}
    mg_step = 0
    realized_pnl = 0.0
    peak_equity = INITIAL_CAPITAL
    kill_switch = False
    kill_switch_trips = 0

    for i in range(BB_LEN, n):
        # 1) fill a pending market entry queued from the previous bar's signal, at THIS bar's open
        if pending_entry is not None and pending_entry["signal_bar"] == i - 1:
            direction = pending_entry["direction"]
            raw_price = opens[i]
            fill_price = raw_price * (1 + entry_slip * direction)
            qty = BASE_QTY * (MG_MULT ** mg_step)
            entry_fee = qty * fill_price * fee
            position = {"direction": direction, "entry_price": fill_price, "entry_bar": i,
                        "qty": qty, "entry_fee": entry_fee}
            tp_price = fill_price * (1 + TP_PERC / 100.0) if direction == 1 else fill_price * (1 - TP_PERC / 100.0)
            pending_entry = None

        # 2) check TP fill (only checkable from the bar AFTER the entry bar onward)
        if position is not None and i > position["entry_bar"]:
            direction = position["direction"]
            touched = (highs[i] >= tp_price) if direction == 1 else (lows[i] <= tp_price)
            if touched:
                # gap-through fills at the open (better than the limit price); otherwise at tp_price
                if direction == 1:
                    exit_price = opens[i] if opens[i] >= tp_price else tp_price
                else:
                    exit_price = opens[i] if opens[i] <= tp_price else tp_price
                exit_fee = position["qty"] * exit_price * fee
                gross = position["qty"] * (exit_price - position["entry_price"]) * direction
                net = gross - position["entry_fee"] - exit_fee
                realized_pnl += net
                trades.append({"entry_time": open_times[position["entry_bar"]], "exit_time": open_times[i],
                                "direction": direction, "qty": position["qty"], "net_pnl": net,
                                "mg_step_used": mg_step, "reason": "TP"})
                mg_step = mg_step + 1 if net < 0 else 0
                mg_step = min(mg_step, MAX_STEPS)
                position = None
                tp_price = None

        # 3) mark equity at this bar's close, update peak / drawdown / kill switch
        unrealized = 0.0
        if position is not None:
            unrealized = position["qty"] * (closes[i] - position["entry_price"]) * position["direction"]
        current_equity = INITIAL_CAPITAL + realized_pnl + unrealized
        if current_equity > peak_equity:
            peak_equity = current_equity
        drawdown_perc = (peak_equity - current_equity) / peak_equity * 100.0
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

    return trades, open_unrealized, kill_switch_trips, mg_step


def report(label, trades, open_unrealized, kill_switch_trips):
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    losses = sum(1 for t in trades if t["net_pnl"] <= 0)
    net_closed = sum(t["net_pnl"] for t in trades)
    gross_win = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = -sum(t["net_pnl"] for t in trades if t["net_pnl"] <= 0)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    pf_str = "inf" if pf == float("inf") else f"{pf:.3f}"
    win_rate = 100 * wins / len(trades) if trades else 0.0
    max_mg = max((t["mg_step_used"] for t in trades), default=0)
    print(f"\n== {label} ==")
    print(f"Closed trades: {len(trades)}  win={win_rate:.1f}% ({wins}/{len(trades)})  PF={pf_str}")
    print(f"Net PnL (closed only): {net_closed:+.6f} AUCTION-quote-equivalent (see note on units below)")
    if open_unrealized is not None:
        total = net_closed + open_unrealized
        print(f"Position still open at data end, unrealized: {open_unrealized:+.6f} -> total incl. open: {total:+.6f}")
    print(f"Max martingale step reached: {max_mg} (qty multiplier {MG_MULT**max_mg:.0f}x base)")
    print(f"Kill switch trips (20% DD from peak equity, initial_capital=${INITIAL_CAPITAL:,.0f} assumed): {kill_switch_trips}")


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

    trades_zero, open_u_zero, kst_zero, _ = simulate(klines, zero_cost=True)
    trades_real, open_u_real, kst_real, _ = simulate(klines, zero_cost=False)

    report("Pine defaults: zero commission, zero slippage (what TradingView Strategy Tester reports)",
           trades_zero, open_u_zero, kst_zero)
    report("+ realistic Binance costs (0.04% taker fee, tramo-1 slippage on market entries)",
           trades_real, open_u_real, kst_real)

    print("\nNote on units: baseQty=1 means each entry trades 1 unit of AUCTION (not $1 or 1% of "
          "equity), scaling by 2^mg_step on consecutive losses. PnL figures above are in USDT "
          "(AUCTIONUSDT is quoted in USDT) since qty*price is already in quote currency.")


if __name__ == "__main__":
    asyncio.run(main())
