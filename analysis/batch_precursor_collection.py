#!/usr/bin/env python3
"""
Batch Precursor Collection for 24h 10%+ Movers
===============================================
Collects precursor indicator data for all symbols that moved 10%+ in the last 24 hours.
For each mover:
  1. Fetches 5-minute klines covering last 48 hours
  2. Scans to find exact candle where 10%+ move occurred
  3. Extracts 6 precursor candles (30 minutes) before move start
  4. Calculates indicators: RSI, BB%B, Z-score, Volume Ratio, ATR%, Squeeze

Output: analysis/226_movers_precursors.json

Usage:
  python analysis/batch_precursor_collection.py
  python analysis/batch_precursor_collection.py --limit 50  # test run
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import numpy as np

# ─── CONFIG ──────────────────────────────────────────────────────────────────

BINANCE_BASE = "https://fapi.binance.com"
KLINE_INTERVAL = "5m"
PRECURSOR_CANDLES = 6          # 30 minutes of precursor data
LOOKBACK_CANDLES = 576         # 48 hours of 5-min candles
WARMUP_CANDLES = 40            # Extra candles for indicator calculation

# Indicator periods (matching current bot config)
RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 14
KELTNER_PERIOD = 20
KELTNER_ATR_MULT = 1.5
ZSCORE_PERIOD = 20
VOLUME_PERIOD = 20

# Rate limiting
RATE_LIMIT_DELAY = 0.2         # 200ms between requests

# ─── INDICATOR CALCULATION FUNCTIONS ─────────────────────────────────────────

def calc_rsi(closes, period=RSI_PERIOD):
    """Wilder's RSI calculation"""
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

    return rsis


def calc_bb(closes, period=BB_PERIOD, std_mult=BB_STD):
    """Bollinger Bands → returns pct_b and bandwidth"""
    n = len(closes)
    pct_b = [np.nan] * n
    bandwidth = [np.nan] * n

    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        sma = np.mean(window)
        std = np.std(window, ddof=0)
        u = sma + std_mult * std
        l = sma - std_mult * std

        if u - l > 0:
            pct_b[i] = (closes[i] - l) / (u - l)
            bandwidth[i] = (u - l) / sma
        else:
            pct_b[i] = 0.5
            bandwidth[i] = 0.0

    return pct_b, bandwidth


def calc_atr(highs, lows, closes, period=ATR_PERIOD):
    """Average True Range → returns ATR% of price"""
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
    """Keltner Channel width calculation"""
    n = len(closes)
    ema = [np.nan] * n
    kc_width = [np.nan] * n
    k = 2.0 / (period + 1)

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
    """Squeeze indicator: BB_width / KC_width"""
    n = len(bb_bandwidth)
    squeeze = [np.nan] * n
    for i in range(n):
        bw = bb_bandwidth[i]
        kw = kc_width[i]
        if bw is not None and kw is not None and not np.isnan(bw) and not np.isnan(kw) and kw > 0:
            squeeze[i] = bw / kw
    return squeeze


def calc_zscore(closes, period=ZSCORE_PERIOD):
    """Z-score of price relative to rolling mean/std"""
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


def calc_volume_ratio(volumes, period=VOLUME_PERIOD):
    """Current volume / SMA(volume, period)"""
    n = len(volumes)
    vr = [np.nan] * n
    for i in range(period - 1, n):
        avg = np.mean(volumes[i - period + 1:i + 1])
        if avg > 0:
            vr[i] = volumes[i] / avg
        else:
            vr[i] = 0.0
    return vr

# ─── DATA FETCHING FUNCTIONS ─────────────────────────────────────────────────

def get_klines(symbol, interval="5m", limit=1000):
    """Fetch klines from Binance Futures API"""
    try:
        r = requests.get(
            f"{BINANCE_BASE}/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
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
    except Exception as e:
        print(f"    Error fetching klines for {symbol}: {e}")
        return None


def find_move_candle(candles, mover_pct):
    """
    Find candles where significant price moves occurred.
    Strategy: Look for candles with 3%+ single-candle moves (5min timeframe).
    Returns the most recent significant move candle.
    """
    if not candles or len(candles) < 2:
        return None

    # For 5-min candles, look for 2%+ single-candle moves
    # Lower threshold to catch more gradual 10%+ moves
    min_move_threshold = 2.0

    # Search backwards from most recent candle
    for i in range(len(candles) - 1, 0, -1):
        current = candles[i]
        prev = candles[i - 1]

        prev_close = prev['close']

        # Check for upward move
        if mover_pct > 0:
            # Check multiple move calculations
            oc_move = ((current['close'] - current['open']) / current['open']) * 100
            hl_move = ((current['high'] - prev_close) / prev_close) * 100
            cl_move = ((current['close'] - prev_close) / prev_close) * 100

            if oc_move >= min_move_threshold or hl_move >= min_move_threshold or cl_move >= min_move_threshold:
                return i

        # Check for downward move
        else:
            # Check multiple move calculations
            oc_move = ((current['close'] - current['open']) / current['open']) * 100
            lh_move = ((current['low'] - prev_close) / prev_close) * 100
            cl_move = ((current['close'] - prev_close) / prev_close) * 100

            if oc_move <= -min_move_threshold or lh_move <= -min_move_threshold or cl_move <= -min_move_threshold:
                return i

    return None


def extract_precursors(candles, move_idx, num_precursors=6):
    """
    Extract precursor candles before the move.
    Returns list of precursor candle data with indicators.
    """
    if move_idx < num_precursors + WARMUP_CANDLES:
        return None  # Not enough history

    # Extract candles including warmup period
    start_idx = move_idx - num_precursors - WARMUP_CANDLES
    end_idx = move_idx  # Up to but not including the move candle

    subset = candles[start_idx:end_idx]

    # Extract OHLCV arrays
    closes = [c['close'] for c in subset]
    highs = [c['high'] for c in subset]
    lows = [c['low'] for c in subset]
    volumes = [c['volume'] for c in subset]

    # Calculate indicators
    rsi = calc_rsi(closes)
    bb_pct_b, bb_bandwidth = calc_bb(closes)
    atr_abs, atr_pct = calc_atr(highs, lows, closes)
    kc_width = calc_keltner_width(closes, atr_abs)
    squeeze = calc_squeeze(bb_bandwidth, kc_width)
    zscore = calc_zscore(closes)
    volume_ratio = calc_volume_ratio(volumes)

    # Extract last 6 candles (after warmup)
    precursor_candles = []
    for i in range(len(subset) - num_precursors, len(subset)):
        candle = subset[i]
        offset = i - (len(subset) - num_precursors) - num_precursors  # -6 to -1

        precursor_candles.append({
            "candle_offset": offset,
            "time": datetime.fromtimestamp(candle['open_time'] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            "timestamp": candle['open_time'],
            "open": candle['open'],
            "high": candle['high'],
            "low": candle['low'],
            "close": candle['close'],
            "volume": candle['volume'],
            "rsi": round(rsi[i], 2) if not np.isnan(rsi[i]) else None,
            "bb_pct_b": round(bb_pct_b[i], 3) if not np.isnan(bb_pct_b[i]) else None,
            "zscore": round(zscore[i], 2) if not np.isnan(zscore[i]) else None,
            "volume_ratio": round(volume_ratio[i], 2) if not np.isnan(volume_ratio[i]) else None,
            "atr_pct": round(atr_pct[i], 2) if not np.isnan(atr_pct[i]) else None,
            "squeeze_ratio": round(squeeze[i], 2) if not np.isnan(squeeze[i]) else None,
        })

    return precursor_candles


def process_mover(mover, progress_str=""):
    """
    Process a single mover: fetch klines, find move, extract precursors.
    Returns dict with mover metadata + precursor candles.
    """
    symbol = mover['symbol']
    move_pct = mover['price_change_pct']

    print(f"{progress_str}Processing {symbol:15} ({move_pct:+7.2f}%)...", end=" ", flush=True)

    # Fetch klines
    candles = get_klines(symbol, KLINE_INTERVAL, LOOKBACK_CANDLES)
    if not candles:
        print("❌ Failed to fetch klines")
        return None

    # Find move candle
    move_idx = find_move_candle(candles, move_pct)
    if move_idx is None:
        print("❌ Could not find move candle")
        return None

    # Extract precursors
    precursors = extract_precursors(candles, move_idx, PRECURSOR_CANDLES)
    if precursors is None:
        print("❌ Insufficient history for precursors")
        return None

    print(f"✓ Found {len(precursors)} precursor candles")

    # Determine direction based on price change
    direction = "UP" if move_pct > 0 else "DOWN"

    return {
        "symbol": symbol,
        "move_metadata": {
            "move_pct": move_pct,
            "direction": direction,
            "timestamp": candles[move_idx]['open_time'],
            "move_time": datetime.fromtimestamp(candles[move_idx]['open_time'] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            "last_price": mover['last_price'],
            "high_24h": mover['high'],
            "low_24h": mover['low'],
        },
        "precursor_candles": precursors
    }


def load_movers(filepath):
    """Load 24h movers JSON file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['movers']


def save_results(results, filepath):
    """Save results to JSON file"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_processed': len(results),
            'movers': results
        }, f, indent=2)

    print(f"\n✓ Results saved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description='Batch collect precursor data for 24h movers')
    parser.add_argument('--limit', type=int, help='Limit number of movers to process (for testing)')
    parser.add_argument('--input', default='../docs/trades_export/24h_movers.json', help='Input movers JSON file')
    parser.add_argument('--output', default='226_movers_precursors.json', help='Output filename')
    args = parser.parse_args()

    # Convert relative paths
    input_path = Path(__file__).parent / args.input
    output_path = Path(__file__).parent / args.output

    print("=" * 80)
    print("BATCH PRECURSOR COLLECTION FOR 24H MOVERS")
    print("=" * 80)

    # Load movers data
    print(f"\nLoading movers from: {input_path}")
    movers = load_movers(input_path)

    # Filter for 10%+ moves
    movers_10pct = [m for m in movers if abs(m['price_change_pct']) >= 10.0]

    if args.limit:
        movers_10pct = movers_10pct[:args.limit]

    print(f"Found {len(movers_10pct)} movers with 10%+ change")
    print(f"Target: {len(movers_10pct)} symbols\n")

    # Process each mover
    results = []
    failed = []

    start_time = time.time()

    for idx, mover in enumerate(movers_10pct, 1):
        progress = f"[{idx:3d}/{len(movers_10pct)}] "

        result = process_mover(mover, progress)

        if result:
            results.append(result)
        else:
            failed.append(mover['symbol'])

        # Rate limiting
        time.sleep(RATE_LIMIT_DELAY)

    # Print summary
    elapsed = time.time() - start_time
    success_rate = (len(results) / len(movers_10pct) * 100) if movers_10pct else 0

    print("\n" + "=" * 80)
    print("COLLECTION SUMMARY")
    print("=" * 80)
    print(f"Total processed:     {len(movers_10pct)}")
    print(f"Successful:          {len(results)} ({success_rate:.1f}%)")
    print(f"Failed:              {len(failed)}")
    print(f"Elapsed time:        {elapsed:.1f} seconds")
    print(f"Average per symbol:  {elapsed/len(movers_10pct):.2f} seconds")

    if failed:
        print(f"\nFailed symbols: {', '.join(failed[:20])}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more")

    # Save results
    save_results(results, output_path)

    print("\n✓ Collection complete!")
    print(f"✓ Success rate: {success_rate:.1f}% (minimum target: 80%)")

    if success_rate < 80:
        print("\n⚠️  WARNING: Success rate below 80% target")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
