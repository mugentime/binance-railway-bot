"""
Martingale Signal Scanner - Pair Scanner
Fetches all market data from Binance Futures API
"""
import asyncio
import numpy as np
from typing import Dict, List
import httpx
from utils import log
import config

class PairScanner:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.symbols_cache = None

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    def _estimate_slippage(self, order_book_side: list, notional_usd: float, side: str) -> float:
        """
        Estimate slippage for a given notional size against order book depth
        Args:
            order_book_side: List of [price, quantity] from order book (asks for BUY, bids for SELL)
            notional_usd: Notional size in USD
            side: "BUY" or "SELL"
        Returns:
            Estimated slippage as percentage
        """
        if not order_book_side:
            return 999.0  # No liquidity

        best_price = float(order_book_side[0][0])
        remaining_notional = notional_usd
        total_cost = 0.0
        total_qty = 0.0

        # Walk through order book levels
        for price_str, qty_str in order_book_side:
            price = float(price_str)
            qty = float(qty_str)

            # Calculate how much notional this level can fill
            level_notional = price * qty

            if level_notional >= remaining_notional:
                # This level completes the fill
                filled_qty = remaining_notional / price
                total_cost += remaining_notional
                total_qty += filled_qty
                break
            else:
                # Consume entire level
                total_cost += level_notional
                total_qty += qty
                remaining_notional -= level_notional

        if total_qty == 0:
            return 999.0  # Insufficient liquidity

        # Calculate average fill price
        avg_fill_price = total_cost / total_qty

        # Calculate slippage percentage
        slippage_pct = abs((avg_fill_price - best_price) / best_price) * 100

        return slippage_pct

    async def get_all_symbols(self) -> List[str]:
        """Get all USDT-M futures symbols with volume and size filtering"""
        if self.symbols_cache:
            return self.symbols_cache

        log("Fetching exchange info and filtering symbols...")

        # Get exchange info
        resp = await self.client.get(f"{config.BINANCE_BASE_URL}/fapi/v1/exchangeInfo")
        resp.raise_for_status()
        exchange_info = resp.json()

        # Build lookup map for faster access
        exchange_symbols_map = {s["symbol"]: s for s in exchange_info["symbols"]}

        # Get 24h ticker for volume filtering
        resp = await self.client.get(f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/24hr")
        resp.raise_for_status()
        tickers = {t["symbol"]: float(t["quoteVolume"]) for t in resp.json()}

        # Get current prices for min order size check
        resp = await self.client.get(f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/price")
        resp.raise_for_status()
        prices = {p["symbol"]: float(p["price"]) for p in resp.json()}

        # Estimate base size for filtering (assuming $100 account: $100 * 3% = $3)
        estimated_base_size = 100.0 * config.BASE_SIZE_PCT
        level_0_notional = estimated_base_size * config.LEVERAGE  # e.g., $60 at level 0

        # Use curated list if enabled, otherwise scan all symbols
        if config.USE_CURATED_PAIR_LIST:
            log(f"Using curated pair list ({len(config.CURATED_PAIR_LIST)} pairs)")
            candidate_symbols = config.CURATED_PAIR_LIST
            skipped_not_found = []
        else:
            log("Using dynamic symbol discovery")
            candidate_symbols = [s["symbol"] for s in exchange_info["symbols"]]
            skipped_not_found = None

        symbols = []

        for symbol in candidate_symbols:
            # Check if symbol exists on USDT-M futures
            symbol_info = exchange_symbols_map.get(symbol)
            if not symbol_info:
                if skipped_not_found is not None:
                    skipped_not_found.append(symbol)
                continue

            # Basic filters
            if symbol_info["quoteAsset"] != config.QUOTE_ASSET:
                continue
            if symbol_info["status"] != "TRADING":
                continue
            if symbol_info["contractType"] != "PERPETUAL":
                continue
            if symbol in config.EXCLUDED_SYMBOLS:
                continue

            # Filter non-ASCII symbols (Chinese meme tokens with terrible liquidity)
            if not symbol.isascii():
                continue

            # Volume filter (only if dynamic discovery)
            if not config.USE_CURATED_PAIR_LIST:
                volume = tickers.get(symbol, 0)
                if volume < config.MIN_24H_VOLUME_USD:
                    continue

            # Minimum order size filter (CRITICAL for level 0 trades)
            price = prices.get(symbol)
            if not price:
                continue

            # Check MIN_NOTIONAL
            min_notional = None
            min_qty = None

            for f in symbol_info["filters"]:
                if f["filterType"] == "MIN_NOTIONAL":
                    min_notional = float(f["notional"])
                elif f["filterType"] == "MARKET_LOT_SIZE":
                    min_qty = float(f["minQty"])

            # Reject if level-0 notional is too small
            if min_notional and level_0_notional < min_notional:
                continue

            # Reject if min quantity * price exceeds level-0 notional
            if min_qty and (min_qty * price) > level_0_notional:
                continue

            symbols.append(symbol)

        # Report skipped pairs if using curated list
        if skipped_not_found:
            log(f"SKIPPED ({len(skipped_not_found)}): Not found on USDT-M futures: {', '.join(skipped_not_found)}")

        self.symbols_cache = symbols
        log(f"Filtered to {len(symbols)} tradeable symbols (level-0 notional=${level_0_notional})")
        return symbols

    async def scan_all_pairs(self) -> Dict[str, dict]:
        """
        Scan all pairs and return market data
        Returns: {symbol: {closes, volumes, spread_pct, funding_rate, volume_24h}}
        """
        symbols = await self.get_all_symbols()
        log(f"Scanning {len(symbols)} pairs...")

        # Get 24h ticker for volume data
        resp = await self.client.get(f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/24hr")
        resp.raise_for_status()
        volume_24h_data = {t["symbol"]: float(t["quoteVolume"]) for t in resp.json()}

        # Get funding rates (single request for all symbols)
        resp = await self.client.get(f"{config.BINANCE_BASE_URL}/fapi/v1/premiumIndex")
        resp.raise_for_status()
        funding_rates = {item["symbol"]: float(item["lastFundingRate"])
                        for item in resp.json()}

        # Fetch klines and depth in controlled batches
        pair_data = {}
        filter_stats = {
            "initial": len(symbols),
            "atr_filtered": 0,
            "spread_filtered": 0,
            "slippage_filtered": 0,
            "passed": 0
        }
        semaphore = asyncio.Semaphore(20)  # Max 20 concurrent requests

        async def fetch_pair_data(symbol: str):
            async with semaphore:
                try:
                    # Klines (2 weight)
                    klines_resp = await self.client.get(
                        f"{config.BINANCE_BASE_URL}/fapi/v1/klines",
                        params={
                            "symbol": symbol,
                            "interval": config.KLINE_INTERVAL,
                            "limit": config.KLINE_LIMIT
                        }
                    )
                    klines_resp.raise_for_status()
                    klines = klines_resp.json()

                    closes = np.array([float(k[4]) for k in klines])  # Close price
                    highs = np.array([float(k[2]) for k in klines])   # High price
                    lows = np.array([float(k[3]) for k in klines])    # Low price
                    volumes = np.array([float(k[5]) for k in klines])  # Volume

                    # Calculate ATR (Average True Range) for volatility filtering
                    # True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
                    if len(closes) >= config.ATR_PERIOD + 1:
                        true_ranges = []
                        for i in range(1, len(klines)):
                            high = highs[i]
                            low = lows[i]
                            prev_close = closes[i-1]

                            tr = max(
                                high - low,
                                abs(high - prev_close),
                                abs(low - prev_close)
                            )
                            true_ranges.append(tr)

                        # Calculate ATR as average of last ATR_PERIOD true ranges
                        if len(true_ranges) >= config.ATR_PERIOD:
                            atr = np.mean(true_ranges[-config.ATR_PERIOD:])
                            current_price = closes[-1]
                            atr_pct = (atr / current_price) * 100

                            # Filter: Reject pairs with ATR% below threshold (too slow-moving)
                            if atr_pct < config.MIN_ATR_PCT:
                                filter_stats["atr_filtered"] += 1
                                return  # Skip this pair
                        else:
                            # Not enough data to calculate ATR, skip
                            return
                    else:
                        # Not enough candles, skip
                        return

                    # SMA slope computation removed: KLINE_LIMIT=50, SMA_PERIOD=50
                    # produces only 1 SMA value, slope is always 0.0
                    sma_slope_pct = 0.0
                    # Order book depth (2 weight)
                    await asyncio.sleep(0.05)  # Rate limit control
                    depth_resp = await self.client.get(
                        f"{config.BINANCE_BASE_URL}/fapi/v1/depth",
                        params={"symbol": symbol, "limit": 5}
                    )
                    depth_resp.raise_for_status()
                    depth = depth_resp.json()

                    best_bid = float(depth["bids"][0][0])
                    best_ask = float(depth["asks"][0][0])
                    midprice = (best_bid + best_ask) / 2
                    spread_pct = (best_ask - best_bid) / midprice * 100

                    # Filter: Reject pairs with spread > MAX_SPREAD_PCT
                    if spread_pct > config.MAX_SPREAD_PCT:
                        filter_stats["spread_filtered"] += 1
                        return  # Skip this pair

                    # Slippage guard: Estimate fill price for max level position
                    # Based on $100 account baseline (conservative filter)
                    estimated_base_size = 100.0 * config.BASE_SIZE_PCT
                    max_notional = estimated_base_size * (config.MARTINGALE_MULTIPLIER ** config.MAX_LEVEL) * config.LEVERAGE

                    # Calculate estimated fill price from order book
                    # For LONG: buying at asks, for SHORT: selling at bids
                    estimated_slippage_long = self._estimate_slippage(depth["asks"], max_notional, "BUY")
                    estimated_slippage_short = self._estimate_slippage(depth["bids"], max_notional, "SELL")

                    # Reject if either direction has excessive slippage
                    if estimated_slippage_long > config.MAX_SLIPPAGE_PCT or estimated_slippage_short > config.MAX_SLIPPAGE_PCT:
                        filter_stats["slippage_filtered"] += 1
                        return  # Skip this pair

                    filter_stats["passed"] += 1
                    pair_data[symbol] = {
                        "closes": closes,
                        "volumes": volumes,
                        "spread_pct": spread_pct,
                        "funding_rate": funding_rates.get(symbol, 0.0),
                        "slippage_long": estimated_slippage_long,
                        "slippage_short": estimated_slippage_short,
                        "atr_pct": atr_pct,  # Store ATR% for logging/analysis
                        "volume_24h": volume_24h_data.get(symbol, 0.0),  # 24h quote volume in USD
                        "sma_slope_pct": sma_slope_pct,  # SMA slope percentage per candle
                    }

                except Exception as e:
                    log(f"Error fetching data for {symbol}: {e}", "warning")

        # Fetch all pairs
        tasks = [fetch_pair_data(symbol) for symbol in symbols]
        await asyncio.gather(*tasks)

        # Log filtering pipeline statistics
        log("=" * 80)
        log("FILTERING PIPELINE")
        log("=" * 80)
        initial = filter_stats["initial"]
        after_atr = initial - filter_stats["atr_filtered"]
        after_spread = after_atr - filter_stats["spread_filtered"]
        after_slippage = after_spread - filter_stats["slippage_filtered"]
        final = filter_stats["passed"]

        log(f"Initial pairs:        {initial}")
        log(f"After ATR filter:     {after_atr} ({initial} → {after_atr}, filtered {filter_stats['atr_filtered']})")
        log(f"After spread filter:  {after_spread} ({after_atr} → {after_spread}, filtered {filter_stats['spread_filtered']})")
        log(f"After slippage filter: {after_slippage} ({after_spread} → {after_slippage}, filtered {filter_stats['slippage_filtered']})")
        log(f"Final pairs passed:   {final}")
        log("=" * 80)

        return pair_data

# Test standalone
async def main():
    scanner = PairScanner()
    try:
        data = await scanner.scan_all_pairs()
        print(f"\n{'='*80}")
        print(f"PAIR SCANNER TEST")
        print(f"{'='*80}")
        print(f"Total pairs scanned: {len(data)}")
        print(f"\nSample data (first 5 pairs):")
        for i, (symbol, info) in enumerate(list(data.items())[:5]):
            print(f"\n{symbol}:")
            print(f"  Closes: {len(info['closes'])} candles, last={info['closes'][-1]:.4f}")
            print(f"  Volumes: avg={info['volumes'].mean():.2f}")
            print(f"  Spread: {info['spread_pct']:.4f}%")
            print(f"  Slippage: LONG={info['slippage_long']:.4f}% SHORT={info['slippage_short']:.4f}%")
            print(f"  Funding: {info['funding_rate']:.6f}")
            print(f"  ATR%: {info['atr_pct']:.2f}%")
    finally:
        await scanner.close()

if __name__ == "__main__":
    asyncio.run(main())
