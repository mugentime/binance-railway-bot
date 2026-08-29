"""
Standalone 24/7 C2 order-book logger for Railway.

Self-contained ON PURPOSE: no imports from the trading bot, NO API keys, only PUBLIC
Binance market-data endpoints. It can never trade. It detects the C2 breakout signal
(Bollinger 15m squeeze->breakout + RVOL + 6h range) and, on each fresh signal, snapshots
the live order book (spread + depth at +/-0.1/0.3/0.5%) — the data klines cannot give us.

Each signal is printed to STDOUT as a `SIGNAL <json>` line so it can be harvested from
`railway logs`. Runs a scan every SCAN_SECONDS (default 300) forever.
"""
import os, sys, json, time
import numpy as np
import httpx

FAPI = "https://fapi.binance.com"
SCAN_SECONDS = int(os.environ.get("SCAN_SECONDS", "300"))
MIN_VOL_24H = float(os.environ.get("MIN_VOL_24H", "10000000"))
RVOL_MIN = float(os.environ.get("RVOL_MIN", "1.5"))
RANGE6H_MIN = float(os.environ.get("RANGE6H_MIN", "8"))
DATA_DIR = os.environ.get("DATA_DIR", "/data")  # Railway volume mount
STORE_PATH = os.path.join(DATA_DIR, "signals.jsonl")
CLIENT = httpx.Client(timeout=20.0)


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def load_persisted_keys():
    """Reload dedup keys from the volume so restarts never re-append signals."""
    keys = set()
    if not os.path.exists(STORE_PATH):
        return keys
    with open(STORE_PATH, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                keys.add(f"{r.get('symbol')}:{r.get('breakout_bar_ms')}")
            except Exception:
                pass
    return keys


def persist(rec):
    """Append one signal to the durable volume store. Never raises."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STORE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log(f"persist failed ({STORE_PATH}): {e}")
        return False


def store_writable():
    """Probe the volume without polluting the signal store."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        probe = os.path.join(DATA_DIR, ".probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception as e:
        log(f"store not writable ({DATA_DIR}): {e}")
        return False


def g(path, params):
    r = CLIENT.get(f"{FAPI}{path}", params=params)
    r.raise_for_status()
    return r.json()


def sma(x, n):
    cs = np.cumsum(np.insert(x, 0, 0.0)); out = np.full(len(x), np.nan)
    out[n - 1:] = (cs[n:] - cs[:-n]) / n; return out


def rstd(c, n=20):
    out = np.full(len(c), np.nan)
    for i in range(n, len(c) + 1):
        out[i - 1] = c[i - n:i].std()
    return out


def check_c2(sym):
    k15 = g("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 200})
    k5 = g("/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 120})
    if len(k15) < 165 or len(k5) < 80:
        return None
    c15 = np.array([float(x[4]) for x in k15]); t15 = np.array([int(x[0]) for x in k15])
    v5 = np.array([float(x[5]) for x in k5]); h5 = np.array([float(x[2]) for x in k5]); l5 = np.array([float(x[3]) for x in k5])
    basis = sma(c15, 20); sd = rstd(c15, 20)
    up = basis + 2 * sd; lo = basis - 2 * sd; width = (up - lo) / basis
    b = len(c15) - 2  # last fully closed 15m bar
    if np.isnan(width[b]) or np.isnan(width[b - 1]):
        return None
    thr = np.nanpercentile(width[b - 150:b], 30)
    if not (width[b - 1] < thr):
        return None
    long_bo = c15[b] > up[b]; short_bo = c15[b] < lo[b]
    if not (long_bo or short_bo):
        return None
    base = np.nanmean(v5[-22:-2])
    rvol5 = v5[-2] / base if base > 0 else 0
    if rvol5 < RVOL_MIN:
        return None
    r6 = (h5[-72:].max() - l5[-72:].min()) / max(1e-12, l5[-72:].min()) * 100
    if r6 < RANGE6H_MIN:
        return None
    return {"dir": "LONG" if long_bo else "SHORT", "breakout_bar_ms": int(t15[b]),
            "breakout_level": float(up[b] if long_bo else lo[b]),
            "rvol5": round(float(rvol5), 2), "range6h_pct": round(float(r6), 1)}


def depth_snapshot(sym):
    d = g("/fapi/v1/depth", {"symbol": sym, "limit": 500})
    bids = [(float(p), float(q)) for p, q in d.get("bids", []) if float(q) > 0]
    asks = [(float(p), float(q)) for p, q in d.get("asks", []) if float(q) > 0]
    if not bids or not asks:
        return None
    mid = (bids[0][0] + asks[0][0]) / 2
    snap = {"mid": mid, "spread_pct": round((asks[0][0] - bids[0][0]) / mid * 100, 4)}
    for band in (0.1, 0.3, 0.5):
        snap[f"buy_depth_{band}pct_usdt"] = round(sum(p * q for p, q in asks if p <= mid * (1 + band / 100)), 2)
        snap[f"sell_depth_{band}pct_usdt"] = round(sum(p * q for p, q in bids if p >= mid * (1 - band / 100)), 2)
    return snap


def universe():
    ex = g("/fapi/v1/exchangeInfo", {})
    perp = {s["symbol"] for s in ex["symbols"] if s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"}
    tk = g("/fapi/v1/ticker/24hr", {})
    return [t["symbol"] for t in tk if t["symbol"] in perp
            and float(t.get("lowPrice", 0) or 0) > 0 and float(t.get("quoteVolume", 0) or 0) >= MIN_VOL_24H]


def main():
    log(f"OB logger starting | scan every {SCAN_SECONDS}s | RVOL>={RVOL_MIN} range6h>={RANGE6H_MIN}% vol>=${MIN_VOL_24H:,.0f}")
    seen = load_persisted_keys()
    log(f"store {STORE_PATH}: {len(seen)} signals loaded, writable={store_writable()}")
    total = 0
    while True:
        t0 = time.time(); found = 0; n = 0
        try:
            uni = universe()
        except Exception as e:
            log(f"universe fetch failed: {e}; retrying next cycle"); time.sleep(SCAN_SECONDS); continue
        for sym in uni:
            n += 1
            try:
                sig = check_c2(sym)
            except Exception:
                continue
            if not sig:
                continue
            key = f"{sym}:{sig['breakout_bar_ms']}"
            if key in seen:
                continue
            try:
                book = depth_snapshot(sym)
            except Exception:
                continue
            if not book:
                continue
            seen.add(key); found += 1; total += 1
            rec = {"ts_utc": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), "symbol": sym, **sig, "book": book}
            print("SIGNAL " + json.dumps(rec), flush=True)
            persist(rec)
            time.sleep(0.05)
        if len(seen) > 5000:
            seen = set(list(seen)[-2000:])
        log(f"cycle done: {n} pairs, {found} new signals, total={total}, took {time.time()-t0:.0f}s")
        time.sleep(max(5, SCAN_SECONDS - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        CLIENT.close()
