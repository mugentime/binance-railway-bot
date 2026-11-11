"""Scale-out MOMENTUM forward-test bot (long-only) — live on Binance USDT-perp futures.

Strategy (validated 2026-10-30 on 4yr / 20 majors; see memory momentum-continuation-edge):
  ENTRY (long): on a freshly CLOSED 1h candle, RSI(14) crosses UP through RSI_ENTRY (default 80)
                AND close > EMA(EMA_LEN) — i.e. buy confirmed momentum/strength, in an uptrend.
  EXIT (scale-out): bank SCALE_FRAC of the position at +TP1_ATR·ATR (LIMIT, reduceOnly); the
                initial protective stop sits at -SL_ATR·ATR (STOP_MARKET, full qty). Once the
                partial fills, cancel the initial stop, move a breakeven stop onto the remainder,
                and arm a native Binance TRAILING_STOP_MARKET so the runner trails server-side.
                Hard time cap: close the remainder at market after MAX_HOLD_H hours.

Why scale-out: the partial books the high hit-rate (>60% win every year 2022-26 in backtest), the
trailing runner supplies the positive-skew expectancy a plain fixed-TP lacks.

Risk: fixed LOT_USD notional per entry at LEVERAGE, at most MAX_POS concurrent, one per symbol.
This is a FORWARD TEST on small accounts — correctness & never-strand-a-stop matter more than fills.

Exchange is the source of truth (positions + open algo orders); a tiny JSON state file only holds
the scale-out metadata that cannot be read back (entry qty, atr at entry, open time, scaled flag).
Restart-safe: adopts live positions on boot.

Config via ENV (all optional, sensible defaults). Run with --live to place real orders; without it
the bot does ONE dry pass (prints intended actions, places nothing).
"""
import sys, os, time, json, argparse, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from order_executor import OrderExecutor, QuantityTooSmallError
import config as _cfg

# ---------------- config (env-parameterized) ----------------
ACCOUNT = os.environ.get("ACCOUNT", "MAIN")
DEFAULT_PAIRS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT",
                 "LINKUSDT","LTCUSDT","BCHUSDT","DOTUSDT","ATOMUSDT","ETCUSDT","FILUSDT","NEARUSDT",
                 "UNIUSDT","APTUSDT","AAVEUSDT","INJUSDT"]
_envp = os.environ.get("SYMBOLS", "").strip()
PAIRS = [p.strip().upper() for p in _envp.split(",") if p.strip()] if _envp else DEFAULT_PAIRS

LOT_USD    = float(os.environ.get("MOM_LOT_USD", "6"))  # notional per entry
# NOTE: dedicated MOM_* keys so we never inherit stale A/B vars (e.g. the old LEVERAGE=5 still set
# on the repurposed sub services). Reading "LEVERAGE" directly would silently trade at the wrong size.
LEVERAGE   = int(os.environ.get("MOM_LEVERAGE", "10"))
MAX_POS    = int(os.environ.get("MOM_MAX_POS", "4"))    # max concurrent positions
RSI_ENTRY  = float(os.environ.get("RSI_ENTRY", "80"))
RSI_LEN    = int(os.environ.get("RSI_LEN", "14"))
EMA_LEN    = int(os.environ.get("EMA_LEN", "200"))
ATR_LEN    = int(os.environ.get("ATR_LEN", "14"))
TP1_ATR    = float(os.environ.get("TP1_ATR", "0.7"))    # partial take-profit distance (× ATR)
SCALE_FRAC = float(os.environ.get("SCALE_FRAC", "0.5")) # fraction closed at partial TP
SL_ATR     = float(os.environ.get("SL_ATR", "3.0"))     # initial stop distance (× ATR)
TRAIL_ATR  = float(os.environ.get("TRAIL_ATR", "4.0"))  # runner trail distance (× ATR) -> callbackRate
MAX_HOLD_H = float(os.environ.get("MAX_HOLD_H", "240")) # time cap (hours)
SCAN_SECS  = int(os.environ.get("SCAN_SECS", "300"))    # loop interval
INTERVAL   = "1h"
STATE_DIR  = os.environ.get("STATE_DIR", os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(STATE_DIR, f"momentum_state_{ACCOUNT}.json")
FAPI = "https://fapi.binance.com"


def flog(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z][{ACCOUNT}] {msg}", flush=True)


# ---------------- state ----------------
def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(st):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(st, f)
    except Exception as e:
        flog(f"WARN: no pude guardar estado: {e}")


# ---------------- indicators ----------------
def fetch_klines(sym, limit=320):
    url = f"{FAPI}/fapi/v1/klines?symbol={sym}&interval={INTERVAL}&limit={limit}"
    with urllib.request.urlopen(url, timeout=20) as r:
        raw = json.loads(r.read().decode())
    # drop the last (in-progress) candle -> only CLOSED candles
    raw = raw[:-1]
    o = np.array([float(r[1]) for r in raw]); h = np.array([float(r[2]) for r in raw])
    l = np.array([float(r[3]) for r in raw]); c = np.array([float(r[4]) for r in raw])
    ot = np.array([int(r[0]) for r in raw], dtype=np.int64)
    return {"o": o, "h": h, "l": l, "c": c, "ot": ot}

def _ewm(x, alpha):
    """Exponential weighted mean, adjust=False (matches pandas ewm used in the backtest)."""
    y = np.empty(len(x), dtype=float)
    y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = alpha * x[i] + (1.0 - alpha) * y[i - 1]
    return y

def _wilder(x, n): return _ewm(x, 1.0 / n)

def indicators(kl):
    c, h, l = kl["c"], kl["h"], kl["l"]
    d = np.diff(c, prepend=c[0])                      # first delta = 0 (warmup, negligible over 320)
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = _wilder(up, RSI_LEN); ad = _wilder(dn, RSI_LEN)
    rs = au / np.where(ad == 0, np.nan, ad)
    rsi = np.nan_to_num(100.0 - 100.0 / (1.0 + rs), nan=50.0)
    ema = _ewm(c, 2.0 / (EMA_LEN + 1))
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = _wilder(tr, ATR_LEN)
    return {
        "close": float(c[-1]),
        "rsi": float(rsi[-1]), "rsi_prev": float(rsi[-2]),
        "ema": float(ema[-1]),
        "atr": float(atr[-1]),
        "candle_ot": int(kl["ot"][-1]),
    }

def entry_signal(ind):
    """Long momentum: RSI crosses UP through RSI_ENTRY on the last closed candle, in uptrend."""
    return (ind["rsi"] > RSI_ENTRY and ind["rsi_prev"] <= RSI_ENTRY and ind["close"] > ind["ema"])


# ---------------- order helpers (reduceOnly partial TP + stop) ----------------
def _fmt(ex, sym, price=None, qty=None):
    info = ex.symbol_info_cache[sym]
    out = {}
    if price is not None:
        out["price"] = f"{ex._round_to_tick_size(price, info['tickSize']):.{info['pricePrecision']}f}"
    if qty is not None:
        out["qty"] = f"{ex._round_to_step_size(qty, info['stepSize']):.{info['quantityPrecision']}f}"
    return out

def place_reduce_limit(ex, sym, qty, price):
    f = _fmt(ex, sym, price=price, qty=qty)
    params = {"symbol": sym, "side": "SELL", "positionSide": "BOTH", "type": "LIMIT",
              "price": f["price"], "quantity": f["qty"], "timeInForce": "GTC", "reduceOnly": "true"}
    params = ex._sign_params(params)
    r = ex.client.post(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/order", params=params, headers=ex._headers())
    r.raise_for_status()
    return f["price"]

def place_stop_market(ex, sym, qty, stop_price):
    """Protective STOP_MARKET placed as a CONDITIONAL algo order via /fapi/v1/algoOrder.

    ROOT CAUSE CONFIRMED 2026-11-09 (INITUSDT, first real entry since 2026-11-04): every
    STOP_MARKET attempt via the plain /fapi/v1/order endpoint (reduceOnly+quantity, the form
    this function used until now) was rejected with HTTP 400, {"code":-4120,"msg":"Order type
    not supported for this endpoint. Please use the Algo Order API endpoints instead."} — a
    previously-unverified failure, since no entry had filled since the 2026-11-04 fix that
    introduced this endpoint, so it was never actually exercised against a real position until
    today. order_executor.py's dead code (verify_and_place_missing_sl/place_tp_sl_orders,
    written for the martingale bot, never wired into momentum_live.py) already documents the
    exact same error and its cause: "Binance migrated all conditional order types (STOP_MARKET,
    TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT, TRAILING_STOP_MARKET) to the Algo Order service on
    2025-12-09". That dead code's working request shape — algoType=CONDITIONAL, triggerPrice
    (not stopPrice), POST to /fapi/v1/algoOrder — is reused here. The pre-2026-11-04 claim that
    "/fapi/v1/algoOrder only supports TWAP/VP, rejects conditional STOP_MARKET" was apparently
    based on a request missing the required algoType=CONDITIONAL param, not a real limitation.

    NOTE: an open CONDITIONAL algo order does NOT show up in GET /fapi/v1/openOrders — callers
    checking for its presence must also check get_algo_open_orders() (see _open_order_types())."""
    f = _fmt(ex, sym, price=stop_price, qty=qty)
    params = {"symbol": sym, "side": "SELL", "positionSide": "BOTH",
              "algoType": "CONDITIONAL", "type": "STOP_MARKET",
              "triggerPrice": f["price"], "quantity": f["qty"],
              "reduceOnly": "true", "workingType": "MARK_PRICE"}
    params = ex._sign_params(params)
    r = ex.client.post(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/algoOrder", params=params, headers=ex._headers())
    try:
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"{e} | body={getattr(r, 'text', '')}") from e
    return f["price"]


# ---------------- setup ----------------
def setup(ex, dry):
    flog(f"SETUP {len(PAIRS)} pares | {LEVERAGE}x CROSSED | ${LOT_USD}/trade | maxPos {MAX_POS} | "
         f"RSI>{RSI_ENTRY:.0f}&>EMA{EMA_LEN} | TP1 {TP1_ATR}·ATR x{SCALE_FRAC:.0%} | SL {SL_ATR}·ATR | "
         f"trail {TRAIL_ATR}·ATR | holdcap {MAX_HOLD_H:.0f}h")
    ok = []
    for s in PAIRS:
        if s not in ex.symbol_info_cache:
            flog(f"  {s}: no existe -> omito"); continue
        if dry:
            ok.append(s); continue
        try:
            if not ex.set_leverage(s, LEVERAGE):
                flog(f"  {s}: leverage no disp -> omito"); continue
            try: ex.set_margin_type(s, "CROSSED")
            except Exception: pass
            ok.append(s)
        except Exception as e:
            flog(f"  {s}: setup fallo ({e}) -> omito")
    flog(f"pares activos: {len(ok)}")
    return ok


def open_syms(ex, universe):
    """symbol -> dict(amt, entry) for live LONG positions within our universe."""
    out = {}
    try:
        for p in ex.get_all_open_positions():
            s = p["symbol"]; amt = float(p["positionAmt"])
            if s in universe and amt > 0:
                out[s] = {"amt": amt, "entry": float(p.get("entryPrice", 0)) or 0.0}
    except Exception as e:
        flog(f"WARN: no pude leer posiciones ({e})")
    return out


def callback_rate_from_atr(atr_abs, price):
    cr = (TRAIL_ATR * atr_abs / price) * 100.0
    return max(0.1, min(5.0, round(cr, 1)))


# Never ride a position with no working protective order indefinitely. Added 2026-11-09 after
# INITUSDT's STOP_MARKET was rejected 3x in a row with HTTP 400 ({"code":-4120,"msg":"Order type
# not supported for this endpoint. Please use the Algo Order API endpoints instead."}) -- a
# live, previously-unverified failure mode (no entry had filled since the 2026-11-04 endpoint
# fix, so this path was never actually exercised against a real position until today). If a
# protective order (SL or trailing stop) fails this many consecutive ticks in a row, flatten the
# position at market instead of retrying forever unprotected.
SL_FAIL_FLATTEN_AFTER = 2


# ---------------- manage one open position (exchange-driven) ----------------
def manage(ex, sym, live_amt, st, dry):
    """Enforce the scale-out exit plan for an open position. Mutates state dict `st` entry for sym."""
    meta = st.get(sym)
    if meta is None or "entry" not in meta:
        # adopted / unknown position (or a stale same-candle dedup marker left over
        # from a prior failed entry attempt on this symbol) -> reconstruct conservatively
        ind = indicators(fetch_klines(sym))
        pos = ex.get_position(sym)
        entry = float(pos.get("entryPrice", 0)) or ind["close"]
        meta = {"entry": entry, "entry_qty": live_amt, "atr": ind["atr"],
                "open_epoch": time.time(), "scaled": ex.has_trailing_stop(sym)}
        st[sym] = meta
        flog(f"  {sym}: ADOPTADO entry={entry:.6f} qty={live_amt} atr={ind['atr']:.6f} scaled={meta['scaled']}")

    entry = meta["entry"]; atr = meta["atr"]; age_h = (time.time() - meta["open_epoch"]) / 3600.0

    # time cap -> close remainder
    if age_h >= MAX_HOLD_H:
        flog(f"  {sym}: HOLD CAP {age_h:.0f}h>={MAX_HOLD_H:.0f}h -> cierro resto {live_amt}")
        if not dry:
            try: ex.cancel_all_orders(sym)
            except Exception: pass
            ex.close_position_market(sym, "LONG", live_amt)
        st.pop(sym, None)
        return

    if not meta["scaled"]:
        partial_filled = live_amt <= meta["entry_qty"] * (1 - SCALE_FRAC) + meta["entry_qty"] * 0.05
        if partial_filled:
            # transition to runner: cancel initial orders, breakeven stop + native trailing on remainder
            cr = callback_rate_from_atr(atr, entry)
            flog(f"  {sym}: PARTIAL llenado -> runner (qty={live_amt}) breakeven + trail {cr}%")
            if not dry:
                try: ex.cancel_all_orders(sym)
                except Exception: pass
                try: place_stop_market(ex, sym, live_amt, entry)  # breakeven
                except Exception as e: flog(f"    {sym}: BE stop fallo ({e})")
                ex.place_trailing_stop(sym, "LONG", live_amt, cr)
            meta["scaled"] = True
        else:
            # ensure the initial bracket (partial TP + protective stop) is present
            try:
                oo = _open_order_types(ex, sym)
            except Exception:
                oo = set()
            if not dry and ("LIMIT" not in oo or "STOP" not in oo):
                flog(f"  {sym}: re-armo bracket (TP1 {TP1_ATR}·ATR, SL {SL_ATR}·ATR)")
                try: ex.cancel_all_orders(sym)
                except Exception: pass
                try: place_reduce_limit(ex, sym, live_amt * SCALE_FRAC, entry + TP1_ATR * atr)
                except Exception as e: flog(f"    {sym}: TP1 fallo ({e})")
                try:
                    place_stop_market(ex, sym, live_amt, entry - SL_ATR * atr)
                    meta["sl_fail"] = 0
                except Exception as e:
                    meta["sl_fail"] = meta.get("sl_fail", 0) + 1
                    flog(f"    {sym}: SL fallo intento {meta['sl_fail']}/{SL_FAIL_FLATTEN_AFTER} ({e})")
                    if meta["sl_fail"] >= SL_FAIL_FLATTEN_AFTER:
                        flog(f"  {sym}: SL fallo {meta['sl_fail']}x seguidas -> cierro posicion "
                             f"(nunca dejar una posicion sin stop)")
                        try: ex.cancel_all_orders(sym)
                        except Exception: pass
                        ex.close_position_market(sym, "LONG", live_amt)
                        st.pop(sym, None)
                        return
                save_state(st)
    else:
        # runner phase: make sure the trailing stop is still armed
        if not dry and not ex.has_trailing_stop(sym):
            cr = callback_rate_from_atr(atr, entry)
            flog(f"  {sym}: trail ausente -> re-armo {cr}%")
            # place_trailing_stop never raises -- it catches its own HTTP errors and returns
            # True/False (see order_executor.py), so check the return value, not an exception.
            ok = ex.place_trailing_stop(sym, "LONG", live_amt, cr)
            if ok:
                meta["sl_fail"] = 0
            else:
                meta["sl_fail"] = meta.get("sl_fail", 0) + 1
                flog(f"    {sym}: trail fallo intento {meta['sl_fail']}/{SL_FAIL_FLATTEN_AFTER}")
                if meta["sl_fail"] >= SL_FAIL_FLATTEN_AFTER:
                    flog(f"  {sym}: trail fallo {meta['sl_fail']}x seguidas -> cierro posicion "
                         f"(nunca dejar una posicion sin stop)")
                    try: ex.cancel_all_orders(sym)
                    except Exception: pass
                    ex.close_position_market(sym, "LONG", live_amt)
                    st.pop(sym, None)
                    return
            save_state(st)


def _open_order_types(ex, sym):
    """Return set of {'LIMIT','STOP'} describing which protective orders are live for sym.
    A CONDITIONAL algo STOP_MARKET (see place_stop_market) does NOT appear in the plain
    /fapi/v1/openOrders listing -- it lives in the separate algo-orders listing, so both
    must be checked or an active SL would look missing and get needlessly re-armed."""
    types = set()
    params = ex._sign_params({"symbol": sym})
    r = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/openOrders", params=params, headers=ex._headers())
    r.raise_for_status()
    for o in r.json():
        t = str(o.get("type") or "")
        if t == "LIMIT": types.add("LIMIT")
        if "STOP" in t: types.add("STOP")
    try:
        for o in ex.get_algo_open_orders(sym):
            if o.get("algoType") == "CONDITIONAL" and "STOP" in str(o.get("orderType") or ""):
                types.add("STOP")
    except Exception:
        pass
    return types


# ---------------- entries ----------------
def try_entries(ex, universe, st, open_now, dry):
    room = MAX_POS - len(open_now)
    if room <= 0:
        flog(f"  sin cupo ({len(open_now)}/{MAX_POS} posiciones)"); return
    cands = []
    for s in universe:
        if s in open_now:
            continue
        try:
            ind = indicators(fetch_klines(s))
        except Exception as e:
            flog(f"  {s}: klines fallo ({e})"); continue
        if entry_signal(ind):
            # dedup: one entry per candle
            if st.get(s, {}).get("last_candle") == ind["candle_ot"]:
                continue
            cands.append((s, ind))
    if not cands:
        flog("  sin señales de entrada este tick"); return
    flog(f"  señales: {', '.join(s.replace('USDT','') for s,_ in cands)} (cupo {room})")
    for s, ind in cands[:room]:
        price = ind["close"]; atr = ind["atr"]
        if dry:
            flog(f"  [DRY] {s}: BUY ${LOT_USD}@~{price:.6f} RSI {ind['rsi_prev']:.0f}->{ind['rsi']:.0f} "
                 f">EMA{EMA_LEN}({ind['ema']:.4f}) | TP1 {price+TP1_ATR*atr:.6f}(x{SCALE_FRAC:.0%}) "
                 f"SL {price-SL_ATR*atr:.6f} trail {callback_rate_from_atr(atr, price)}%")
            continue
        try:
            avail = _available(ex)
            if avail < LOT_USD / LEVERAGE + 0.3:
                flog(f"  {s}: SKIP colateral libre ${avail:.2f}"); continue
            ex.place_market_order(s, "BUY", LOT_USD)
            pos = ex.get_position(s)
            qty = abs(float(pos["positionAmt"])); avg = float(pos["entryPrice"]) or price
            ex.cancel_all_orders(s)
            tp = place_reduce_limit(ex, s, qty * SCALE_FRAC, avg + TP1_ATR * atr)
            sl = place_stop_market(ex, s, qty, avg - SL_ATR * atr)
            st[s] = {"entry": avg, "entry_qty": qty, "atr": atr, "open_epoch": time.time(),
                     "scaled": False, "last_candle": ind["candle_ot"]}
            save_state(st)
            flog(f"  {s}: BUY ${LOT_USD} qty={qty} avg={avg:.6f} | TP1 {tp}(x{SCALE_FRAC:.0%}) SL {sl}")
            open_now[s] = {"amt": qty, "entry": avg}
        except QuantityTooSmallError as e:
            # Deterministic for this candle (price/precision won't change intra-candle) —
            # mark it processed so we don't re-attempt the same doomed signal every tick.
            st[s] = {"last_candle": ind["candle_ot"]}
            save_state(st)
            flog(f"  {s}: ERROR compra ({e})")
        except Exception as e:
            flog(f"  {s}: ERROR compra ({e})")


def _available(ex):
    try:
        params = ex._sign_params({})
        r = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v2/balance", params=params, headers=ex._headers())
        r.raise_for_status()
        u = next((b for b in r.json() if b["asset"] == "USDT"), None)
        return float(u["availableBalance"]) if u else 0.0
    except Exception:
        return 0.0


# ---------------- real P&L reporting (equity is NOT the same as available collateral:
# availableBalance excludes margin locked in open positions, so it drops every time a new
# position opens even with zero P&L change — use totalMarginBalance for true mark-to-market
# account equity, and /fapi/v1/income for real realized trade outcomes / win rate) --------
PNL_SINCE_MS = int(os.environ.get("MOM_PNL_SINCE_MS", "1793750400000"))  # 2026-11-04T00:00:00Z default


def _account_equity(ex):
    """True mark-to-market equity (wallet + unrealized), not just free/available margin."""
    try:
        params = ex._sign_params({})
        r = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v2/account", params=params, headers=ex._headers())
        r.raise_for_status()
        j = r.json()
        return {
            "wallet": float(j.get("totalWalletBalance", 0.0)),
            "unrealized": float(j.get("totalUnrealizedProfit", 0.0)),
            "margin_balance": float(j.get("totalMarginBalance", 0.0)),
            "available": float(j.get("availableBalance", 0.0)),
        }
    except Exception as e:
        return {"error": str(e)}


def _income_window(ex, itype, start_ms, end_ms, limit=1000):
    """One /fapi/v1/income page. Binance caps the startTime..endTime span on this endpoint,
    so callers must chunk; this fetches exactly one chunk and lets the caller paginate."""
    params = ex._sign_params({"incomeType": itype, "startTime": start_ms, "endTime": end_ms, "limit": limit})
    r = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/income", params=params, headers=ex._headers())
    r.raise_for_status()
    return r.json()


def _income_summary(ex, since_ms=PNL_SINCE_MS, limit=1000):
    """Real realized-trade outcomes since `since_ms`, via Binance's own income ledger —
    not a backtest sim. incomeType=REALIZED_PNL gives one row per closing fill (so this
    bot's scale-out design yields two rows per round-trip: the TP1 partial + the runner's
    exit); COMMISSION/FUNDING_FEE are netted in separately for the true dollar outcome.
    Binance caps startTime..endTime span on this endpoint, so this chunks in <=6-day
    windows from since_ms to now rather than relying on one open-ended query."""
    try:
        now_ms = int(time.time() * 1000)
        windows = []
        lo = since_ms
        step = 6 * 24 * 3600 * 1000
        while lo < now_ms:
            hi = min(lo + step, now_ms)
            windows.append((lo, hi))
            lo = hi
        out = {"REALIZED_PNL": [], "COMMISSION": [], "FUNDING_FEE": []}
        truncated = False
        for itype in out:
            for (lo, hi) in windows:
                page = _income_window(ex, itype, lo, hi, limit)
                if len(page) >= limit:
                    truncated = True  # a single window hit the page cap — some rows in it may be missing
                out[itype].extend(page)
        realized = out["REALIZED_PNL"]
        wins = [float(x["income"]) for x in realized if float(x["income"]) > 0]
        losses = [float(x["income"]) for x in realized if float(x["income"]) < 0]
        n = len(wins) + len(losses)
        return {
            "n_closed_legs": n,
            "win_rate": (len(wins) / n * 100.0) if n else None,
            "realized_pnl_total": sum(wins) + sum(losses),
            "commission_total": sum(float(x["income"]) for x in out["COMMISSION"]),
            "funding_total": sum(float(x["income"]) for x in out["FUNDING_FEE"]),
            "net_total": (sum(wins) + sum(losses)
                          + sum(float(x["income"]) for x in out["COMMISSION"])
                          + sum(float(x["income"]) for x in out["FUNDING_FEE"])),
            "truncated": truncated,
        }
    except Exception as e:
        return {"error": str(e)}


def log_real_pnl(ex, tag="PNL"):
    eq = _account_equity(ex)
    pnl = _income_summary(ex)
    if "error" in eq:
        flog(f"{tag} | equity fetch FAILED ({eq['error']})")
    else:
        flog(f"{tag} | equity: wallet=${eq['wallet']:.2f} unrealized=${eq['unrealized']:.2f} "
             f"marginBalance(true equity)=${eq['margin_balance']:.2f} available=${eq['available']:.2f}")
    if "error" in pnl:
        flog(f"{tag} | income fetch FAILED ({pnl['error']})")
    else:
        wr = f"{pnl['win_rate']:.1f}%" if pnl['win_rate'] is not None else "n/a (0 closed legs)"
        trunc = " [TRUNCATED at limit, real total is more negative/positive than shown]" if pnl["truncated"] else ""
        flog(f"{tag} | realized since {datetime.fromtimestamp(PNL_SINCE_MS/1000, tz=timezone.utc).strftime('%Y-%m-%d')}: "
             f"closed_legs={pnl['n_closed_legs']} win_rate={wr} "
             f"realized_pnl=${pnl['realized_pnl_total']:.2f} fees=${pnl['commission_total'] + pnl['funding_total']:.2f} "
             f"net=${pnl['net_total']:.2f}{trunc}")


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--live", action="store_true"); args = ap.parse_args()
    dry = not args.live
    flog("#" * 70)
    flog(f"MOMENTUM SCALE-OUT | account={ACCOUNT} | modo={'LIVE' if not dry else 'DRY'}")
    ex = OrderExecutor()
    universe = setup(ex, dry)
    if not universe:
        flog("sin pares. fin."); return
    st = load_state()

    if dry:
        flog("[DRY] una pasada: evaluando señales + estado (sin órdenes)")
        open_now = open_syms(ex, universe)
        flog(f"posiciones abiertas ahora: {len(open_now)} -> {list(open_now)}")
        for s, info in open_now.items():
            manage(ex, s, info["amt"], st, dry=True)
        try_entries(ex, universe, st, open_now, dry=True)
        flog("[DRY] fin. Para ir en vivo: python src/momentum_live.py --live")
        return

    # LIVE: startup identity check — log the account balance so the operator can confirm
    # THIS service is wired to the intended account (match against known balances).
    avail = _available(ex)
    flog(f"LIVE START | available collateral=${avail:.2f} | verify this matches the intended account")
    flog(f"RUNNING COMMIT: {os.environ.get('RAILWAY_GIT_COMMIT_SHA','local')[:12]}")
    log_real_pnl(ex, tag="PNL@START")

    # LIVE: indefinite rolling loop
    tick = 0
    while True:
        try:
            open_now = open_syms(ex, universe)
            flog(f"--- TICK {tick} | posiciones {len(open_now)}/{MAX_POS}: "
                 f"{', '.join(s.replace('USDT','') for s in open_now) or '—'} ---")
            # Real equity + realized-PnL/win-rate snapshot, ~hourly (not every tick: two
            # extra signed Binance calls each time) — so any run reviewing recent logs
            # always has a fresh true-equity reading without needing a fresh deploy.
            if tick % max(1, int(3600 / max(SCAN_SECS, 1))) == 0:
                try: log_real_pnl(ex, tag="PNL")
                except Exception as e: flog(f"PNL snapshot ERROR ({e})")
            # 1) manage/protect existing
            for s, info in list(open_now.items()):
                try: manage(ex, s, info["amt"], st, dry=False)
                except Exception as e: flog(f"  {s}: manage ERROR ({e})")
            # 2) clear state for symbols no longer open; cancel stray orders
            # (skip pure same-candle dedup markers — entries with no "entry" key never
            # had a position/orders placed, so there's nothing to cancel/clear yet)
            for s in list(st.keys()):
                if s not in open_now and "entry" in st[s]:
                    try: ex.cancel_all_orders(s)
                    except Exception: pass
                    st.pop(s, None)
            # 3) entries
            try_entries(ex, universe, st, open_now, dry=False)
            save_state(st)
        except Exception as e:
            flog(f"TICK ERROR: {e}")
        tick += 1
        time.sleep(SCAN_SECS)


if __name__ == "__main__":
    main()
