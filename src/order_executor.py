"""
Martingale Signal Scanner - Order Executor
All Binance Futures trading API interactions (HMAC-SHA256 signed)
"""
import hmac
import hashlib
import time
import urllib.parse
from typing import Dict, Optional
import httpx
import config
from utils import log, round_down

class OrderExecutor:
    def __init__(self):
        self.client = httpx.Client(timeout=30.0)
        self.symbol_info_cache: Dict[str, dict] = {}
        self.time_offset = 0  # Offset between local time and server time
        self.last_sync_time = 0  # Track when we last synced
        self._sync_server_time()
        self._load_exchange_info()

    def close(self):
        """Close HTTP client"""
        self.client.close()

    def _sync_server_time(self):
        """Sync local time with Binance server time"""
        try:
            resp = self.client.get(f"{config.BINANCE_BASE_URL}/fapi/v1/time")
            resp.raise_for_status()
            server_time = resp.json()["serverTime"]
            local_time = int(time.time() * 1000)
            self.time_offset = server_time - local_time
            self.last_sync_time = time.time()
            log(f"Time synced with Binance server (offset: {self.time_offset}ms)")
        except Exception as e:
            log(f"Failed to sync server time: {e}", "warning")
            self.time_offset = 0

    def _sign_params(self, params: dict) -> dict:
        """Sign parameters with HMAC-SHA256"""
        # Re-sync time if it's been more than 5 minutes (prevents drift)
        if time.time() - self.last_sync_time > 300:  # 5 minutes
            self._sync_server_time()

        # Use server-synced time
        params["timestamp"] = int(time.time() * 1000) + self.time_offset
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            config.BINANCE_API_SECRET.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def _headers(self) -> dict:
        """Get API headers"""
        return {"X-MBX-APIKEY": config.BINANCE_API_KEY}

    def _load_exchange_info(self):
        """Load and cache exchange info (symbol precision data)"""
        log("Loading exchange info...")
        resp = self.client.get(f"{config.BINANCE_BASE_URL}/fapi/v1/exchangeInfo")
        resp.raise_for_status()
        exchange_info = resp.json()

        for symbol_data in exchange_info["symbols"]:
            symbol = symbol_data["symbol"]

            # Extract tick size and lot size from filters
            tick_size = None
            step_size = None
            for f in symbol_data.get("filters", []):
                if f["filterType"] == "PRICE_FILTER":
                    tick_size = float(f["tickSize"])
                elif f["filterType"] == "LOT_SIZE":
                    step_size = float(f["stepSize"])

            self.symbol_info_cache[symbol] = {
                "quantityPrecision": symbol_data["quantityPrecision"],
                "pricePrecision": symbol_data["pricePrecision"],
                "tickSize": tick_size,
                "stepSize": step_size,
            }

        log(f"Cached info for {len(self.symbol_info_cache)} symbols")

    def _round_to_tick_size(self, price: float, tick_size: float) -> float:
        """Round price to nearest tick size"""
        return round(price / tick_size) * tick_size

    def _round_to_step_size(self, quantity: float, step_size: float) -> float:
        """Round quantity to nearest step size"""
        return round(quantity / step_size) * step_size

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        Set leverage for symbol
        Returns: True if successful, False if symbol doesn't support leverage
        """
        params = {"symbol": symbol, "leverage": leverage}
        params = self._sign_params(params)

        try:
            resp = self.client.post(
                f"{config.BINANCE_BASE_URL}/fapi/v1/leverage",
                params=params,
                headers=self._headers()
            )
            resp.raise_for_status()
            log(f"Set leverage {leverage}x for {symbol}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                try:
                    error_data = e.response.json()
                    error_code_raw = error_data.get('code', 'unknown')
                    error_msg = error_data.get('msg', 'unknown')

                    # Normalize error code to integer for comparison
                    try:
                        error_code = int(error_code_raw) if error_code_raw != 'unknown' else None
                    except (ValueError, TypeError):
                        error_code = None

                    # -4028: Leverage not available for this symbol
                    # -4300: Invalid leverage
                    if error_code in [-4028, -4300]:
                        log(f"Leverage {leverage}x not available for {symbol} (code: {error_code})", "warning")
                        return False
                    else:
                        # Other 400 errors should raise
                        log(f"Failed to set leverage for {symbol}: {error_data}", "error")
                        raise
                except ValueError:
                    # Failed to parse JSON response
                    log(f"Failed to set leverage for {symbol}: {e.response.text}", "error")
                    raise
            else:
                # Non-400 errors are critical
                raise

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED"):
        """
        Set margin type for symbol and VERIFY it's actually set
        Raises exception if verification fails
        """
        params = {"symbol": symbol, "marginType": margin_type}
        params = self._sign_params(params)

        try:
            resp = self.client.post(
                f"{config.BINANCE_BASE_URL}/fapi/v1/marginType",
                params=params,
                headers=self._headers()
            )
            resp.raise_for_status()
            log(f"Set margin type {margin_type} for {symbol}")
        except httpx.HTTPStatusError as e:
            # Common errors: -4046 (already set), -4047 (no need to change)
            if e.response.status_code == 400:
                try:
                    error_data = e.response.json()
                    error_code_raw = error_data.get('code', 'unknown')

                    # Normalize error code to integer for comparison
                    try:
                        error_code = int(error_code_raw) if error_code_raw != 'unknown' else None
                    except (ValueError, TypeError):
                        error_code = None

                    # -4046: Margin type already set, this is OK
                    # -4047: No need to change margin type
                    if error_code in [-4046, -4047]:
                        log(f"Margin type already configured for {symbol} (code: {error_code})")
                    else:
                        # Other 400 errors are not acceptable
                        log(f"Failed to set margin type for {symbol}: {error_data}", "error")
                        raise
                except ValueError:
                    # Failed to parse JSON response
                    log(f"Failed to set margin type for {symbol}: {e.response.text}", "error")
                    raise
            else:
                # Non-400 errors are critical
                raise

        # VERIFICATION: Check that margin type is actually set correctly
        position = self.get_position(symbol)
        if position:
            actual_margin_type = position.get('marginType', '').upper()

            # Normalize margin types: CROSSED <-> CROSS, ISOLATED <-> ISOLATED
            expected_normalized = "CROSS" if margin_type == "CROSSED" else margin_type
            actual_normalized = "CROSS" if actual_margin_type == "CROSSED" else actual_margin_type

            if actual_normalized != expected_normalized:
                error_msg = f"CRITICAL: Margin type verification FAILED for {symbol}! Expected {margin_type} (normalized: {expected_normalized}), got {actual_margin_type} (normalized: {actual_normalized})"
                log(error_msg, "error")
                raise Exception(error_msg)
            else:
                log(f"✓ Verified margin type {margin_type} for {symbol} (API returned: {actual_margin_type})")
        else:
            log(f"Warning: Could not verify margin type for {symbol} (no position info)", "warning")

    def get_current_price(self, symbol: str) -> float:
        """Get current market price"""
        resp = self.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/price",
            params={"symbol": symbol}
        )
        resp.raise_for_status()
        return float(resp.json()["price"])

    def check_orderbook_depth(self, symbol: str, notional_usd: float) -> bool:
        """
        Check if orderbook has sufficient depth to absorb position without excessive slippage
        Args:
            symbol: Trading pair
            notional_usd: Position size in USD
        Returns:
            True if depth is sufficient, False otherwise
        """
        try:
            # Get orderbook (top 20 levels)
            resp = self.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/depth",
                params={"symbol": symbol, "limit": 20}
            )
            resp.raise_for_status()
            orderbook = resp.json()

            # Get mid price
            best_bid = float(orderbook["bids"][0][0]) if orderbook["bids"] else 0
            best_ask = float(orderbook["asks"][0][0]) if orderbook["asks"] else 0

            if best_bid == 0 or best_ask == 0:
                log(f"Orderbook check failed for {symbol}: empty orderbook", "warning")
                return False

            mid_price = (best_bid + best_ask) / 2

            # Calculate acceptable price range (within 1% of mid)
            max_bid = mid_price * (1 - config.ORDERBOOK_DEPTH_PCT)
            min_ask = mid_price * (1 + config.ORDERBOOK_DEPTH_PCT)

            # Sum up bid depth within acceptable range
            bid_depth_usd = 0
            for bid in orderbook["bids"]:
                price = float(bid[0])
                qty = float(bid[1])
                if price >= max_bid:
                    bid_depth_usd += price * qty
                else:
                    break

            # Sum up ask depth within acceptable range
            ask_depth_usd = 0
            for ask in orderbook["asks"]:
                price = float(ask[0])
                qty = float(ask[1])
                if price <= min_ask:
                    ask_depth_usd += price * qty
                else:
                    break

            # Check if depth is sufficient (use the smaller of bid/ask depth)
            min_depth = min(bid_depth_usd, ask_depth_usd)

            if min_depth < config.ORDERBOOK_DEPTH_MIN_USD:
                log(f"Insufficient orderbook depth for {symbol}: ${min_depth:.0f} < ${config.ORDERBOOK_DEPTH_MIN_USD} (within {config.ORDERBOOK_DEPTH_PCT*100}%)", "warning")
                return False

            log(f"Orderbook depth OK for {symbol}: ${min_depth:.0f} within {config.ORDERBOOK_DEPTH_PCT*100}% of mid price")
            return True

        except Exception as e:
            log(f"Error checking orderbook depth for {symbol}: {e}", "warning")
            return False

    def place_market_order(self, symbol: str, side: str, notional_usd: float) -> dict:
        """
        Place market order
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "BUY" or "SELL"
            notional_usd: Notional size in USD
        Returns:
            Order response dict with avgPrice and executedQty
        """
        # Get current price
        current_price = self.get_current_price(symbol)

        # Calculate quantity
        raw_qty = notional_usd / current_price
        qty_precision = self.symbol_info_cache[symbol]["quantityPrecision"]
        quantity = round_down(raw_qty, qty_precision)

        log(f"Placing MARKET {side} order: {symbol} qty={quantity:.{qty_precision}f} "
            f"(notional=${notional_usd:.2f} @ price={current_price:.4f})")

        # Place order
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{quantity:.{qty_precision}f}",
            "newOrderRespType": "RESULT",  # Get full execution details immediately
        }
        params = self._sign_params(params)

        resp = self.client.post(
            f"{config.BINANCE_BASE_URL}/fapi/v1/order",
            params=params,
            headers=self._headers()
        )

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Log Binance error details
            try:
                error_data = e.response.json()
                log(f"Binance API Error: {error_data}", "error")
            except:
                log(f"Binance API Error: {e.response.text}", "error")
            raise

        order = resp.json()

        # Validate order actually filled
        executed_qty = float(order.get('executedQty', 0))
        avg_price = float(order.get('avgPrice', 0))
        order_status = order.get('status', '')

        # If order is NEW (not filled immediately), wait briefly and check again
        if order_status == 'NEW' and executed_qty == 0:
            import time
            log(f"Order status NEW, waiting 1s to check if it fills...")
            time.sleep(1)

            # Query the order to get updated status
            query_params = {"symbol": symbol, "orderId": order['orderId']}
            query_params = self._sign_params(query_params)
            query_resp = self.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/order",
                params=query_params,
                headers=self._headers()
            )
            query_resp.raise_for_status()
            order = query_resp.json()
            executed_qty = float(order.get('executedQty', 0))
            avg_price = float(order.get('avgPrice', 0))
            order_status = order.get('status', '')

        if executed_qty == 0 or avg_price == 0:
            log(f"MARKET order FAILED to fill: {symbol} {side} | executedQty={executed_qty} avgPrice={avg_price}", "error")
            log(f"Order status: {order_status}", "error")
            log(f"Order response: {order}", "error")
            raise Exception(f"Market order did not execute (qty={executed_qty}, price={avg_price}, status={order_status})")

        log(f"MARKET order filled: {symbol} {side} @ {avg_price} | Executed qty={executed_qty}")

        return order

    def place_tp_sl_orders(self, symbol: str, direction: str,
                          tp_price: float, sl_price: float, quantity: float):
        """
        Place both TP (LIMIT) and SL (STOP_MARKET) orders
        CRITICAL: TP uses LIMIT order (maker fee 0.02%), not TAKE_PROFIT_MARKET
        """
        # Get tick size and step size for proper rounding
        tick_size = self.symbol_info_cache[symbol]["tickSize"]
        step_size = self.symbol_info_cache[symbol]["stepSize"]
        price_precision = self.symbol_info_cache[symbol]["pricePrecision"]
        qty_precision = self.symbol_info_cache[symbol]["quantityPrecision"]

        # Round to tick size and step size
        tp_price_rounded = self._round_to_tick_size(tp_price, tick_size)
        sl_price_rounded = self._round_to_tick_size(sl_price, tick_size)
        quantity_rounded = self._round_to_step_size(quantity, step_size)

        # Format as strings
        tp_price_str = f"{tp_price_rounded:.{price_precision}f}"
        sl_price_str = f"{sl_price_rounded:.{price_precision}f}"
        quantity_str = f"{quantity_rounded:.{qty_precision}f}"

        # TAKE PROFIT - LIMIT ORDER (maker fee 0.02%)
        tp_side = "SELL" if direction == "LONG" else "BUY"
        tp_params = {
            "symbol": symbol,
            "side": tp_side,
            "type": "LIMIT",
            "price": tp_price_str,
            "quantity": quantity_str,
            "timeInForce": "GTC",
            "reduceOnly": "true",
        }
        tp_params = self._sign_params(tp_params)

        try:
            resp = self.client.post(
                f"{config.BINANCE_BASE_URL}/fapi/v1/order",
                params=tp_params,
                headers=self._headers()
            )
            resp.raise_for_status()
            log(f"TP LIMIT order placed: {symbol} @ {tp_price_str}")
        except httpx.HTTPStatusError as e:
            try:
                error_data = e.response.json()
                log(f"TP order failed - Binance error: {error_data}", "error")
            except:
                log(f"TP order failed - Response: {e.response.text}", "error")
            raise

        # STOP LOSS - Only place if enabled in config
        # Skip if SL_PCT >= 1.0 (effectively disabled)
        if config.SL_PCT >= 1.0:
            log(f"SL order skipped: SL_PCT={config.SL_PCT} (stop-loss disabled)")
            return

        # STOP LOSS - STOP_LIMIT via Algo Order API (prevents excessive slippage)
        # Set limit price 0.5% below trigger to cap worst-case fill price
        sl_side = "SELL" if direction == "LONG" else "BUY"

        # Calculate limit price with buffer
        if direction == "LONG":
            # For LONG: limit price is below trigger (worse price)
            sl_limit_price = sl_price_rounded * (1 - config.SL_LIMIT_BUFFER_PCT)
        else:
            # For SHORT: limit price is above trigger (worse price)
            sl_limit_price = sl_price_rounded * (1 + config.SL_LIMIT_BUFFER_PCT)

        # Round limit price to tick size
        sl_limit_price = self._round_to_tick_size(sl_limit_price, tick_size)
        sl_limit_str = f"{sl_limit_price:.{price_precision}f}"

        sl_params = {
            "symbol": symbol,
            "side": sl_side,
            "algoType": "CONDITIONAL",
            "type": "STOP",  # STOP order (STOP_LIMIT for algo orders)
            "triggerPrice": sl_price_str,
            "price": sl_limit_str,  # Limit price caps worst-case fill
            "quantity": quantity_str,
            "workingType": "MARK_PRICE",
        }
        sl_params = self._sign_params(sl_params)

        resp = self.client.post(
            f"{config.BINANCE_BASE_URL}/fapi/v1/algoOrder",
            params=sl_params,
            headers=self._headers()
        )
        resp.raise_for_status()
        sl_order = resp.json()
        algo_id = sl_order.get("algoId")
        log(f"SL STOP_LIMIT algo order placed: {symbol} trigger={sl_price_str} limit={sl_limit_str} (algoId: {algo_id})")

    def close_position_market(self, symbol: str, direction: str, quantity: float) -> dict:
        """
        Close position at market for timeout
        Args:
            symbol: Trading pair
            direction: Original position direction ("LONG" or "SHORT")
            quantity: Position quantity to close
        Returns:
            Order response dict
        """
        # Opposite side to close: LONG position → SELL, SHORT position → BUY
        side = "SELL" if direction == "LONG" else "BUY"
        qty_precision = self.symbol_info_cache[symbol]["quantityPrecision"]

        log(f"Closing {direction} position at market: {symbol} {side} qty={quantity:.{qty_precision}f}")

        # Place market order with exact quantity and reduceOnly flag
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{quantity:.{qty_precision}f}",
            "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        }
        params = self._sign_params(params)

        resp = self.client.post(
            f"{config.BINANCE_BASE_URL}/fapi/v1/order",
            params=params,
            headers=self._headers()
        )

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Check for error -2022 (ReduceOnly rejected - position already closed)
            try:
                error_data = e.response.json()
                error_code = error_data.get('code')

                if error_code == -2022:
                    log(f"Error -2022: Position already closed (likely by SL algo order)", "warning")

                    # Verify position is actually closed
                    position = self.get_position(symbol)
                    if position and float(position.get("positionAmt", 0)) == 0:
                        log(f"Confirmed: {symbol} position is closed (positionAmt = 0)")

                        # Get actual exit price from last trade
                        last_trade = self.get_last_trade(symbol)
                        if last_trade:
                            exit_price = float(last_trade["price"])
                            executed_qty = float(last_trade["qty"])
                            log(f"Retrieved actual exit from trade history: {symbol} @ {exit_price} | Qty: {executed_qty}")

                            # Return synthetic order response with actual exit data
                            return {
                                "avgPrice": exit_price,
                                "executedQty": executed_qty,
                                "status": "FILLED",
                                "alreadyClosed": True  # Flag to indicate position was already closed
                            }
                        else:
                            log(f"ERROR: Could not retrieve exit price from trade history", "error")
                            raise Exception(f"Position closed but cannot determine exit price for {symbol}")
                    else:
                        log(f"ERROR: Position NOT confirmed closed despite -2022 error", "error")
                        raise
                else:
                    # Other errors - log and re-raise
                    log(f"Binance API Error: {error_data}", "error")
                    raise
            except ValueError:
                # Failed to parse JSON response
                log(f"Binance API Error: {e.response.text}", "error")
                raise

        order = resp.json()
        avg_price = float(order.get('avgPrice', 0))
        log(f"Position closed at market: {symbol} @ {avg_price}")

        return order

    def cancel_all_orders(self, symbol: str):
        """Cancel all open orders for symbol (both regular and algo orders)"""
        params = {"symbol": symbol}
        params = self._sign_params(params)

        # Cancel regular orders (TP LIMIT orders)
        try:
            resp = self.client.delete(
                f"{config.BINANCE_BASE_URL}/fapi/v1/allOpenOrders",
                params=params,
                headers=self._headers()
            )
            resp.raise_for_status()
            log(f"Cancelled all regular orders for {symbol}")
        except Exception as e:
            log(f"Error cancelling regular orders for {symbol}: {e}", "warning")

        # Cancel algo orders (SL STOP_MARKET orders)
        try:
            # Need to re-sign params for second request
            params = {"symbol": symbol}
            params = self._sign_params(params)

            resp = self.client.delete(
                f"{config.BINANCE_BASE_URL}/fapi/v1/algoOpenOrders",
                params=params,
                headers=self._headers()
            )
            resp.raise_for_status()
            log(f"Cancelled all algo orders for {symbol}")
        except Exception as e:
            log(f"Error cancelling algo orders for {symbol}: {e}", "warning")

    def get_position(self, symbol: str) -> Optional[dict]:
        """Get position info for symbol"""
        params = {"symbol": symbol}
        params = self._sign_params(params)

        try:
            resp = self.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v2/positionRisk",
                params=params,
                headers=self._headers()
            )
            resp.raise_for_status()
            positions = resp.json()

            if positions and len(positions) > 0:
                return positions[0]
            return None
        except httpx.HTTPStatusError as e:
            log(f"HTTP error getting position for {symbol}: {e.response.status_code} - {e.response.text}", "error")
            return None
        except Exception as e:
            log(f"Error getting position for {symbol}: {e}", "error")
            return None

    def get_all_open_positions(self) -> list:
        """Get ALL open positions across all symbols (positionAmt != 0)"""
        params = {}
        params = self._sign_params(params)

        try:
            resp = self.client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v2/positionRisk",
                params=params,
                headers=self._headers()
            )
            resp.raise_for_status()
            all_positions = resp.json()

            # Filter only positions with non-zero quantity
            open_positions = [p for p in all_positions if float(p["positionAmt"]) != 0]
            return open_positions
        except Exception as e:
            log(f"Error getting all positions: {e}", "error")
            return []

    def get_open_orders(self, symbol: str) -> list:
        """Get all open orders for symbol"""
        params = {"symbol": symbol}
        params = self._sign_params(params)

        resp = self.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/openOrders",
            params=params,
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_last_trade(self, symbol: str) -> Optional[dict]:
        """Get last trade for symbol (for determining win/loss)"""
        params = {"symbol": symbol, "limit": 1}
        params = self._sign_params(params)

        resp = self.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v1/userTrades",
            params=params,
            headers=self._headers()
        )
        resp.raise_for_status()
        trades = resp.json()

        if trades:
            return trades[0]
        return None

    def get_account_balance(self) -> float:
        """Get available USDT balance"""
        params = {}
        params = self._sign_params(params)

        resp = self.client.get(
            f"{config.BINANCE_BASE_URL}/fapi/v2/balance",
            params=params,
            headers=self._headers()
        )
        resp.raise_for_status()
        balances = resp.json()

        for balance in balances:
            if balance["asset"] == "USDT":
                return float(balance["availableBalance"])

        return 0.0

# Test (CAUTION: This places a REAL $20 trade on Binance)
if __name__ == "__main__":
    print(f"\n{'='*80}")
    print(f"ORDER EXECUTOR TEST")
    print(f"{'='*80}")
    print(f"⚠️  WARNING: This will place a REAL trade on Binance!")
    print(f"⚠️  Level 0: $1 margin, $20 notional at 20x leverage")
    print(f"⚠️  Press Ctrl+C to cancel, or Enter to continue...")
    input()

    executor = OrderExecutor()

    try:
        # Get account balance
        balance = executor.get_account_balance()
        print(f"\nAvailable balance: ${balance:.2f}")

        if balance < 2.0:
            print(f"ERROR: Insufficient balance (need at least $2)")
            exit(1)

        # Test with a liquid low-price pair (example: DOGEUSDT)
        test_symbol = "DOGEUSDT"
        test_direction = "LONG"
        test_notional = 20.0  # Level 0 notional

        print(f"\nTest trade: {test_symbol} {test_direction} ${test_notional}")

        # Set leverage and margin type
        executor.set_leverage(test_symbol, config.LEVERAGE)
        executor.set_margin_type(test_symbol, "ISOLATED")

        # Place market entry
        entry_order = executor.place_market_order(
            symbol=test_symbol,
            side="BUY" if test_direction == "LONG" else "SELL",
            notional_usd=test_notional
        )

        entry_price = float(entry_order["avgPrice"])
        entry_qty = float(entry_order["executedQty"])

        print(f"\nEntry filled: {entry_price:.6f} | Qty: {entry_qty:.2f}")

        # Calculate TP/SL
        tp_price = entry_price * (1 + config.TP_PCT) if test_direction == "LONG" else entry_price * (1 - config.TP_PCT)
        sl_price = entry_price * (1 - config.SL_PCT) if test_direction == "LONG" else entry_price * (1 + config.SL_PCT)

        print(f"TP: {tp_price:.6f} ({config.TP_PCT*100:.2f}%)")
        print(f"SL: {sl_price:.6f} ({config.SL_PCT*100:.2f}%)")

        # Place TP/SL
        executor.place_tp_sl_orders(
            symbol=test_symbol,
            direction=test_direction,
            tp_price=tp_price,
            sl_price=sl_price,
            quantity=entry_qty
        )

        print(f"\n✓ Test complete! TP and SL orders placed.")
        print(f"⚠️  IMPORTANT: Cancel orders and close position manually:")
        print(f"   1. Go to Binance Futures")
        print(f"   2. Cancel all {test_symbol} orders")
        print(f"   3. Close {test_symbol} position at market")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        executor.close()
