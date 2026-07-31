#!/usr/bin/env python3
"""
Daily Profit-Taking Action  -  FULLY INDEPENDENT of the trading bot.

Skims HALF of the last 24h NET realized futures profit out of the USDⓈ-M Futures
wallet and parks it in Binance Simple Earn Flexible (the "Earn" wallet), where it
stops being at risk and earns yield.

INDEPENDENCE GUARANTEE:
  This script imports NOTHING from the bot. It does not read or write state.json,
  config.py, or any bot module. It only reads BINANCE_API_KEY / BINANCE_API_SECRET
  from the environment (the same creds the bot uses) and talks to Binance directly.
  It reuses the bot's *signing pattern* (see src/order_executor.py:41-66), not its code.

FLOW (run-once program - compute, move funds, exit):
  1. Dedupe: skip if a Futures->Spot transfer already happened in the last window
     (uses Binance transfer history as source of truth - survives ephemeral filesystems).
  2. Sum NET realized PnL over the last 24h from /fapi/v1/income
     (REALIZED_PNL + COMMISSION + FUNDING_FEE; TRANSFER excluded). Skip if <= 0.
  3. amount = 50% of that, rounded down, capped so the bot's margin floor is preserved.
  4. Transfer Futures -> Spot (universal transfer, type UMFUTURE_MAIN).
  5. Subscribe the USDT into Simple Earn Flexible.

Designed for a once-a-day Railway cron service:  python src/profit_taker.py

Binance API key needs "Permits Universal Transfer" enabled for the transfer to work.

Env overrides (all optional):
  WITHDRAW_FRACTION       default 0.5    (fraction of net 24h profit to skim)
  LOOKBACK_HOURS          default 24     (profit measurement window)
  MIN_WITHDRAW_USDT       default 1.0    (skip dust below this)
  FUTURES_MIN_FLOOR_USDT  default 0.0    (keep at least this much availableBalance on futures)
  DEDUPE_WINDOW_HOURS     default 23     (don't skim twice within this many hours)
  DRY_RUN                 default 0      (set 1 to compute only, move NO funds)
"""
import os
import sys
import time
import hmac
import math
import hashlib
import urllib.parse

import httpx
from dotenv import load_dotenv

# --- Credentials (same env vars the bot uses; loaded from .env if present) ---------
load_dotenv()
API_KEY = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")

# --- Hosts -------------------------------------------------------------------------
FAPI = "https://fapi.binance.com"   # USDⓈ-M Futures: /fapi/v1/income, /fapi/v2/balance
SAPI = "https://api.binance.com"    # Spot host: /sapi/... transfer + Simple Earn, /api/v3/time

# --- Logging -----------------------------------------------------------------------
def log(msg: str, level: str = "INFO") -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    print(f"[{stamp}Z] [profit_taker] [{level}] {msg}", flush=True)


# --- Tunables (env-overridable, independent of bot config.py) -----------------------
def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        log(f"Invalid {name}={raw!r}; using default {default}", "WARN")
        return default

WITHDRAW_FRACTION = _env_float("WITHDRAW_FRACTION", 0.5)
LOOKBACK_HOURS = _env_float("LOOKBACK_HOURS", 24.0)
MIN_WITHDRAW_USDT = _env_float("MIN_WITHDRAW_USDT", 1.0)
FUTURES_MIN_FLOOR_USDT = _env_float("FUTURES_MIN_FLOOR_USDT", 0.0)
DEDUPE_WINDOW_HOURS = _env_float("DEDUPE_WINDOW_HOURS", 23.0)
DRY_RUN = os.environ.get("DRY_RUN", "0").strip().lower() in ("1", "true", "yes", "on")

ASSET = "USDT"
RECV_WINDOW = 20000

# --- HTTP client + server-time offset (mirrors OrderExecutor pattern) ---------------
CLIENT = httpx.Client(timeout=30.0)
TIME_OFFSET = 0  # ms: Binance serverTime - local time


class BinanceError(RuntimeError):
    """Raised when Binance returns a non-200 response, carrying its {code,msg} body."""
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sync_time() -> None:
    """Sync TIME_OFFSET against Binance so signed timestamps are accepted."""
    global TIME_OFFSET
    try:
        resp = CLIENT.get(f"{SAPI}/api/v3/time")
        resp.raise_for_status()
        TIME_OFFSET = int(resp.json()["serverTime"]) - _now_ms()
        log(f"Time synced with Binance (offset {TIME_OFFSET}ms)")
    except Exception as e:  # non-fatal: fall back to local clock
        TIME_OFFSET = 0
        log(f"Could not sync server time ({e}); using local clock", "WARN")


def _signed(method: str, base: str, path: str, params: dict | None = None):
    """HMAC-SHA256 signed request. Params go in the query string for GET and POST
    (same convention as the bot). Raises BinanceError with the JSON body on non-200."""
    p = dict(params or {})
    p["timestamp"] = _now_ms() + TIME_OFFSET
    p.setdefault("recvWindow", RECV_WINDOW)
    query = urllib.parse.urlencode(p)
    p["signature"] = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    resp = CLIENT.request(method, f"{base}{path}", params=p, headers={"X-MBX-APIKEY": API_KEY})
    if resp.status_code != 200:
        raise BinanceError(resp.status_code, resp.text)
    return resp.json()


def _round_down(value: float, decimals: int = 2) -> float:
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


# --- Binance operations -------------------------------------------------------------
def already_skimmed_recently() -> bool:
    """True if a (non-failed) Futures->Spot transfer already happened within the
    dedupe window. Prevents a double cron fire from skimming the same 24h twice."""
    end = _now_ms()
    start = end - int(DEDUPE_WINDOW_HOURS * 3600 * 1000)
    resp = _signed("GET", SAPI, "/sapi/v1/asset/transfer",
                   {"type": "UMFUTURE_MAIN", "startTime": start, "endTime": end, "size": 100})
    rows = resp.get("rows", []) if isinstance(resp, dict) else []
    active = [r for r in rows if str(r.get("status", "")).upper() != "FAILED"]
    if active:
        last = active[0]
        log(f"Found {len(active)} recent Futures->Spot transfer(s); most recent "
            f"amount={last.get('amount')} status={last.get('status')} "
            f"tranId={last.get('tranId')}")
    return len(active) > 0


def net_realized_pnl_24h() -> float:
    """NET realized futures PnL over the last LOOKBACK_HOURS, from /fapi/v1/income.
    Sums income for REALIZED_PNL, COMMISSION and FUNDING_FEE only (TRANSFER excluded,
    so our own withdrawals never corrupt the figure)."""
    end = _now_ms()
    start = end - int(LOOKBACK_HOURS * 3600 * 1000)
    records = _signed("GET", FAPI, "/fapi/v1/income",
                      {"startTime": start, "endTime": end, "limit": 1000})
    if not isinstance(records, list):
        raise RuntimeError(f"Unexpected /fapi/v1/income response: {records!r}")
    if len(records) >= 1000:
        log("income returned 1000 records (the max) - 24h profit may be UNDER-counted; "
            "the skim will be conservative.", "WARN")

    trading_types = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}
    realized = sum(float(r.get("income", 0.0) or 0.0)
                   for r in records if r.get("incomeType") == "REALIZED_PNL")
    commission = sum(float(r.get("income", 0.0) or 0.0)
                     for r in records if r.get("incomeType") == "COMMISSION")
    funding = sum(float(r.get("income", 0.0) or 0.0)
                  for r in records if r.get("incomeType") == "FUNDING_FEE")
    net = sum(float(r.get("income", 0.0) or 0.0)
              for r in records if r.get("incomeType") in trading_types)
    log(f"Last {LOOKBACK_HOURS:.0f}h  realized=${realized:+.4f}  commission=${commission:+.4f}  "
        f"funding=${funding:+.4f}  ->  NET=${net:+.4f}")
    return net


def available_futures_usdt() -> float:
    balances = _signed("GET", FAPI, "/fapi/v2/balance", {})
    for b in balances:
        if b.get("asset") == ASSET:
            return float(b.get("availableBalance", 0.0) or 0.0)
    return 0.0


def find_flexible_product() -> tuple[str | None, float]:
    """Return (productId, minPurchaseAmount) for a purchasable USDT Simple Earn
    Flexible product, or (None, 0.0) if none is available."""
    resp = _signed("GET", SAPI, "/sapi/v1/simple-earn/flexible/list", {"asset": ASSET, "size": 100})
    rows = resp.get("rows", []) if isinstance(resp, dict) else []
    for r in rows:
        if r.get("asset") == ASSET and r.get("canPurchase", False):
            return r.get("productId"), float(r.get("minPurchaseAmount", 0.0) or 0.0)
    return None, 0.0


def transfer_futures_to_spot(amount: float) -> int:
    resp = _signed("POST", SAPI, "/sapi/v1/asset/transfer",
                   {"type": "UMFUTURE_MAIN", "asset": ASSET, "amount": f"{amount:.2f}"})
    tran_id = resp.get("tranId") if isinstance(resp, dict) else None
    if not tran_id:
        raise RuntimeError(f"Transfer returned no tranId: {resp!r}")
    return tran_id


def subscribe_flexible(product_id: str, amount: float) -> int | None:
    """Subscribe `amount` USDT from the Spot wallet into a Simple Earn Flexible product.
    Retries once, because freshly-transferred funds can take a moment to settle in Spot."""
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = _signed("POST", SAPI, "/sapi/v1/simple-earn/flexible/subscribe",
                           {"productId": product_id, "amount": f"{amount:.2f}",
                            "autoSubscribe": "true", "sourceAccount": "SPOT"})
            if not (isinstance(resp, dict) and resp.get("success")):
                raise RuntimeError(f"Subscribe not successful: {resp!r}")
            return resp.get("purchaseId")
        except Exception as e:
            last_err = e
            if attempt == 1:
                log(f"Subscribe attempt 1 failed ({e}); retrying in 3s...", "WARN")
                time.sleep(3)
    raise RuntimeError(f"Simple Earn subscribe failed after 2 attempts: {last_err}")


# --- Orchestration ------------------------------------------------------------------
def run() -> int:
    if not API_KEY or not API_SECRET:
        log("BINANCE_API_KEY / BINANCE_API_SECRET not set in environment.", "ERROR")
        return 2

    log("=" * 70)
    log(f"Daily profit-taking run  (DRY_RUN={DRY_RUN}, fraction={WITHDRAW_FRACTION})")
    _sync_time()

    # 1) Idempotency guard
    if already_skimmed_recently():
        log(f"Already skimmed within the last {DEDUPE_WINDOW_HOURS:.0f}h - nothing to do. Exiting.")
        return 0

    # 2) Profit
    net = net_realized_pnl_24h()
    if net <= 0:
        log(f"NET 24h profit is ${net:+.4f} (down/flat day) - nothing to skim. Exiting.")
        return 0

    # 3) Amount, capped by the bot's margin floor
    amount = _round_down(net * WITHDRAW_FRACTION, 2)
    available = available_futures_usdt()
    headroom = _round_down(max(0.0, available - FUTURES_MIN_FLOOR_USDT), 2)
    if amount > headroom:
        log(f"Capping skim ${amount:.2f} -> ${headroom:.2f} to keep availableBalance "
            f"(${available:.2f}) above floor ${FUTURES_MIN_FLOOR_USDT:.2f}", "WARN")
        amount = headroom

    if amount < MIN_WITHDRAW_USDT:
        log(f"Skim amount ${amount:.2f} below MIN_WITHDRAW_USDT ${MIN_WITHDRAW_USDT:.2f} "
            f"- nothing to do. Exiting.")
        return 0

    # 4) Confirm a purchasable Earn product BEFORE moving funds (don't strand cash in Spot)
    product_id, min_purchase = find_flexible_product()
    if not product_id:
        log("No purchasable USDT Simple Earn Flexible product found - not transferring. Exiting.",
            "ERROR")
        return 3
    if amount < min_purchase:
        log(f"Skim ${amount:.2f} is below the Earn minimum ${min_purchase:.2f} for product "
            f"{product_id} - leaving funds on futures for now. Exiting.", "WARN")
        return 0

    log(f"PLAN: skim ${amount:.2f} (= {WITHDRAW_FRACTION:.0%} of ${net:.4f}) "
        f"Futures -> Spot -> Simple Earn Flexible product {product_id}")

    if DRY_RUN:
        log("DRY_RUN=1 - no funds moved. Exiting.")
        return 0

    # 5) Transfer Futures -> Spot
    tran_id = transfer_futures_to_spot(amount)
    log(f"Transferred ${amount:.2f} USDT Futures -> Spot  (tranId={tran_id})")

    # 6) Subscribe into Simple Earn Flexible
    try:
        purchase_id = subscribe_flexible(product_id, amount)
    except Exception as e:
        log(f"TRANSFER SUCCEEDED but Simple Earn subscribe FAILED: {e}", "ERROR")
        log(f"${amount:.2f} USDT is SAFE in your Spot wallet (tranId={tran_id}); "
            f"subscribe it to Earn manually. Next run will NOT re-transfer (dedupe guard).",
            "ERROR")
        return 4

    log(f"SUBSCRIBED ${amount:.2f} USDT into Simple Earn Flexible "
        f"(product={product_id}, purchaseId={purchase_id})")
    log(f"DONE. Banked ${amount:.2f} of ${net:.4f} 24h profit into Earn.")
    log("=" * 70)
    return 0


def main() -> int:
    try:
        return run()
    except BinanceError as e:
        # Surface Binance's own error body verbatim (e.g. -2015 = key lacks permission / bad IP)
        log(f"Binance API error: {e}", "ERROR")
        if "-2015" in e.body:
            log("Hint: -2015 usually means the API key lacks the required permission "
                "('Permits Universal Transfer') or the request IP isn't whitelisted.", "ERROR")
        return 5
    except Exception as e:
        log(f"Unexpected error: {e}", "ERROR")
        return 1
    finally:
        CLIENT.close()


if __name__ == "__main__":
    sys.exit(main())
