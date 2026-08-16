#!/usr/bin/env python3
"""
retest_trader.py — LIVE executor for the RETEST strategy.

FULLY INDEPENDENT of the martingale bot: imports NOTHING from it, never reads or writes
state.json or any bot file. Self-contained ON PURPOSE (own HMAC signing + detection copied
from the ob-logger). Runs 24/7 as its own Railway service.

STRATEGY (validated over 90 retests, see research/orderbook_signals.jsonl):
  Entry : on a C2 breakout (Bollinger-15m squeeze->breakout + RVOL5>=1.5 + 6h-range>=8%),
          REST a LIMIT at  broken_level + 0.10*ATR5*dir  for the retest window; it fills on
          the pullback back to that level (that IS the retest). Unfilled -> cancel, no entry.
  Exit  : STATIC bracket  TP +3% / SL -2%  (no trailing, no martingale). Max-hold 3h.
  Sizing: FLAT. notional = NOTIONAL_PCT% of account equity at LEVERAGE.
          Ramp: start NOTIONAL_PCT=100 for the first ~20 real trades (plumbing check),
          then manually flip NOTIONAL_PCT=250 (env). NEVER escalate size within a chain.
  Concurrency: ONE position at a time.

SAFETY:
  - DRY_RUN=1 by DEFAULT: it detects, logs the LIMIT/TP/SL it WOULD place, and paper-tracks
    the outcome against live klines — but places NO real orders. Flip DRY_RUN=0 only after the
    edge is reconfirmed at 100 retests.
  - Never holds a naked position: if the SL fails to place, the position is closed immediately.
  - ENABLED=0 kill-switch. Requires ONE-WAY position mode (matches the account); refuses hedge.
  - Does not set margin type (account is multi-assets / cross) — only leverage.

ENV (keys required; rest optional):
  BINANCE_API_KEY / BINANCE_API_SECRET   (same key the bot uses; already has futures-trade perms)
  DRY_RUN=1  ENABLED=1
  NOTIONAL_PCT=100  LEVERAGE=10  SL_PCT=2.0  TP_PCT=3.0
  MAX_HOLD_MIN=180  ENTRY_WINDOW_MIN=30  POLL_SECONDS=30  DETECT_SECONDS=300
  MIN_VOL_24H=10000000  RVOL_MIN=1.5  RANGE6H_MIN=8  ATR_MULT=0.10  MIN_NOTIONAL_USDT=5
"""
import os, sys, json, time, math, hmac, hashlib, urllib.parse
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
import numpy as np
import httpx
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

API_KEY = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")
FAPI = "https://fapi.binance.com"
RECV_WINDOW = 20000


def _f(n, d):
    try: return float(os.environ.get(n, d))
    except Exception: return float(d)
def _i(n, d):
    try: return int(float(os.environ.get(n, d)))
    except Exception: return int(d)
def _b(n, d):
    return str(os.environ.get(n, d)).strip().lower() in ("1", "true", "yes", "on")

DRY_RUN          = _b("DRY_RUN", "1")
ENABLED          = _b("ENABLED", "1")
NOTIONAL_PCT     = _f("NOTIONAL_PCT", 100.0)
LEVERAGE         = _i("LEVERAGE", 10)
SL_PCT           = _f("SL_PCT", 2.0)
TP_PCT           = _f("TP_PCT", 3.0)
MAX_HOLD_MIN     = _f("MAX_HOLD_MIN", 180.0)
ENTRY_WINDOW_MIN = _f("ENTRY_WINDOW_MIN", 30.0)
POLL_SECONDS     = _i("POLL_SECONDS", 30)
DETECT_SECONDS   = _i("DETECT_SECONDS", 300)
MIN_VOL_24H      = _f("MIN_VOL_24H", 10_000_000)
RVOL_MIN         = _f("RVOL_MIN", 1.5)
RANGE6H_MIN      = _f("RANGE6H_MIN", 8.0)
ATR_MULT         = _f("ATR_MULT", 0.10)
MIN_NOTIONAL_USDT = _f("MIN_NOTIONAL_USDT", 5.0)
SL_LIMIT_BAND_PCT = _f("SL_LIMIT_BAND_PCT", 1.0)       # SL is a stop-LIMIT; limit sits this far past the trigger (caps fill slippage)
HARD_STOP_BUFFER_PCT = _f("HARD_STOP_BUFFER_PCT", 0.5) # market backstop if price blows past the stop-limit band unfilled

CLIENT = httpx.Client(timeout=30.0)
TIME_OFFSET = 0


def log(msg, level="INFO"):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}] [{level}] {msg}", flush=True)


# ------------------------- signing / market data -------------------------
def now_ms():
    return int(time.time() * 1000) + TIME_OFFSET

def sync_time():
    global TIME_OFFSET
    try:
        TIME_OFFSET = int(CLIENT.get(f"{FAPI}/fapi/v1/time").json()["serverTime"]) - int(time.time() * 1000)
        log(f"time synced (offset {TIME_OFFSET}ms)")
    except Exception as e:
        TIME_OFFSET = 0
        log(f"time sync failed: {e}", "WARN")

def signed(method, path, params=None):
    p = dict(params or {})
    p["timestamp"] = now_ms()
    p.setdefault("recvWindow", RECV_WINDOW)
    q = urllib.parse.urlencode(p)
    p["signature"] = hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    r = CLIENT.request(method, f"{FAPI}{path}", params=p, headers={"X-MBX-APIKEY": API_KEY})
    if r.status_code != 200:
        raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text}")
    return r.json()

def pub(path, params):
    r = CLIENT.get(f"{FAPI}{path}", params=params)
    r.raise_for_status()
    return r.json()

def klines5(sym, start_ms=None, limit=100):
    p = {"symbol": sym, "interval": "5m", "limit": limit}
    if start_ms:
        p["startTime"] = int(start_ms)
    return pub("/fapi/v1/klines", p)


# ------------------------- exchange info / rounding -------------------------
SYMINFO = {}
def _dec_places(numstr):
    return max(0, -Decimal(str(numstr)).normalize().as_tuple().exponent)

def load_exchange_info():
    ex = pub("/fapi/v1/exchangeInfo", {})
    for s in ex["symbols"]:
        tick = step = None
        for f in s.get("filters", []):
            if f["filterType"] == "PRICE_FILTER": tick = f["tickSize"]      # keep RAW string
            elif f["filterType"] == "LOT_SIZE": step = f["stepSize"]
        SYMINFO[s["symbol"]] = {"pP": int(s["pricePrecision"]), "qP": int(s["quantityPrecision"]),
                                "tick": tick, "step": step, "maxlev": None,
                                "tdec": _dec_places(tick) if tick else int(s["pricePrecision"]),
                                "qdec": _dec_places(step) if step else int(s["quantityPrecision"])}
    log(f"exchange info cached: {len(SYMINFO)} symbols")

def load_leverage_brackets():
    """Per-symbol max leverage, so set_leverage never sends an invalid value (-4028 / -2027)."""
    try:
        lb = signed("GET", "/fapi/v1/leverageBracket", {})
    except Exception as e:
        log(f"leverageBracket fetch failed: {e}", "WARN"); return
    n = 0
    for row in (lb if isinstance(lb, list) else []):
        sym = row.get("symbol"); br = row.get("brackets", [])
        if sym in SYMINFO and br:
            SYMINFO[sym]["maxlev"] = max(int(b.get("initialLeverage", 0)) for b in br)
            n += 1
    log(f"leverage brackets cached: {n} symbols")

def pstr(price, sym):
    """Round to tick, format to the TICK's decimals (NOT pricePrecision: 650/737 symbols have
    pricePrecision > tick decimals, whose trailing digits trip -4014 on /fapi/v1/order)."""
    t = Decimal(SYMINFO[sym]["tick"])
    q = (Decimal(str(price)) / t).quantize(Decimal(1), rounding=ROUND_HALF_UP) * t
    return f"{q:.{SYMINFO[sym]['tdec']}f}"
def qstr(qty, sym):
    s = Decimal(SYMINFO[sym]["step"])
    q = (Decimal(str(qty)) / s).to_integral_value(rounding=ROUND_DOWN) * s
    return f"{q:.{SYMINFO[sym]['qdec']}f}"


# ------------------------- detection (copied from ob-logger, + ATR5) -------------------------
def sma(x, n):
    cs = np.cumsum(np.insert(x, 0, 0.0)); o = np.full(len(x), np.nan); o[n - 1:] = (cs[n:] - cs[:-n]) / n; return o
def rstd(c, n=20):
    o = np.full(len(c), np.nan)
    for i in range(n, len(c) + 1): o[i - 1] = c[i - n:i].std()
    return o
def rma(x, n):
    o = np.full(len(x), np.nan)
    if len(x) < n: return o
    o[n - 1] = x[:n].mean()
    for i in range(n, len(x)): o[i] = (o[i - 1] * (n - 1) + x[i]) / n
    return o

def check_c2(sym):
    k15 = pub("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 200})
    k5 = pub("/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 120})
    if len(k15) < 165 or len(k5) < 80:
        return None
    c15 = np.array([float(x[4]) for x in k15]); t15 = np.array([int(x[0]) for x in k15])
    h5 = np.array([float(x[2]) for x in k5]); l5 = np.array([float(x[3]) for x in k5])
    c5 = np.array([float(x[4]) for x in k5]); v5 = np.array([float(x[5]) for x in k5])
    basis = sma(c15, 20); sd = rstd(c15, 20); up = basis + 2 * sd; lo = basis - 2 * sd
    width = (up - lo) / basis
    b = len(c15) - 2  # last fully closed 15m bar
    if np.isnan(width[b]) or np.isnan(width[b - 1]):
        return None
    thr = np.nanpercentile(width[b - 150:b], 30)
    if not (width[b - 1] < thr):
        return None
    long_bo = c15[b] > up[b]; short_bo = c15[b] < lo[b]
    if not (long_bo or short_bo):
        return None
    base = np.nanmean(v5[-22:-2]); rvol5 = v5[-2] / base if base > 0 else 0
    if rvol5 < RVOL_MIN:
        return None
    r6 = (h5[-72:].max() - l5[-72:].min()) / max(1e-12, l5[-72:].min()) * 100
    if r6 < RANGE6H_MIN:
        return None
    pc = np.concatenate([[c5[0]], c5[:-1]])
    tr = np.maximum.reduce([h5 - l5, np.abs(h5 - pc), np.abs(l5 - pc)])
    atr5 = rma(tr, 14)[-1]
    if not np.isfinite(atr5):
        return None
    return {"symbol": sym, "dir": "LONG" if long_bo else "SHORT",
            "breakout_bar_ms": int(t15[b]), "level": float(up[b] if long_bo else lo[b]),
            "atr5": float(atr5), "rvol5": round(float(rvol5), 2), "range6h": round(float(r6), 1)}

def universe():
    ex = pub("/fapi/v1/exchangeInfo", {})
    perp = {s["symbol"] for s in ex["symbols"] if s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"}
    tk = pub("/fapi/v1/ticker/24hr", {})
    return [t["symbol"] for t in tk if t["symbol"] in perp
            and float(t.get("quoteVolume", 0) or 0) >= MIN_VOL_24H and float(t.get("lowPrice", 0) or 0) > 0]


# ------------------------- account / orders (signed) -------------------------
def equity_and_avail():
    a = signed("GET", "/fapi/v2/account", {})
    return float(a.get("totalMarginBalance", 0) or 0), float(a.get("availableBalance", 0) or 0)

def get_position(sym):
    r = signed("GET", "/fapi/v2/positionRisk", {"symbol": sym})
    return r[0] if r else None

def set_leverage(sym, lev):
    mx = SYMINFO.get(sym, {}).get("maxlev")
    use = min(lev, mx) if mx else lev
    if use != lev:
        log(f"  leverage capped {lev}x -> {use}x (symbol max {mx}) {sym}")
    try:
        signed("POST", "/fapi/v1/leverage", {"symbol": sym, "leverage": use})
    except Exception as e:
        log(f"set_leverage {sym} {use}x failed: {e}", "WARN")
    return use

def place_limit_entry(sym, side, price, qty):
    return signed("POST", "/fapi/v1/order", {"symbol": sym, "side": side, "type": "LIMIT",
        "timeInForce": "GTC", "price": pstr(price, sym), "quantity": qstr(qty, sym), "positionSide": "BOTH"})

def order_status(sym, oid):
    return signed("GET", "/fapi/v1/order", {"symbol": sym, "orderId": oid})

def cancel_order(sym, oid):
    try:
        signed("DELETE", "/fapi/v1/order", {"symbol": sym, "orderId": oid})
    except Exception as e:
        log(f"cancel {sym} {oid} failed: {e}", "WARN")

def cancel_all(sym):
    for path in ("/fapi/v1/allOpenOrders", "/fapi/v1/algoOpenOrders"):
        try:
            signed("DELETE", path, {"symbol": sym})
        except Exception:
            pass

def place_tp(sym, direction, tp_price, qty):
    side = "SELL" if direction == "LONG" else "BUY"
    return signed("POST", "/fapi/v1/order", {"symbol": sym, "side": side, "positionSide": "BOTH",
        "type": "LIMIT", "price": pstr(tp_price, sym), "quantity": qstr(qty, sym),
        "timeInForce": "GTC", "reduceOnly": "true"})

def place_sl(sym, direction, sl_price, qty):
    """Stop-LIMIT (not stop-market): triggers at sl_price, then rests a LIMIT that will not fill
    worse than sl_price +/- SL_LIMIT_BAND_PCT -> caps slippage. A hard market backstop (in the
    main loop) closes the position if price blows past the band while the limit stays unfilled."""
    side = "SELL" if direction == "LONG" else "BUY"
    band = SL_LIMIT_BAND_PCT / 100.0
    limit_price = sl_price * (1 - band) if direction == "LONG" else sl_price * (1 + band)
    return signed("POST", "/fapi/v1/algoOrder", {"symbol": sym, "side": side, "positionSide": "BOTH",
        "algoType": "CONDITIONAL", "type": "STOP", "triggerPrice": pstr(sl_price, sym),
        "price": pstr(limit_price, sym), "quantity": qstr(qty, sym), "reduceOnly": "true",
        "workingType": "MARK_PRICE", "timeInForce": "GTC"})

def close_market(sym, direction, qty):
    side = "SELL" if direction == "LONG" else "BUY"
    return signed("POST", "/fapi/v1/order", {"symbol": sym, "side": side, "type": "MARKET",
        "quantity": qstr(qty, sym), "reduceOnly": "true", "newOrderRespType": "RESULT"})

def realized_since(sym, since_ms):
    try:
        tr = signed("GET", "/fapi/v1/userTrades", {"symbol": sym, "startTime": int(since_ms), "limit": 1000})
        rp = sum(float(t.get("realizedPnl", 0) or 0) for t in tr)
        cm = sum(float(t.get("commission", 0) or 0) for t in tr if t.get("commissionAsset") == "USDT")
        return rp - cm
    except Exception:
        return None


def record(kind, d):
    """Structured trade line for harvesting from `railway logs` (mirrors ob-logger's SIGNAL)."""
    print("RETEST_TRADE " + json.dumps({"kind": kind, **d}), flush=True)


# ------------------------- state machine -------------------------
def paper_fill(a):
    """DRY_RUN: did price pull back to the LIMIT within the window? -> (filled, bar_ms)."""
    try:
        kl = klines5(a["sym"], start_ms=a["arm_ms"] - 5 * 60 * 1000, limit=20)
    except Exception:
        return False, None
    for k in kl:
        bt = int(k[0]); hi = float(k[2]); lo = float(k[3])
        if bt < a["arm_ms"] - 5 * 60 * 1000 or bt > a["expire_ms"]:
            continue
        if (a["d"] > 0 and lo <= a["lim"]) or (a["d"] < 0 and hi >= a["lim"]):
            return True, bt
    return False, None

def paper_exit(p):
    """DRY_RUN: resolve the paper position vs live klines (adverse-first) -> (reason, move%)."""
    try:
        kl = klines5(p["sym"], start_ms=p["entry_ms"] - 5 * 60 * 1000, limit=80)
    except Exception:
        return None, None
    d = p["d"]; e = p["entry"]
    for k in kl:
        bt = int(k[0])
        if bt < p["entry_ms"] - 5 * 60 * 1000:
            continue
        hi = float(k[2]); lo = float(k[3])
        if (lo <= e * (1 - SL_PCT / 100)) if d > 0 else (hi >= e * (1 + SL_PCT / 100)):
            return "SL", -SL_PCT
        if (hi >= e * (1 + TP_PCT / 100)) if d > 0 else (lo <= e * (1 - TP_PCT / 100)):
            return "TP", TP_PCT
    if now_ms() - p["entry_ms"] > MAX_HOLD_MIN * 60 * 1000:
        last = float(kl[-1][4]) if kl else e
        return "HOLD", (last / e - 1) * 100 * d
    return None, None

def open_real_position(a, entry_price, qty_filled):
    """Place the TP/SL bracket. Returns posn dict, or None (naked -> closed) on SL failure."""
    sym, direction, d = a["sym"], a["dir"], a["d"]
    tp = entry_price * (1 + TP_PCT / 100) if d > 0 else entry_price * (1 - TP_PCT / 100)
    sl = entry_price * (1 - SL_PCT / 100) if d > 0 else entry_price * (1 + SL_PCT / 100)
    try:
        place_tp(sym, direction, tp, qty_filled)
        log(f"  TP LIMIT @ {pstr(tp, sym)}")
    except Exception as e:
        log(f"  TP place failed {sym}: {e}", "ERROR")
    sl_ok = False
    for attempt in (1, 2, 3):
        try:
            place_sl(sym, direction, sl, qty_filled)
            log(f"  SL STOP_MARKET trigger @ {pstr(sl, sym)}")
            sl_ok = True
            break
        except Exception as e:
            log(f"  SL place failed {sym} (try {attempt}): {e}", "ERROR")
            time.sleep(1)
    if not sl_ok:
        log(f"  NAKED POSITION (no SL) {sym} -> closing immediately for safety", "ERROR")
        try:
            close_market(sym, direction, qty_filled)
        except Exception as e:
            log(f"  emergency close FAILED {sym}: {e}", "ERROR")
        cancel_all(sym)
        return None
    return {"sym": sym, "dir": direction, "d": d, "entry": entry_price, "qty": qty_filled,
            "tp": tp, "sl": sl, "notional": a["notional"], "entry_ms": now_ms(), "paper": False}


def main():
    if not API_KEY or not API_SECRET:
        log("BINANCE_API_KEY / BINANCE_API_SECRET not set in environment.", "ERROR")
        return 2
    sync_time()
    load_exchange_info()
    load_leverage_brackets()
    try:
        dual = signed("GET", "/fapi/v1/positionSide/dual", {}).get("dualSidePosition", False)
    except Exception as e:
        log(f"could not read position mode: {e}", "ERROR"); return 3
    if dual:
        log("Account is in HEDGE mode; this executor assumes ONE-WAY (positionSide BOTH). Refusing to run.", "ERROR")
        return 3
    eq, av = equity_and_avail()
    log("=" * 72)
    log(f"retest_trader | DRY_RUN={DRY_RUN} ENABLED={ENABLED} | notional={NOTIONAL_PCT:.0f}% lev={LEVERAGE}x "
        f"SL={SL_PCT}%(stop-limit band {SL_LIMIT_BAND_PCT}%,backstop {SL_PCT+SL_LIMIT_BAND_PCT+HARD_STOP_BUFFER_PCT:.1f}%) "
        f"TP={TP_PCT}% | 1-at-a-time | max-hold {MAX_HOLD_MIN:.0f}m")
    log(f"account: equity ${eq:.2f} | available ${av:.2f} | entry=resting LIMIT on the pullback")
    if not DRY_RUN:
        log("*** LIVE MODE: REAL ORDERS WILL BE PLACED ***", "WARN")
    else:
        log("DRY_RUN: no real orders; paper-tracking outcomes vs live klines")

    state = "IDLE"; armed = None; posn = None
    seen = set(); last_detect = 0.0; trade_count = 0

    while True:
        loop0 = time.time()
        try:
            if not ENABLED:
                log("ENABLED=0 kill-switch active; idling", "WARN")
                time.sleep(POLL_SECONDS); continue

            # ---------------- IN_POSITION ----------------
            if state == "IN_POSITION":
                p = posn
                if p["paper"]:
                    reason, move = paper_exit(p)
                    if reason:
                        pnl = p["notional"] * move / 100.0
                        log(f"[PAPER] CLOSE {p['sym']} {p['dir']} via {reason} | move {move:+.2f}% | ~${pnl:+.2f}")
                        record("paper", {"symbol": p["sym"], "dir": p["dir"], "entry": p["entry"],
                                         "exit_reason": reason, "move_pct": round(move, 3),
                                         "pnl_usd": round(pnl, 4), "notional": round(p["notional"], 2)})
                        trade_count += 1; posn = None; state = "IDLE"
                        log(f"trade_count={trade_count}" + ("  >>> 20 reached: consider NOTIONAL_PCT=250" if trade_count == 20 else ""))
                else:
                    pos = get_position(p["sym"])
                    amt = float(pos.get("positionAmt", 0) or 0) if pos else 0.0
                    if abs(amt) < 1e-12:  # closed by TP or SL
                        cancel_all(p["sym"])
                        pnl = realized_since(p["sym"], p["entry_ms"] - 2000)
                        move = (pnl / p["notional"] * 100) if (pnl is not None and p["notional"]) else None
                        log(f"CLOSE {p['sym']} {p['dir']} | realized ${pnl if pnl is not None else float('nan'):+.2f}"
                            + (f" ({move:+.2f}%)" if move is not None else ""))
                        record("real", {"symbol": p["sym"], "dir": p["dir"], "entry": p["entry"],
                                        "pnl_usd": round(pnl, 4) if pnl is not None else None,
                                        "move_pct": round(move, 3) if move is not None else None,
                                        "notional": round(p["notional"], 2)})
                        trade_count += 1; posn = None; state = "IDLE"
                        log(f"trade_count={trade_count}" + ("  >>> 20 reached: consider NOTIONAL_PCT=250" if trade_count == 20 else ""))
                    elif float(pos.get("markPrice", 0) or 0) > 0 and (float(pos["markPrice"]) / p["entry"] - 1) * 100 * p["d"] <= -(SL_PCT + SL_LIMIT_BAND_PCT + HARD_STOP_BUFFER_PCT):
                        mv = (float(pos["markPrice"]) / p["entry"] - 1) * 100 * p["d"]
                        log(f"HARD-STOP {p['sym']} move {mv:+.2f}% past stop-limit band -> market close", "WARN")
                        try: close_market(p["sym"], p["dir"], abs(amt))
                        except Exception as e: log(f"hard-stop close failed {p['sym']}: {e}", "ERROR")
                        cancel_all(p["sym"])
                        pnl = realized_since(p["sym"], p["entry_ms"] - 2000)
                        record("real", {"symbol": p["sym"], "dir": p["dir"], "entry": p["entry"],
                                        "pnl_usd": round(pnl, 4) if pnl is not None else None,
                                        "exit_reason": "HARD_STOP", "notional": round(p["notional"], 2)})
                        trade_count += 1; posn = None; state = "IDLE"
                    elif now_ms() - p["entry_ms"] > MAX_HOLD_MIN * 60 * 1000:
                        log(f"MAX-HOLD {p['sym']} -> market close")
                        try: close_market(p["sym"], p["dir"], abs(amt))
                        except Exception as e: log(f"close failed {p['sym']}: {e}", "ERROR")
                        cancel_all(p["sym"])
                        pnl = realized_since(p["sym"], p["entry_ms"] - 2000)
                        record("real", {"symbol": p["sym"], "dir": p["dir"], "entry": p["entry"],
                                        "pnl_usd": round(pnl, 4) if pnl is not None else None,
                                        "exit_reason": "MAX_HOLD", "notional": round(p["notional"], 2)})
                        trade_count += 1; posn = None; state = "IDLE"

            # ---------------- ARMED ----------------
            elif state == "ARMED":
                a = armed
                expired = now_ms() > a["expire_ms"]
                filled = False; fill_price = a["lim"]; fill_qty = a["qty"]
                if a["paper"]:
                    filled, _bar = paper_fill(a)
                else:
                    try:
                        st = order_status(a["sym"], a["order_id"])
                        if st.get("status") == "FILLED":
                            filled = True; fill_price = float(st.get("avgPrice") or a["lim"])
                            fill_qty = float(st.get("executedQty") or a["qty"])
                        elif st.get("status") in ("CANCELED", "EXPIRED", "REJECTED"):
                            log(f"entry order {a['sym']} {st.get('status')} -> IDLE"); armed = None; state = "IDLE"
                    except Exception as e:
                        log(f"order_status {a['sym']} error: {e}", "WARN")

                if state == "ARMED" and filled:
                    log(f"FILLED {a['sym']} {a['dir']} @ {fill_price:.6g}"
                        + ("  [PAPER]" if a["paper"] else f" qty {fill_qty}"))
                    if a["paper"]:
                        posn = {"sym": a["sym"], "dir": a["dir"], "d": a["d"], "entry": fill_price,
                                "qty": fill_qty, "notional": a["notional"], "entry_ms": now_ms(), "paper": True}
                        log(f"  [PAPER] bracket TP +{TP_PCT}% / SL -{SL_PCT}%")
                        armed = None; state = "IN_POSITION"
                    else:
                        posn = open_real_position(a, fill_price, fill_qty)
                        armed = None
                        state = "IN_POSITION" if posn else "IDLE"
                elif state == "ARMED" and expired:
                    if not a["paper"] and a["order_id"]:
                        cancel_order(a["sym"], a["order_id"])
                    log(f"retest window expired unfilled: {a['sym']} -> IDLE")
                    record("no_fill", {"symbol": a["sym"], "dir": a["dir"]})
                    armed = None; state = "IDLE"

            # ---------------- IDLE: scan for the next fresh breakout ----------------
            elif state == "IDLE":
                if time.time() - last_detect >= DETECT_SECONDS:
                    last_detect = time.time()
                    try:
                        uni = universe()
                    except Exception as e:
                        log(f"universe fetch failed: {e}", "WARN"); uni = []
                    log(f"scan: {len(uni)} symbols | state=IDLE | trades={trade_count} | waiting for a fresh C2 retest")
                    for sym in uni:
                        try:
                            sig = check_c2(sym)
                        except Exception:
                            continue
                        if not sig:
                            continue
                        key = f"{sym}:{sig['breakout_bar_ms']}"
                        if key in seen:
                            continue
                        seen.add(key)
                        d = 1 if sig["dir"] == "LONG" else -1
                        lim = sig["level"] + ATR_MULT * sig["atr5"] * d
                        eqx, avx = equity_and_avail()
                        notional = eqx * NOTIONAL_PCT / 100.0
                        if notional < MIN_NOTIONAL_USDT:
                            log(f"notional ${notional:.2f} < min ${MIN_NOTIONAL_USDT}; skip {sym}", "WARN")
                            continue
                        qty = notional / lim
                        armed = {"sym": sym, "dir": sig["dir"], "d": d, "lim": lim, "qty": qty,
                                 "notional": notional, "arm_ms": now_ms(),
                                 "expire_ms": now_ms() + int(ENTRY_WINDOW_MIN * 60 * 1000),
                                 "order_id": None, "paper": DRY_RUN}
                        log(f"ARM {sym} {sig['dir']} | level {sig['level']:.6g} -> retest LIMIT {lim:.6g} "
                            f"| qty {qstr(qty, sym)} notional ${notional:.2f} | rvol {sig['rvol5']} "
                            f"range6h {sig['range6h']}% | window {ENTRY_WINDOW_MIN:.0f}m")
                        if not DRY_RUN:
                            set_leverage(sym, LEVERAGE)
                            try:
                                o = place_limit_entry(sym, "BUY" if d > 0 else "SELL", lim, qty)
                                armed["order_id"] = o.get("orderId")
                                log(f"  LIMIT resting orderId={armed['order_id']}")
                            except Exception as e:
                                log(f"  LIMIT place failed {sym}: {e}; skip", "ERROR")
                                armed = None; continue
                        else:
                            log("  [DRY_RUN] would rest LIMIT; paper-fill on pullback")
                        state = "ARMED"
                        break  # take the FIRST fresh breakout (1 at a time)
                    if len(seen) > 5000:
                        seen = set(list(seen)[-2000:])
        except Exception as e:
            log(f"loop error: {e}", "ERROR")

        time.sleep(max(2, POLL_SECONDS - (time.time() - loop0)))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
    finally:
        CLIENT.close()
