#!/usr/bin/env python3
"""
01_fetch_data.py -- Stage 1+2 of the martingale-robustness pipeline. Builds a volume-tiered
universe of REAL Binance USDT-M perpetuals and fetches REAL 1m klines for the last N_DAYS for
every symbol in it. No synthetic/mock data anywhere -- every number here comes from a live
fapi.binance.com response.

UNIVERSE / TIERS: to actually test the user's hypothesis ("pares con mayor volumen tal vez sean
mejores para esta estrategia") we need real separation between tiers, not three groups that are
all secretly "high liquidity". Ranked by live 24h quoteVolume among ASCII, TRADING, PERPETUAL
USDT-M symbols:
  TIER_HIGH = ranks 1-12   (the most liquid majors/large-caps)
  TIER_MID  = ranks 31-42  (real mid-tier alts)
  TIER_LOW  = the lowest-ranked symbols that still clear MIN_VOL_FLOOR_USD (a basic tradability
              floor -- without this, "low volume" would include near-dead/about-to-delist
              symbols, which isn't a fair test of "lower volume but still tradable")
Depth(3%) is also fetched for every tiered symbol (same method as backtest_bollinger_5m.py's
depth_notional_3pct) purely for honest reporting -- it does not gate selection here since the tier
ranking is volume-based, not depth-based (that's a distinct axis worth showing, not conflating).

DATA WINDOW: N_DAYS of 1m klines, anchored to the most recent CLOSED candle on the exchange (not
local clock), so every symbol covers the identical calendar window -- required for a coherent
in-sample/out-of-sample split by calendar date across the whole universe (done downstream in
02_sweep.py, not here). Paginated at 1500 candles/request (Binance's per-call max), cached to disk
under cache/klines_<SYMBOL>.json so a re-run (e.g. after adding a symbol) doesn't re-fetch what's
already there.
"""
import asyncio
import json
import os

import httpx

from lib import get_json, log, ts_str, cache_load, cache_save, OUTPUT_DIR

N_DAYS = 30
TIER_HIGH_RANKS = (0, 12)     # python slice, 0-indexed, exclusive end
TIER_MID_RANKS = (30, 42)
MIN_VOL_FLOOR_USD = 2_000_000.0  # tradability floor for the "low volume" tier
TIER_LOW_COUNT = 12
KLINE_LIMIT = 1500
WINDOW_MS = N_DAYS * 24 * 60 * 60 * 1000
SEM_LIMIT = 6


async def build_tiered_universe(client):
    ex = await get_json(client, "/fapi/v1/exchangeInfo")
    perp_usdt = {
        s["symbol"] for s in ex["symbols"]
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
        and s.get("contractType") == "PERPETUAL" and s["symbol"].isascii()
    }
    tk = await get_json(client, "/fapi/v1/ticker/24hr")
    tickers = {
        t["symbol"]: {"quoteVolume": float(t["quoteVolume"]), "priceChangePercent": float(t["priceChangePercent"])}
        for t in tk if t["symbol"] in perp_usdt
    }
    ranked = sorted(tickers.items(), key=lambda kv: -kv[1]["quoteVolume"])
    log(f"universe: {len(ranked)} ASCII TRADING USDT-M perpetuals with live 24h ticker data")

    high = [s for s, _ in ranked[TIER_HIGH_RANKS[0]:TIER_HIGH_RANKS[1]]]
    mid = [s for s, _ in ranked[TIER_MID_RANKS[0]:TIER_MID_RANKS[1]]]
    below_floor = [(s, v) for s, v in ranked if v["quoteVolume"] >= MIN_VOL_FLOOR_USD]
    low = [s for s, _ in below_floor[-TIER_LOW_COUNT:]] if len(below_floor) >= TIER_LOW_COUNT else []

    log(f"TIER_HIGH (ranks {TIER_HIGH_RANKS[0]+1}-{TIER_HIGH_RANKS[1]}): {high}")
    log(f"TIER_MID  (ranks {TIER_MID_RANKS[0]+1}-{TIER_MID_RANKS[1]}): {mid}")
    log(f"TIER_LOW  (lowest-vol symbols still >= ${MIN_VOL_FLOOR_USD:,.0f} 24h vol, n={len(low)}): {low}")

    return {"high": high, "mid": mid, "low": low}, tickers, ranked


async def depth_notional_3pct(client, symbol, sem):
    async with sem:
        try:
            d = await get_json(client, "/fapi/v1/depth", {"symbol": symbol, "limit": 100})
        except Exception as e:
            log(f"  depth fetch failed {symbol}: {e}")
            return symbol, 0.0
        finally:
            await asyncio.sleep(0.05)
    bids, asks = d.get("bids", []), d.get("asks", [])
    if not bids or not asks:
        return symbol, 0.0
    mid = (float(bids[0][0]) + float(asks[0][0])) / 2.0
    lo, hi = mid * 0.97, mid * 1.03
    notional = (sum(float(p) * float(q) for p, q in bids if float(p) >= lo)
                + sum(float(p) * float(q) for p, q in asks if float(p) <= hi))
    return symbol, notional


async def fetch_1m_range(client, symbol, start_ms, end_ms, sem):
    cache_name = f"klines_{symbol}_{start_ms}_{end_ms}.json"
    cached = cache_load(cache_name)
    if cached is not None:
        log(f"  {symbol}: {len(cached)} candles (cached)")
        return cached
    out = []
    cursor = start_ms
    async with sem:
        while cursor < end_ms:
            r = await get_json(client, "/fapi/v1/klines", {
                "symbol": symbol, "interval": "1m", "startTime": cursor, "endTime": end_ms, "limit": KLINE_LIMIT,
            })
            await asyncio.sleep(0.08)
            if not r:
                break
            out.extend(r)
            last_close = int(r[-1][6])
            if last_close <= cursor or len(r) < 2:
                break
            cursor = last_close + 1
    klines = [{
        "open_time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
        "low": float(k[3]), "close": float(k[4]), "close_time": int(k[6]),
    } for k in out]
    cache_save(cache_name, klines)
    log(f"  {symbol}: {len(klines)} candles fetched")
    return klines


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    async with httpx.AsyncClient(timeout=30.0) as client:
        tiers, tickers, ranked = await build_tiered_universe(client)
        all_symbols = sorted(set(tiers["high"]) | set(tiers["mid"]) | set(tiers["low"]))
        log(f"total distinct symbols to fetch: {len(all_symbols)}")

        sem_depth = asyncio.Semaphore(6)
        depth_results = dict(await asyncio.gather(*[depth_notional_3pct(client, s, sem_depth) for s in all_symbols]))

        latest = await get_json(client, "/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1m", "limit": 1})
        end_ms = int(latest[0][6])
        start_ms = end_ms - WINDOW_MS
        log(f"data window (anchored to exchange's latest closed 1m candle): "
            f"{ts_str(start_ms)} -> {ts_str(end_ms)} UTC ({N_DAYS} days)")

        sem_kl = asyncio.Semaphore(SEM_LIMIT)
        results = await asyncio.gather(*[
            fetch_1m_range(client, s, start_ms, end_ms, sem_kl) for s in all_symbols
        ])
        counts = {s: len(k) for s, k in zip(all_symbols, results)}

    meta = {
        "n_days": N_DAYS, "start_ms": start_ms, "end_ms": end_ms,
        "start_str": ts_str(start_ms), "end_str": ts_str(end_ms),
        "tiers": tiers, "candle_counts": counts,
        "tier_high_ranks": list(TIER_HIGH_RANKS), "tier_mid_ranks": list(TIER_MID_RANKS),
        "min_vol_floor_usd": MIN_VOL_FLOOR_USD,
        "tickers": {s: tickers[s] for s in all_symbols if s in tickers},
        "depth_3pct_usd": {s: round(depth_results.get(s, 0.0), 2) for s in all_symbols},
    }
    with open(os.path.join(OUTPUT_DIR, "universe_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    log("=" * 78)
    log(f"DONE. {len(all_symbols)} symbols, window {meta['start_str']} -> {meta['end_str']} UTC")
    for tier_name, syms in tiers.items():
        vols = [tickers[s]["quoteVolume"] for s in syms if s in tickers]
        deps = [depth_results.get(s, 0.0) for s in syms]
        log(f"  {tier_name:5s} n={len(syms):2d}  vol range=${min(vols):,.0f}-${max(vols):,.0f}  "
            f"depth3% range=${min(deps):,.0f}-${max(deps):,.0f}")
    log(f"Metadata written to {os.path.join(OUTPUT_DIR, 'universe_meta.json')}")


if __name__ == "__main__":
    asyncio.run(main())
