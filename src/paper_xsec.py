"""PAPER (no-capital) FORWARD test of the cross-sectional momentum strategy.

Purpose: prove the edge works on live, out-of-sample data BEFORE any real capital is committed.
No API keys, no orders, no money — it only reads PUBLIC Binance klines and marks a hypothetical
portfolio to market.

FROZEN SPEC (pinned 2026-11-09; do NOT retune — retuning turns a forward test back into a backtest):
  - Universe: top UNIVERSE_N USDT-perp by 24h quote volume, re-read each rebalance (no survivorship:
    it only ever holds what is actually tradeable at the time).
  - Signal: rank by trailing LOOKBACK-day return.
  - Portfolios tracked in parallel, both weekly-rebalanced, 10bp/side cost on turnover:
      LONG-ONLY : equal-weight long the top K (beta-tilted; what a spot/1x account would run).
      MKT-NEUTRAL: equal-weight long top K / short bottom K (the real alpha; needs a futures acct).
  - Mark-to-market daily. Equity starts at 1.0 (report as %).

Stateless by design: it recomputes the WHOLE curve from PAPER_START on every run from public data, so
it is restart-proof and needs no stored state. It also APPENDS the latest reading to a CSV log on the
Railway volume (/data) if present, as an immutable timestamped record.

Run:  python src/paper_xsec.py           (one pass, prints the curve)
      python src/paper_xsec.py --loop     (re-run every INTERVAL_H hours; for the Railway service)
"""
import sys, os, time, json, csv, urllib.request
from datetime import datetime, timezone, timedelta

FAPI = "https://fapi.binance.com"
PAPER_START = os.environ.get("PAPER_START", "2026-11-09")   # OOS start (pinned). Forward from here.
LOOKBACK   = int(os.environ.get("LOOKBACK", "14"))
K          = int(os.environ.get("TOPK", "10"))
REBAL_DAYS = int(os.environ.get("REBAL_DAYS", "7"))
UNIVERSE_N = int(os.environ.get("UNIVERSE_N", "120"))
FEE        = float(os.environ.get("FEE", "0.001"))          # per side, on turnover
MIN_VOL    = float(os.environ.get("MIN_VOL_USD", "5000000"))
INTERVAL_H = float(os.environ.get("INTERVAL_H", "6"))
CST = timezone(timedelta(hours=-6))
LOGDIR = "/data" if os.path.isdir("/data") else os.path.dirname(os.path.abspath(__file__))
LOGFILE = os.path.join(LOGDIR, "paper_xsec_log.csv")
BAD = {"USDCUSDT","BUSDUSDT","TUSDUSDT","FDUSDUSDT","DAIUSDT","USDPUSDT","PAXGUSDT"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def universe():
    tick = _get(f"{FAPI}/fapi/v1/ticker/24hr")
    exi = _get(f"{FAPI}/fapi/v1/exchangeInfo")
    perp = {s["symbol"] for s in exi["symbols"]
            if s.get("contractType") == "PERPETUAL" and s["symbol"].endswith("USDT")
            and s["status"] == "TRADING"}
    rows = sorted(((t["symbol"], float(t["quoteVolume"])) for t in tick
                   if t["symbol"] in perp and t["symbol"] not in BAD and float(t["quoteVolume"]) > MIN_VOL),
                  key=lambda x: -x[1])
    return [s for s, _ in rows[:UNIVERSE_N]]


def daily_closes(sym, days):
    kl = _get(f"{FAPI}/fapi/v1/klines?symbol={sym}&interval=1d&limit={days}")[:-1]  # drop in-progress day
    return {int(k[0]): float(k[4]) for k in kl}


def simulate():
    start_ms = int(datetime.strptime(PAPER_START, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    need_days = LOOKBACK + 5 + int((time.time()*1000 - start_ms) / 86400000) + 3
    syms = universe()
    closes = {}
    for s in syms:
        try:
            d = daily_closes(s, min(need_days, 1000))
            if len(d) > LOOKBACK + 1:
                closes[s] = d
        except Exception:
            pass
        time.sleep(0.02)
    syms = list(closes.keys())
    days = sorted({d for c in closes.values() for d in c})
    # restrict to days >= (PAPER_START minus LOOKBACK buffer) so signals are computable at START
    days = [d for d in days if d >= start_ms - (LOOKBACK + 3) * 86400000]
    px = {s: [closes[s].get(d) for d in days] for s in syms}

    lo_eq, mn_eq = 1.0, 1.0           # long-only / market-neutral equity (start 1.0)
    lo_prev, mns_prev, mnl_prev = set(), set(), set()
    curve = []                        # (day, lo_eq, mn_eq) for days on/after PAPER_START
    lo_hold = mn_long = mn_short = []
    start_idx = next((i for i, d in enumerate(days) if d >= start_ms), len(days))

    for i in range(1, len(days)):
        # daily returns realised today for names held since yesterday
        def ret(s):
            a, b = px[s][i-1], px[s][i]
            return (b / a - 1.0) if (a and b) else None
        # rebalance on schedule (by index offset from start)
        if (i - start_idx) % REBAL_DAYS == 0 or lo_hold == []:
            sig = []
            for s in syms:
                j = i - 1                                   # rank on info THROUGH YESTERDAY (no look-ahead)
                p0, p1 = px[s][max(0, j-LOOKBACK)], px[s][j]
                if p0 and p1:
                    sig.append((s, p1 / p0 - 1.0))
            sig.sort(key=lambda x: x[1], reverse=True)
            valid = [s for s, _ in sig]
            if len(valid) >= 2 * K:
                mn_long = set(valid[:K]); mn_short = set(valid[-K:]); lo_hold = set(valid[:K])
                lo_turn = len(lo_hold ^ lo_prev) / K
                mn_turn = (len(mn_long ^ mnl_prev) + len(mn_short ^ mns_prev)) / (2 * K)
                lo_prev, mnl_prev, mns_prev = lo_hold, mn_long, mn_short
            else:
                lo_turn = mn_turn = 0.0
        else:
            lo_turn = mn_turn = 0.0
        # apply today's P&L (only once we are at/after START)
        if i > start_idx and lo_hold:
            lr = [ret(s) for s in lo_hold if ret(s) is not None]
            lo_r = (sum(lr) / len(lr)) if lr else 0.0
            sl = [ret(s) for s in mn_long if ret(s) is not None]
            ss = [ret(s) for s in mn_short if ret(s) is not None]
            mn_r = 0.5 * ((sum(sl)/len(sl)) if sl else 0.0) - 0.5 * ((sum(ss)/len(ss)) if ss else 0.0)
            lo_eq *= (1 + lo_r - lo_turn * FEE)
            mn_eq *= (1 + mn_r - mn_turn * FEE)
        if days[i] >= start_ms:
            curve.append((days[i], lo_eq, mn_eq))
    return curve, sorted(lo_hold), sorted(mn_long), sorted(mn_short), len(syms)


def stats(series):
    if len(series) < 2:
        return 0.0, 0.0, 0.0
    rets = [series[i] / series[i-1] - 1.0 for i in range(1, len(series))]
    import statistics
    mean = sum(rets) / len(rets)
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (mean / sd * (365 ** 0.5)) if sd else 0.0
    peak = series[0]; mdd = 0.0
    for v in series:
        peak = max(peak, v); mdd = min(mdd, v/peak - 1)
    return (series[-1] - 1) * 100, sharpe, mdd * 100


def run_once():
    curve, lo_hold, mn_long, mn_short, nsy = simulate()
    now = datetime.now(CST)
    print("=" * 72)
    print(f"PAPER FORWARD TEST (cross-sectional momentum) | {now:%Y-%m-%d %H:%M CST}")
    print(f"frozen spec: lb{LOOKBACK} top{K} rebal{REBAL_DAYS}d {FEE*1e4:.0f}bp/side | universe {nsy} liquid perps")
    print(f"OOS start: {PAPER_START}  | days elapsed: {len(curve)}")
    print("-" * 72)
    if len(curve) < 2:
        print("forward window just started — equity ~flat; real signal accrues over the coming days.")
    else:
        lo = [c[1] for c in curve]; mn = [c[2] for c in curve]
        lr, lsh, ldd = stats(lo); mr, msh, mdd = stats(mn)
        print(f"  LONG-ONLY top{K}   : {lr:+.1f}%  (Sharpe {lsh:+.2f}, maxDD {ldd:.0f}%)   [beta-tilted]")
        print(f"  MKT-NEUTRAL {K}/{K} : {mr:+.1f}%  (Sharpe {msh:+.2f}, maxDD {mdd:.0f}%)   [the real alpha]")
        last5 = curve[-5:]
        print("  recent equity (long-only / mkt-neutral):")
        for d, l, m in last5:
            print(f"    {datetime.fromtimestamp(d/1000, tz=CST):%m-%d}:  {(l-1)*100:+6.2f}% / {(m-1)*100:+6.2f}%")
    print(f"  current longs : {', '.join(s.replace('USDT','') for s in lo_hold)}")
    print(f"  current shorts: {', '.join(s.replace('USDT','') for s in mn_short)}")
    print("=" * 72)
    # immutable append log
    try:
        new = not os.path.exists(LOGFILE)
        with open(LOGFILE, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts_cst", "days", "longonly_eq", "mktneutral_eq"])
            le = curve[-1][1] if curve else 1.0
            me = curve[-1][2] if curve else 1.0
            w.writerow([now.strftime("%Y-%m-%d %H:%M"), len(curve), f"{le:.5f}", f"{me:.5f}"])
    except Exception as e:
        print(f"(log append failed: {e})")


def main():
    loop = "--loop" in sys.argv
    print(f"PAPER-XSEC starting | COMMIT {os.environ.get('RAILWAY_GIT_COMMIT_SHA','local')[:12]} | loop={loop} | log={LOGFILE}", flush=True)
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"run error: {e}", flush=True)
        if not loop:
            break
        time.sleep(INTERVAL_H * 3600)


if __name__ == "__main__":
    main()
