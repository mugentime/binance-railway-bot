"""Shared fetch/cache helpers for the martingale-robustness research pipeline. Reuses the exact
conventions already established in research/bollinger_pyramid_5m/backtest_bollinger_5m.py (same
FAPI base, same retry/backoff, same disk-cache pattern) rather than re-inventing them, but points
the cache at this folder's own cache/ dir so it doesn't collide with or get evicted by that other
script's CACHE_TTL_SEC-based universe cache."""
import asyncio
import json
import os
import time
from datetime import datetime, timezone

import httpx

FAPI = "https://fapi.binance.com"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "cache")
OUTPUT_DIR = os.path.join(HERE, "output")
TAKER_FEE = 0.0004
SLIPPAGE_BPS_TIER1 = 15 / 10000.0  # matches SLIPPAGE_BPS_TIER[1] in backtest_bollinger_5m.py


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}Z] {msg}", flush=True)


def ts_str(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def cache_load(name):
    path = _cache_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def cache_save(name, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(name), "w") as f:
        json.dump(data, f)


async def get_json(client, path, params=None, tries=4):
    for attempt in range(tries):
        try:
            r = await client.get(f"{FAPI}{path}", params=params)
            if r.status_code == 429 or r.status_code == 418:
                wait = float(r.headers.get("Retry-After", 3))
                log(f"  rate-limited on {path} ({r.status_code}); sleeping {wait}s")
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == tries - 1:
                raise
            await asyncio.sleep(1.5)
    return None
