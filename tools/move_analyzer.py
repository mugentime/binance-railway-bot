"""
10%+ Move Analyzer with ATR & Squeeze
======================================
Scans all USDT-M pairs for 10%+ price moves in the last 3 hours.
For each move found, outputs the precursor candle data including:
  - OHLCV
  - RSI, BB%B, Z-score
  - ATR (absolute + % of price)
  - Bollinger Squeeze (BB width / Keltner width)
  - Volume ratio

Usage:
  python tools/move_analyzer.py
  python tools/move_analyzer.py --hours 6        # lookback window
  python tools/move_analyzer.py --threshold 5    # lower move % threshold
  python tools/move_analyzer.py --candles 10     # precursor candles to show
  python tools/move_analyzer.py --export         # save CSV
"""

import requests
import numpy as np
import time
import argparse
import csv
import sys
from datetime import datetime, timezone

# ─── CONFIG ──────────────────────────────────────────────────────────────────

BINANCE_BASE = "https://fapi.binance.com"
KLINE_INTERVAL = "5m"          # 5-minute candles
PRECURSOR_CANDLES = 6          # candles before the move to display
LOOKBACK_EXTRA = 40            # extra candles for indicator warmup (ATR/BB/RSI need history)
RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 14
KELTNER_PERIOD = 20
KELTNER_ATR_MULT = 1.5
ZSCORE_PERIOD = 20

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_all_usdt_pairs():
    """Fetch all active USDT-M perpetual futures pairs."""
    r = requests.get(f"{BINANCE_BASE}/fapi/v1/exchangeInfo", timeout=10)
    r.raise_for_status()
    data = r.json()
    pairs = []
    for s in data["symbols"]:
        if (s["quoteAsset"] == "USDT"
            and s["contractType"] == "PERPETUAL"
            and s["status"] == "TRADING"):
            pairs.append(s["symbol"])
    return pairs


def get_klines(symbol, interval, limit):
    """Fetch klines from Binance Futures."""
    r = requests.get(f"{BINANCE_BASE}/fapi/v1/klines", params={
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }, timeout=10)
    r.raise_for_status()
    raw = r.json()
    candles = []
    for k in raw:
        candles.append({
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": int(k[6]),
            "quote_volume": float(k[7]),
        })
    return candles


def calc_rsi(closes, period=RSI_PERIOD):
    """Wilder's RSI."""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    rsis = [np.nan] * period
    if avg_loss == 0:
        rsis.append(100.0)
    else:
        rsis.append(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsis.append(100.0)
        else:
            rsis.append(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))

    return rsis  # length = len(closes)


def calc_bb(closes, period=BB_PERIOD, std_mult=BB_STD):
    """Bollinger Bands → returns (upper, middle, lower, pct_b, bandwidth)."""
    n = len(closes)
    upper = [np.nan] * n
    middle = [np.nan] * n
    lower = [np.nan] * n
    pct_b = [np.nan] * n
    bandwidth = [np.nan] * n

    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        sma = np.mean(window)
        std = np.std(window, ddof=0)
        u = sma + std_mult * std
        l = sma - std_mult * std
        middle[i] = sma
        upper[i] = u
        lower[i] = l
        if u - l > 0:
            pct_b[i] = (closes[i] - l) / (u - l)
            bandwidth[i] = (u - l) / sma
        else:
            pct_b[i] = 0.5
            bandwidth[i] = 0.0

    return upper, middle, lower, pct_b, bandwidth


def calc_atr(highs, lows, closes, period=ATR_PERIOD):
    """Average True Range → returns (atr_values, atr_pct_of_price)."""
    n = len(closes)
    tr = [np.nan] * n
    atr = [np.nan] * n
    atr_pct = [np.nan] * n

    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Wilder's smoothed ATR
    if n >= period + 1:
        atr[period] = np.mean([t for t in tr[1:period + 1] if t is not np.nan])
        if closes[period] > 0:
            atr_pct[period] = atr[period] / closes[period] * 100

        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
            if closes[i] > 0:
                atr_pct[i] = atr[i] / closes[i] * 100

    return atr, atr_pct


def calc_keltner_width(closes, atr_values, period=KELTNER_PERIOD, mult=KELTNER_ATR_MULT):
    """Keltner Channel width = 2 * mult * ATR / EMA."""
    n = len(closes)
    ema = [np.nan] * n
    kc_width = [np.nan] * n
    k = 2.0 / (period + 1)

    # seed EMA
    start = None
    for i in range(n):
        if not np.isnan(closes[i]):
            if start is None:
                start = i
                ema[i] = closes[i]
            else:
                ema[i] = closes[i] * k + ema[i - 1] * (1 - k)

            if atr_values[i] is not None and not np.isnan(atr_values[i]) and ema[i] > 0:
                kc_width[i] = (2 * mult * atr_values[i]) / ema[i]

    return kc_width


def calc_squeeze(bb_bandwidth, kc_width):
    """
    Squeeze indicator:
      squeeze_ratio = BB_width / KC_width
      < 1.0 = squeeze ON (BB inside KC → low volatility, potential breakout)
      > 1.0 = squeeze OFF (BB outside KC → volatility expanding)
    """
    n = len(bb_bandwidth)
    squeeze = [np.nan] * n
    for i in range(n):
        bw = bb_bandwidth[i]
        kw = kc_width[i]
        if bw is not None and kw is not None and not np.isnan(bw) and not np.isnan(kw) and kw > 0:
            squeeze[i] = bw / kw
    return squeeze


def calc_zscore(closes, period=ZSCORE_PERIOD):
    """Z-score of price relative to rolling mean/std."""
    n = len(closes)
    zs = [np.nan] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        mu = np.mean(window)
        sigma = np.std(window, ddof=0)
        if sigma > 0:
            zs[i] = (closes[i] - mu) / sigma
        else:
            zs[i] = 0.0
    return zs


def calc_volume_ratio(volumes, period=20):
    """Current volume / SMA(volume, period)."""
    n = len(volumes)
    vr = [np.nan] * n
    for i in range(period - 1, n):
        avg = np.mean(volumes[i - period + 1:i + 1])
        if avg > 0:
            vr[i] = volumes[i] / avg
        else:
            vr[i] = 0.0
    return vr


def ts_str(epoch_ms):
    """Convert epoch ms to readable UTC string."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ─── MAIN ANALYSIS ──────────────────────────────────────────────────────────

def analyze_pair(symbol, lookback_candles, move_threshold_pct, precursor_count):
    """
    Check if symbol had any move >= threshold in the lookback window.
    Returns list of detected moves with precursor data.
    """
    total_candles = lookback_candles + LOOKBACK_EXTRA + precursor_count
    try:
        candles = get_klines(symbol, KLINE_INTERVAL, min(total_candles, 1500))
    except Exception as e:
        return []

    if len(candles) < LOOKBACK_EXTRA + precursor_count + 5:
        return []

    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])

    # Calculate all indicators
    rsi = calc_rsi(closes)
    bb_upper, bb_mid, bb_lower, bb_pctb, bb_bw = calc_bb(closes)
    atr, atr_pct = calc_atr(highs, lows, closes)
    kc_width = calc_keltner_width(closes, atr)
    squeeze = calc_squeeze(bb_bw, kc_width)
    zscore = calc_zscore(closes)
    vol_ratio = calc_volume_ratio(volumes)

    # Scan the lookback window for 10%+ moves
    analysis_start = len(candles) - lookback_candles
    moves = []

    i = analysis_start
    while i < len(candles):
        # Look forward from candle i for a move >= threshold
        for j in range(i + 1, len(candles)):
            pct_change = (candles[j]["close"] - candles[i]["close"]) / candles[i]["close"] * 100
            if abs(pct_change) >= move_threshold_pct:
                direction = "UP" if pct_change > 0 else "DOWN"

                # Gather precursor candle data
                pre_start = max(0, i - precursor_count)
                precursors = []
                for p in range(pre_start, i + 1):
                    sq_val = squeeze[p] if p < len(squeeze) else np.nan
                    sq_status = "N/A"
                    if sq_val is not None and not np.isnan(sq_val):
                        if sq_val < 0.8:
                            sq_status = "TIGHT"
                        elif sq_val < 1.0:
                            sq_status = "ON"
                        else:
                            sq_status = "OFF"

                    precursors.append({
                        "time": ts_str(candles[p]["open_time"]),
                        "open": candles[p]["open"],
                        "high": candles[p]["high"],
                        "low": candles[p]["low"],
                        "close": candles[p]["close"],
                        "volume": candles[p]["volume"],
                        "rsi": rsi[p] if p < len(rsi) else np.nan,
                        "bb_pctb": bb_pctb[p] if p < len(bb_pctb) else np.nan,
                        "zscore": zscore[p] if p < len(zscore) else np.nan,
                        "vol_ratio": vol_ratio[p] if p < len(vol_ratio) else np.nan,
                        "atr": atr[p] if p < len(atr) else np.nan,
                        "atr_pct": atr_pct[p] if p < len(atr_pct) else np.nan,
                        "squeeze_ratio": sq_val,
                        "squeeze_status": sq_status,
                        "bb_bandwidth": bb_bw[p] if p < len(bb_bw) else np.nan,
                    })

                moves.append({
                    "symbol": symbol,
                    "direction": direction,
                    "pct_change": pct_change,
                    "start_price": candles[i]["close"],
                    "end_price": candles[j]["close"],
                    "start_time": ts_str(candles[i]["open_time"]),
                    "end_time": ts_str(candles[j]["open_time"]),
                    "candles_duration": j - i,
                    "precursors": precursors,
                })
                i = j  # skip past this move
                break
        else:
            i += 1
            continue
        i += 1

    return moves


def print_move(move, idx):
    """Pretty-print a single move with precursor data."""
    print(f"\n{'='*120}")
    print(f"  MOVE #{idx}: {move['symbol']}  {move['direction']}  {move['pct_change']:+.2f}%")
    print(f"  {move['start_price']:.6g} → {move['end_price']:.6g}  |  {move['start_time']} → {move['end_time']}  |  {move['candles_duration']} candles")
    print(f"{'='*120}")

    # Header
    print(f"  {'Time':<20} {'O':>10} {'H':>10} {'L':>10} {'C':>10} {'Vol':>12}"
          f" {'RSI':>6} {'BB%B':>6} {'Z':>6} {'VolR':>6}"
          f" {'ATR':>10} {'ATR%':>6} {'SqzR':>6} {'Sqz':>6} {'BBW%':>7}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*12}"
          f" {'-'*6} {'-'*6} {'-'*6} {'-'*6}"
          f" {'-'*10} {'-'*6} {'-'*6} {'-'*6} {'-'*7}")

    for j, p in enumerate(move["precursors"]):
        label = "→MOVE" if j == len(move["precursors"]) - 1 else f"  T-{len(move['precursors'])-1-j}"

        def fmt(v, decimals=2):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return "  -"
            return f"{v:.{decimals}f}"

        # Auto-detect price decimals
        price = p["close"]
        if price < 0.001:
            pd = 8
        elif price < 0.1:
            pd = 6
        elif price < 10:
            pd = 4
        else:
            pd = 2

        print(f"  {p['time']:<20}"
              f" {p['open']:>{10}.{pd}f}"
              f" {p['high']:>{10}.{pd}f}"
              f" {p['low']:>{10}.{pd}f}"
              f" {p['close']:>{10}.{pd}f}"
              f" {p['volume']:>12,.0f}"
              f" {fmt(p['rsi']):>6}"
              f" {fmt(p['bb_pctb']):>6}"
              f" {fmt(p['zscore']):>6}"
              f" {fmt(p['vol_ratio']):>6}"
              f" {fmt(p['atr'], 6 if price < 1 else 2):>10}"
              f" {fmt(p['atr_pct']):>6}"
              f" {fmt(p['squeeze_ratio']):>6}"
              f" {p['squeeze_status']:>6}"
              f" {fmt(p['bb_bandwidth'], 4):>7}"
              f"  {label}")

    # Summary stats from the last precursor candle (right before the move)
    last = move["precursors"][-1]
    print(f"\n  PRE-MOVE SNAPSHOT:")
    rsi_v = last['rsi']
    bb_v = last['bb_pctb']
    zs_v = last['zscore']
    atr_v = last['atr_pct']
    sq_v = last['squeeze_ratio']
    vr_v = last['vol_ratio']

    conditions = []
    if rsi_v is not None and not np.isnan(rsi_v):
        if rsi_v > 60:
            conditions.append(f"RSI overbought ({rsi_v:.1f})")
        elif rsi_v < 40:
            conditions.append(f"RSI oversold ({rsi_v:.1f})")
        else:
            conditions.append(f"RSI neutral ({rsi_v:.1f})")

    if sq_v is not None and not np.isnan(sq_v):
        if sq_v < 0.8:
            conditions.append(f"TIGHT squeeze ({sq_v:.2f}) — breakout imminent")
        elif sq_v < 1.0:
            conditions.append(f"Squeeze ON ({sq_v:.2f})")
        else:
            conditions.append(f"Squeeze OFF ({sq_v:.2f}) — vol expanding")

    if atr_v is not None and not np.isnan(atr_v):
        if atr_v > 3.0:
            conditions.append(f"HIGH volatility ATR={atr_v:.2f}%")
        elif atr_v < 1.0:
            conditions.append(f"LOW volatility ATR={atr_v:.2f}%")
        else:
            conditions.append(f"ATR={atr_v:.2f}%")

    if vr_v is not None and not np.isnan(vr_v):
        conditions.append(f"Volume {vr_v:.2f}x avg")

    for c in conditions:
        print(f"    • {c}")


def export_csv(all_moves, filename):
    """Export all precursor data to CSV for further analysis."""
    rows = []
    for move in all_moves:
        for j, p in enumerate(move["precursors"]):
            rows.append({
                "symbol": move["symbol"],
                "direction": move["direction"],
                "move_pct": move["pct_change"],
                "move_start": move["start_time"],
                "move_end": move["end_time"],
                "move_duration_candles": move["candles_duration"],
                "candle_offset": -(len(move["precursors"]) - 1 - j),
                "time": p["time"],
                "open": p["open"],
                "high": p["high"],
                "low": p["low"],
                "close": p["close"],
                "volume": p["volume"],
                "rsi": p["rsi"],
                "bb_pctb": p["bb_pctb"],
                "zscore": p["zscore"],
                "vol_ratio": p["vol_ratio"],
                "atr": p["atr"],
                "atr_pct": p["atr_pct"],
                "squeeze_ratio": p["squeeze_ratio"],
                "squeeze_status": p["squeeze_status"],
                "bb_bandwidth": p["bb_bandwidth"],
            })

    if rows:
        with open(filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n✅ Exported {len(rows)} rows to {filename}")


def main():
    parser = argparse.ArgumentParser(description="10%+ Move Analyzer with ATR & Squeeze")
    parser.add_argument("--hours", type=float, default=3, help="Lookback window in hours (default: 3)")
    parser.add_argument("--threshold", type=float, default=10, help="Move threshold %% (default: 10)")
    parser.add_argument("--candles", type=int, default=6, help="Precursor candles to show (default: 6)")
    parser.add_argument("--export", action="store_true", help="Export CSV")
    parser.add_argument("--csv-file", type=str, default="move_analysis.csv", help="CSV filename")
    args = parser.parse_args()

    lookback_candles = int(args.hours * 60 / 5)  # 5-min candles

    print(f"╔{'═'*118}╗")
    print(f"║  10%+ MOVE ANALYZER — ATR & Squeeze Edition{' '*73}║")
    print(f"║  Lookback: {args.hours}h ({lookback_candles} candles)  |  Threshold: {args.threshold}%  |  Precursors: {args.candles} candles{' '*(118 - 75 - len(str(args.hours)) - len(str(args.threshold)) - len(str(args.candles)))}║")
    print(f"║  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}{' '*(110 - len(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')))}║")
    print(f"╚{'═'*118}╝")

    print(f"\nFetching USDT-M pairs...", end=" ", flush=True)
    pairs = get_all_usdt_pairs()
    print(f"{len(pairs)} pairs found.")

    all_moves = []
    scanned = 0
    errors = 0

    print(f"Scanning for {args.threshold}%+ moves in last {args.hours}h...\n")

    for i, symbol in enumerate(pairs):
        if (i + 1) % 50 == 0:
            print(f"  ... scanned {i+1}/{len(pairs)}", flush=True)

        try:
            moves = analyze_pair(symbol, lookback_candles, args.threshold, args.candles)
            all_moves.extend(moves)
            scanned += 1
        except Exception as e:
            errors += 1

        # Rate limit: ~1200 weight/min, klines = 5 weight each
        if (i + 1) % 40 == 0:
            time.sleep(2)

    # Sort by absolute move size
    all_moves.sort(key=lambda m: abs(m["pct_change"]), reverse=True)

    print(f"\n{'━'*120}")
    print(f"  RESULTS: {len(all_moves)} moves ≥ {args.threshold}% found across {scanned} pairs ({errors} errors)")
    print(f"{'━'*120}")

    if not all_moves:
        print(f"\n  No {args.threshold}%+ moves detected in the last {args.hours} hours.")
        print(f"  Try --threshold 5 for smaller moves or --hours 6 for longer lookback.")
        return

    for idx, move in enumerate(all_moves, 1):
        print_move(move, idx)

    # Summary table
    print(f"\n\n{'='*120}")
    print(f"  SUMMARY — Pre-Move Indicator Medians")
    print(f"{'='*120}")

    rsis = [m["precursors"][-1]["rsi"] for m in all_moves if m["precursors"][-1]["rsi"] is not None and not np.isnan(m["precursors"][-1]["rsi"])]
    atrs = [m["precursors"][-1]["atr_pct"] for m in all_moves if m["precursors"][-1]["atr_pct"] is not None and not np.isnan(m["precursors"][-1]["atr_pct"])]
    squeezes = [m["precursors"][-1]["squeeze_ratio"] for m in all_moves if m["precursors"][-1]["squeeze_ratio"] is not None and not np.isnan(m["precursors"][-1]["squeeze_ratio"])]
    bbs = [m["precursors"][-1]["bb_pctb"] for m in all_moves if m["precursors"][-1]["bb_pctb"] is not None and not np.isnan(m["precursors"][-1]["bb_pctb"])]
    vols = [m["precursors"][-1]["vol_ratio"] for m in all_moves if m["precursors"][-1]["vol_ratio"] is not None and not np.isnan(m["precursors"][-1]["vol_ratio"])]

    ups = [m for m in all_moves if m["direction"] == "UP"]
    downs = [m for m in all_moves if m["direction"] == "DOWN"]

    print(f"\n  {'Metric':<25} {'All':>10} {'UP moves':>10} {'DOWN moves':>10}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
    print(f"  {'Count':<25} {len(all_moves):>10} {len(ups):>10} {len(downs):>10}")

    def med(lst):
        return f"{np.median(lst):.2f}" if lst else "  -"

    def get_vals(moves, key):
        return [m["precursors"][-1][key] for m in moves
                if m["precursors"][-1][key] is not None and not np.isnan(m["precursors"][-1][key])]

    for label, key in [("RSI", "rsi"), ("BB%B", "bb_pctb"), ("Z-score", "zscore"),
                        ("Volume ratio", "vol_ratio"), ("ATR%", "atr_pct"),
                        ("Squeeze ratio", "squeeze_ratio"), ("BB bandwidth%", "bb_bandwidth")]:
        all_v = get_vals(all_moves, key)
        up_v = get_vals(ups, key)
        dn_v = get_vals(downs, key)
        print(f"  {label:<25} {med(all_v):>10} {med(up_v):>10} {med(dn_v):>10}")

    # Squeeze state distribution
    sq_tight = sum(1 for m in all_moves if m["precursors"][-1]["squeeze_status"] == "TIGHT")
    sq_on = sum(1 for m in all_moves if m["precursors"][-1]["squeeze_status"] == "ON")
    sq_off = sum(1 for m in all_moves if m["precursors"][-1]["squeeze_status"] == "OFF")

    print(f"\n  Squeeze state before move:")
    print(f"    TIGHT (<0.8): {sq_tight}/{len(all_moves)} ({sq_tight/max(len(all_moves),1)*100:.0f}%)")
    print(f"    ON   (<1.0):  {sq_on}/{len(all_moves)} ({sq_on/max(len(all_moves),1)*100:.0f}%)")
    print(f"    OFF  (>1.0):  {sq_off}/{len(all_moves)} ({sq_off/max(len(all_moves),1)*100:.0f}%)")

    if args.export:
        export_csv(all_moves, args.csv_file)


if __name__ == "__main__":
    main()
