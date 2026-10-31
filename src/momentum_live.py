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
import pandas as pd
import numpy as np
from order_executor import OrderExecutor
import config as _cfg

# ---------------- config (env-parameterized) ----------------
ACCOUNT = os.environ.get("ACCOUNT", "MAIN")
DEFAULT_PAIRS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT",
                 "LINKUSDT","LTCUSDT","BCHUSDT","DOTUSDT","ATOMUSDT","ETCUSDT","FILUSDT","NEARUSDT",
                 "UNIUSDT","APTUSDT","AAVEUSDT","INJUSDT"]
_envp = os.environ.get("SYMBOLS", "").strip()
PAIRS = [p.strip().upper() for p in _envp.split(",") if p.strip()] if _envp else DEFAULT_PAIRS

LOT_USD    = float(os.environ.get("LOT_USD", "6"))      # notional per entry
LEVERAGE   = int(os.environ.get("LEVERAGE", "10"))
MAX_POS    = int(os.environ.get("MAX_POS", "4"))        # max concurrent positions
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
    df = pd.DataFrame(raw, columns=["ot","o","h","l","c","v","ct","qv","n","tb","tq","ig"])
    for col in ("o","h","l","c"):
        df[col] = df[col].astype(float)
    return df

def _wilder(s, n):
    return s.ewm(alpha=1.0/n, adjust=False).mean()

def indicators(df):
    c, h, l = df["c"], df["h"], df["l"]
    d = c.diff()
    up = d.clip(lower=0); dn = (-d.clip(upper=0))
    rs = _wilder(up, RSI_LEN) / _wilder(dn, RSI_LEN).replace(0, np.nan)
    rsi = (100 - 100/(1+rs)).fillna(50)
    ema = c.ewm(span=EMA_LEN, adjust=False).mean()
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    atr = _wilder(tr, ATR_LEN)
    return {
        "close": float(c.iloc[-1]),
        "rsi": float(rsi.iloc[-1]), "rsi_prev": float(rsi.iloc[-2]),
        "ema": float(ema.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "candle_ot": int(df["ot"].iloc[-1]),
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
    """Protective STOP_MARKET (reduceOnly) via Algo endpoint (Binance moved conditional orders there)."""
    f = _fmt(ex, sym, price=stop_price, qty=qty)
    params = {"symbol": sym, "side": "SELL", "positionSide": "BOTH", "algoType": "CONDITIONAL",
              "type": "STOP_MARKET", "stopPrice": f["price"], "quantity": f["qty"],
              "reduceOnly": "true", "workingType": "MARK_PRICE"}
    params = ex._sign_params(params)
    r = ex.client.post(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/algoOrder", params=params, headers=ex._headers())
    r.raise_for_status()
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


# ---------------- manage one open position (exchange-driven) ----------------
def manage(ex, sym, live_amt, st, dry):
    """Enforce the scale-out exit plan for an open position. Mutates state dict `st` entry for sym."""
    meta = st.get(sym)
    if meta is None:
        # adopted / unknown position -> reconstruct conservatively
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
                try: place_stop_market(ex, sym, live_amt, entry - SL_ATR * atr)
                except Exception as e: flog(f"    {sym}: SL fallo ({e})")
    else:
        # runner phase: make sure the trailing stop is still armed
        if not dry and not ex.has_trailing_stop(sym):
            cr = callback_rate_from_atr(atr, entry)
            flog(f"  {sym}: trail ausente -> re-armo {cr}%")
            ex.place_trailing_stop(sym, "LONG", live_amt, cr)


def _open_order_types(ex, sym):
    """Return set of {'LIMIT','STOP'} describing which protective orders are live for sym."""
    types = set()
    params = ex._sign_params({"symbol": sym})
    r = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/openOrders", params=params, headers=ex._headers())
    r.raise_for_status()
    for o in r.json():
        if o.get("type") == "LIMIT": types.add("LIMIT")
    # algo (conditional) orders
    try:
        p2 = ex._sign_params({"symbol": sym})
        r2 = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/openAlgoOrders", params=p2, headers=ex._headers())
        r2.raise_for_status()
        for o in r2.json().get("orders", r2.json()) if isinstance(r2.json(), dict) else r2.json():
            if "STOP" in str(o.get("orderType") or o.get("type") or ""): types.add("STOP")
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

    # LIVE: indefinite rolling loop
    tick = 0
    while True:
        try:
            open_now = open_syms(ex, universe)
            flog(f"--- TICK {tick} | posiciones {len(open_now)}/{MAX_POS}: "
                 f"{', '.join(s.replace('USDT','') for s in open_now) or '—'} ---")
            # 1) manage/protect existing
            for s, info in list(open_now.items()):
                try: manage(ex, s, info["amt"], st, dry=False)
                except Exception as e: flog(f"  {s}: manage ERROR ({e})")
            # 2) clear state for symbols no longer open; cancel stray orders
            for s in list(st.keys()):
                if s not in open_now:
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
