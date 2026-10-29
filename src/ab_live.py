"""A/B en vivo: ejecutor parametrizado por variante (env). Reusa OrderExecutor.

Diferencias vs forward_test.py:
  - Lee COLATERAL a nivel cuenta (/fapi/v2/account availableBalance) -> funciona con
    USDC en Multi-Assets Mode (no depende del saldo del activo "USDT").
  - Filtro de tendencia SMA (diario) opcional: solo agrega si precio >= SMA(SMA_DAYS).
  - Cap de adds por par (MAX_ADDS) y tope de presupuesto (BUDGET_USD) para paridad A/B.
  - Todo lo demás igual: $LOT cada 30min, TP +TP% maker, sin SL, cierre h24, cross,
    restart-safe (adopta posiciones, START_EPOCH por env).

Variantes del A/B:
  A baseline : SMA_DAYS=0  MAX_ADDS=41
  C robusta  : SMA_DAYS=30 MAX_ADDS=20

Config por env: VARIANT, LOT, LEVERAGE, TP_PCT, MAX_ADDS, SMA_DAYS, STOP_ADD_H, CLOSE_H,
BUDGET_USD, FORWARD_PAIRS (csv), START_EPOCH. Modo: sin --live = DRY_RUN (una pasada).
"""
import sys, os, time, json, argparse, urllib.request
from datetime import datetime, timezone

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC); os.chdir(SRC)
from order_executor import OrderExecutor
from utils import round_down
import config as _cfg

VARIANT = os.environ.get("VARIANT", "A")
LOT_USD = float(os.environ.get("LOT", "1"))
LEVERAGE = int(os.environ.get("LEVERAGE", "10"))
TP_PCT = float(os.environ.get("TP_PCT", "0.04"))
MAX_ADDS = int(os.environ.get("MAX_ADDS", "41"))
SMA_DAYS = int(os.environ.get("SMA_DAYS", "0"))        # 0 = sin filtro
STOP_ADDING_H = int(os.environ.get("STOP_ADD_H", "20"))
CLOSE_ALL_H = int(os.environ.get("CLOSE_H", "24"))
BUDGET_USD = float(os.environ.get("BUDGET_USD", "25"))
INTERVAL_MIN = 30
MAX_NOTIONAL = BUDGET_USD * LEVERAGE                   # tope de nocional total (paridad)
START_EPOCH = float(os.environ.get("START_EPOCH", "0")) or None
ROLLING = os.environ.get("ROLLING", "0") == "1"                # True = cicla sin fin hasta un stop
INITIAL_EQUITY = float(os.environ.get("INITIAL_EQUITY", "0"))  # baseline $ del stop (fijo por env -> restart-safe)
STOP_HIGH_MULT = float(os.environ.get("STOP_HIGH_MULT", "0"))  # 2.0 = frena al DOBLAR; 0 = off
STOP_LOW_MULT = float(os.environ.get("STOP_LOW_MULT", "0"))    # 0.10 = frena si cae a 10% (~arruinado); 0 = off
MIN_COINS = int(os.environ.get("MIN_COINS", "5"))              # piso de diversificacion: SIEMPRE >= este nro de monedas
PER_COIN_CAP = float(os.environ.get("PER_COIN_CAP", "0")) or (MAX_NOTIONAL / max(1, MIN_COINS))  # tope nocional por moneda

DEFAULT_PAIRS = ["SOMIUSDT","FLUXUSDT","DUSKUSDT","WALUSDT","AVNTUSDT","NIGHTUSDT","CHRUSDT","DEEPUSDT"]
_env_pairs = os.environ.get("FORWARD_PAIRS", "").strip()
PAIRS = [p.strip() for p in _env_pairs.split(",") if p.strip()] if _env_pairs else DEFAULT_PAIRS

LOGDIR = os.path.join(SRC, "..", "binance_usdt_futures", "output")
os.makedirs(LOGDIR, exist_ok=True)
LOGFILE = os.path.join(LOGDIR, f"ab_{VARIANT}_{datetime.now().strftime('%Y%m%d_%H%M')}.log")
_sma_cache = {}


def flog(msg):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC [{VARIANT}] | {msg}"
    print(line, flush=True)
    with open(LOGFILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def account_available(ex):
    """Colateral usable a nivel cuenta (USDT-equiv; sirve con USDC en multi-asset)."""
    p = ex._sign_params({})
    r = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v2/account", params=p, headers=ex._headers())
    r.raise_for_status()
    return float(r.json()["availableBalance"])


def equity(ex):
    """Equity TOTAL (wallet + PnL no realizado), USDT-equiv. Base del stop doblar/arruinar."""
    p = ex._sign_params({})
    r = ex.client.get(f"{_cfg.BINANCE_BASE_URL}/fapi/v2/account", params=p, headers=ex._headers())
    r.raise_for_status()
    return float(r.json()["totalMarginBalance"])


def stop_reason(eq):
    """'DOBLADO' si eq>=high, 'ARRUINADO' si eq<=low, sino None. Requiere INITIAL_EQUITY>0."""
    if INITIAL_EQUITY <= 0:
        return None
    if STOP_HIGH_MULT and eq >= STOP_HIGH_MULT * INITIAL_EQUITY:
        return "DOBLADO"
    if STOP_LOW_MULT and eq <= STOP_LOW_MULT * INITIAL_EQUITY:
        return "ARRUINADO"
    return None


def sma_value(sym):
    """SMA diaria de SMA_DAYS (cacheada 1h). None si SMA_DAYS<=0 (sin filtro)."""
    if SMA_DAYS <= 0:
        return None
    now = time.time()
    c = _sma_cache.get(sym)
    if not c or now - c[1] > 3600:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1d&limit={SMA_DAYS+1}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            kl = json.loads(resp.read())
        closes = [float(k[4]) for k in kl[:-1]]        # cierres de días completos
        sma = sum(closes[-SMA_DAYS:]) / min(SMA_DAYS, len(closes))
        _sma_cache[sym] = (sma, now)
    return _sma_cache[sym][0]


def select_coins(ex, syms):
    """DIVERSIFICA: elige >= MIN_COINS monedas por tick. Rankea por fuerza de tendencia
    (precio/SMA). Prefiere las que estan SOBRE su SMA (ratio>=1); si en tendencia hay
    menos de MIN_COINS, COMPLETA con las 'menos malas' (top ratio) hasta el piso, para
    nunca concentrarse en 1-2 nombres. Devuelve [(sym, price, ratio)] ordenada por ratio desc.
    SMA_DAYS<=0 -> sin filtro, rankea todo (ratio 1.0)."""
    ranked = []
    for s in syms:
        try:
            price = ex.get_current_price(s)
        except Exception as e:
            flog(f"  {s}: sin precio ({e}) -> fuera del ranking"); continue
        sma = sma_value(s)
        ratio = (price / sma) if sma else 1.0
        ranked.append((s, price, ratio))
    ranked.sort(key=lambda x: x[2], reverse=True)
    if SMA_DAYS <= 0:
        return ranked
    passers = [r for r in ranked if r[2] >= 1.0]
    if len(passers) >= MIN_COINS:
        return passers                               # bastantes en tendencia: usa todas
    return ranked[:min(MIN_COINS, len(ranked))]      # piso: top MIN_COINS aunque esten bajo SMA


def total_notional(ex, syms):
    try:
        pos = ex.get_all_open_positions()
    except Exception:
        return 0.0
    return sum(abs(float(p["positionAmt"])) * float(p["markPrice"])
               for p in pos if p["symbol"] in syms)


def place_tp_limit(ex, symbol, qty, tp_price):
    info = ex.symbol_info_cache[symbol]
    tp_r = ex._round_to_tick_size(tp_price, info["tickSize"])
    qty_r = ex._round_to_step_size(qty, info["stepSize"])
    params = {"symbol": symbol, "side": "SELL", "positionSide": "BOTH", "type": "LIMIT",
              "price": f"{tp_r:.{info['pricePrecision']}f}", "quantity": f"{qty_r:.{info['quantityPrecision']}f}",
              "timeInForce": "GTC", "reduceOnly": "true"}
    params = ex._sign_params(params)
    r = ex.client.post(f"{_cfg.BINANCE_BASE_URL}/fapi/v1/order", params=params, headers=ex._headers())
    r.raise_for_status()
    return f"{tp_r:.{info['pricePrecision']}f}"


def setup(ex, dry):
    flog(f"SETUP {len(PAIRS)} pares | {LEVERAGE}x CROSSED | SMA{SMA_DAYS} rank | minCoins {MIN_COINS} | "
         f"cap ${PER_COIN_CAP:.0f}/moneda | lote ${LOT_USD} | budget ${BUDGET_USD} (notl max ${MAX_NOTIONAL:.0f})")
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


def buy_tick(ex, syms, dry, tick):
    flog(f"--- TICK {tick} ---")
    selected = select_coins(ex, syms)
    flog(f"  seleccion {len(selected)}/{len(syms)} (piso {MIN_COINS}, cap ${PER_COIN_CAP:.0f}/moneda): "
         + ", ".join(f"{s.replace('USDT','')}@{r:.3f}" for s, _, r in selected))
    if dry:
        for s, price, ratio in selected:
            info = ex.symbol_info_cache[s]
            qty = round_down(LOT_USD / price, info["quantityPrecision"])
            tag = "sobreSMA" if ratio >= 1 else "bajoSMA(piso)"
            flog(f"  [DRY] {s}: BUY ${LOT_USD}={qty}@{price:.6f} r={ratio:.3f} {tag} -> TP {price*(1+TP_PCT):.6f}")
        return
    notl_map = {}
    try:
        for p in ex.get_all_open_positions():
            if p["symbol"] in syms:
                notl_map[p["symbol"]] = abs(float(p["positionAmt"])) * float(p["markPrice"])
    except Exception:
        pass
    notl_total = sum(notl_map.values())
    for s, price, ratio in selected:
        try:
            coin_notl = notl_map.get(s, 0.0)
            if coin_notl + LOT_USD > PER_COIN_CAP + 1e-6:
                flog(f"  {s}: SKIP (cap/moneda ${coin_notl:.0f}+{LOT_USD}>{PER_COIN_CAP:.0f})"); continue
            if notl_total + LOT_USD > MAX_NOTIONAL + 1e-6:
                flog(f"  {s}: SKIP (budget total ${notl_total:.0f}>{MAX_NOTIONAL:.0f})"); continue
            avail = account_available(ex)
            if avail < LOT_USD / LEVERAGE + 0.5:
                flog(f"  {s}: SKIP (colateral libre ${avail:.2f})"); continue
            ex.place_market_order(s, "BUY", LOT_USD)
            pos = ex.get_position(s)
            amt = abs(float(pos["positionAmt"])); avg = float(pos["entryPrice"]) or price
            ex.cancel_all_orders(s)
            tp = place_tp_limit(ex, s, amt, avg * (1 + TP_PCT))
            notl_total += LOT_USD; notl_map[s] = coin_notl + LOT_USD
            flog(f"  {s}: BUY ${LOT_USD} r={ratio:.3f} | pos={amt} avg={avg:.6f} | TP {tp}")
        except Exception as e:
            flog(f"  {s}: ERROR compra ({e})")


def adopt(ex, syms):
    try: pos = ex.get_all_open_positions()
    except Exception as e:
        flog(f"adopt: no pude leer posiciones ({e})"); return
    n = 0
    for p in pos:
        s = p["symbol"]; amt = float(p["positionAmt"])
        if s not in syms or amt <= 0: continue
        avg = float(p.get("entryPrice", 0)) or ex.get_current_price(s)
        try:
            ex.cancel_all_orders(s); place_tp_limit(ex, s, abs(amt), avg * (1 + TP_PCT)); n += 1
        except Exception as e:
            flog(f"  {s}: adopt TP fallo ({e})")
    flog(f"adopt: {n} posiciones adoptadas")


def close_all(ex, syms):
    flog("=== CIERRE h%d ===" % CLOSE_ALL_H)
    try: pos = ex.get_all_open_positions()
    except Exception as e:
        flog(f"cierre: no pude leer ({e})"); return
    for p in pos:
        s = p["symbol"]; amt = float(p["positionAmt"])
        if s not in syms or amt == 0: continue
        try:
            ex.cancel_all_orders(s)
            ex.close_position_market(s, "LONG" if amt > 0 else "SHORT", abs(amt))
            flog(f"  {s}: cerrado {abs(amt)}")
        except Exception as e:
            flog(f"  {s}: ERROR cierre ({e})")


def run_rolling(syms, epoch0, buy_fn, close_fn, equity_fn, clock=time.time, sleep=time.sleep):
    """Cicla sin fin (fase por reloj -> restart-safe) hasta tocar un stop de equity.
    Cierra todo al cruzar cada frontera de ciclo (h{CLOSE_ALL_H}) y arranca acumulacion nueva.
    Chequea el stop ANTES de comprar en cada tick. Devuelve el motivo ('DOBLADO'/'ARRUINADO')
    tras cerrar todo. Inyectables buy_fn(tick)/close_fn()/equity_fn()/clock()/sleep() p/ testear."""
    cycle_s = CLOSE_ALL_H * 3600
    stop_add_s = STOP_ADDING_H * 3600
    cur_cycle = int((clock() - epoch0) // cycle_s)   # ciclo actual al arrancar (no re-cierra lo adoptado)
    tick = 0
    while True:
        now = clock()
        phase = (now - epoch0) % cycle_s
        cyc = int((now - epoch0) // cycle_s)
        eq = equity_fn()
        why = stop_reason(eq)
        if why:
            xmult = f" x{eq/INITIAL_EQUITY:.2f}" if INITIAL_EQUITY > 0 else ""
            flog(f"*** STOP {why}: equity ${eq:.2f}{xmult} (init ${INITIAL_EQUITY:.2f}) -> cierro TODO ***")
            close_fn()
            return why
        if cyc != cur_cycle:
            flog(f"--- fin de ciclo {cur_cycle}->{cyc} (h{CLOSE_ALL_H}): cierro todo y reinicio acumulacion ---")
            close_fn()
            cur_cycle = cyc
        xmult = f" x{eq/INITIAL_EQUITY:.2f}" if INITIAL_EQUITY > 0 else ""
        flog(f"[ciclo {cyc} fase {phase/3600:.1f}h | equity ${eq:.2f}{xmult}]")
        if phase <= stop_add_s:
            buy_fn(tick)
        else:
            flog(f"--- tick {tick}: solo espera TP (fase {phase/3600:.1f}h > h{STOP_ADDING_H}) ---")
        tick += 1
        sleep(INTERVAL_MIN * 60)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--live", action="store_true"); args = ap.parse_args()
    dry = not args.live
    flog("#" * 60)
    flog(f"A/B LIVE variante {VARIANT} | modo={'LIVE' if not dry else 'DRY'} | "
         f"${LOT_USD}/30min | {LEVERAGE}x | SMA{SMA_DAYS} rank | minCoins {MIN_COINS} | "
         f"cap ${PER_COIN_CAP:.0f}/moneda | TP+{TP_PCT*100:.0f}% | h{CLOSE_ALL_H}")
    ex = OrderExecutor()
    try:
        avail = account_available(ex)
        openpos = ex.get_all_open_positions()
        flog(f"Colateral libre: ${avail:.2f} | posiciones previas: {len(openpos)}")
        syms = setup(ex, dry)
        if not syms: flog("sin pares. fin."); return
        if dry:
            buy_tick(ex, syms, True, 0)
            flog("[DRY] fin de pasada. live: ab_live.py --live"); return
        if openpos:
            flog("adoptando posiciones previas (restart-safe)"); adopt(ex, syms)
        start = START_EPOCH if START_EPOCH else time.time()
        flog(f"START_EPOCH={start:.0f} elapsed {(time.time()-start)/3600:.2f}h | ROLLING={ROLLING}")
        if ROLLING:
            if INITIAL_EQUITY > 0:
                flog(f"STOP equity: DOBLAR >= ${STOP_HIGH_MULT*INITIAL_EQUITY:.2f} | "
                     f"ARRUINAR <= ${STOP_LOW_MULT*INITIAL_EQUITY:.2f} (init ${INITIAL_EQUITY:.2f})")
            else:
                flog("AVISO: ROLLING sin INITIAL_EQUITY>0 -> correra sin stop (indefinido)")
            why = run_rolling(syms, start,
                              buy_fn=lambda t: buy_tick(ex, syms, False, t),
                              close_fn=lambda: close_all(ex, syms),
                              equity_fn=lambda: equity(ex))
            flog(f"=== {VARIANT} FRENADO ({why}) | equity final ${equity(ex):.2f} | OCIOSO (no opera mas) ===")
            while True:                                   # ocioso: NO salir (evita restart-loop/doble-trade)
                time.sleep(3600)
                try:
                    flog(f"HALTED ({why}). equity ${equity(ex):.2f}. (ocioso; borra el servicio cuando quieras)")
                except Exception:
                    pass
        else:
            stop_s = STOP_ADDING_H * 3600; close_s = CLOSE_ALL_H * 3600; tick = 0
            while True:
                el = time.time() - start
                if el >= close_s: break
                if el <= stop_s: buy_tick(ex, syms, False, tick)
                else: flog(f"--- TICK {tick}: espera TP (h{STOP_ADDING_H} superada) ---")
                tick += 1
                nxt = min(INTERVAL_MIN * 60, max(5, close_s - (time.time() - start)))
                flog(f"  durmiendo {nxt/60:.1f}min (elapsed {(time.time()-start)/3600:.2f}h)")
                time.sleep(nxt)
            close_all(ex, syms)
            flog(f"=== FIN variante {VARIANT} | colateral final ${account_available(ex):.2f} ===")
    finally:
        ex.close()


if __name__ == "__main__":
    main()
