"""
Martingale Signal Scanner - Configuration
Single source of truth for all parameters
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Binance API (from environment)
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET")
BINANCE_BASE_URL = "https://fapi.binance.com"

# FEE-CORRECTED TP/SL — CRITICAL FOR MARTINGALE MATH
# Entry: MARKET (taker 0.05%)
# TP exit: LIMIT (maker 0.02%) → win-side fees = 0.07%
# SL exit: STOP_MARKET (taker 0.05%) → loss-side fees = 0.10%
# net_win = 10.0% - 0.07% = 9.93%
# net_loss = 4.0% + 0.10% = 4.10%
# Risk/Reward: 2.5:1 (excellent for martingale)
TAKER_FEE = 0.0005            # 0.05%
MAKER_FEE = 0.0002            # 0.02%
TP_PCT = 0.10                 # 10.0% gross take profit
SL_PCT = 0.04                 # 4.0% price-based stop loss (prevents catastrophes)

# Strategy mode
STRATEGY_MODE = "MEAN_REVERSION"  # "MEAN_REVERSION" or "TREND_FOLLOWING"
SIGNAL_DIRECTION = "inverted"  # "normal" or "inverted" - oversold → SHORT, overbought → LONG

# Martingale parameters
BASE_SIZE_PCT = 0.03          # 3% of account balance per trade at level 0 (dynamic sizing)
MARTINGALE_MULTIPLIER = 1.5   # Position size multiplier per level (1.5x = 50% increase)
MAX_LEVEL = 10                # Max 10 levels
LEVERAGE = 20                 # 20x leverage
COOLDOWN_AFTER_MAX_LOSS = 0  # 1 hour cooldown after blowing a full chain
MAX_POSITION_PCT = 0.25       # EMERGENCY BRAKE: Never risk more than 25% of account in one position
DAILY_LOSS_LIMIT_USD = 1000.0   # Effectively disabled - high limit
MAX_HOLD_CANDLES = 54         # Maximum candles to hold position before timeout close (2.25 hours at 2.5m)

# Scanner parameters
SCAN_INTERVAL_SECS = 150      # 2.5 minutes (150 seconds)
KLINE_INTERVAL = "5m"        # 5 minute candles
KLINE_LIMIT = 50              # Candles to fetch per pair
MIN_24H_VOLUME_USD = 10_000_000  # $10M+ required to filter out low-liquidity meme coins
LOW_VOLUME_THRESHOLD = 500_000    # $500k - if 24h volume below this, widen SL by 1.5x
ORDERBOOK_DEPTH_MIN_USD = 5000    # Minimum $5k orderbook depth within 1% of mid price
ORDERBOOK_DEPTH_PCT = 0.01        # Check depth within 1% of mid price
SL_LIMIT_BUFFER_PCT = 0.005       # 0.5% buffer below trigger for STOP_LIMIT orders
MAX_SPREAD_PCT = 0.05            # Reject pairs with spread > 0.05%
MAX_SLIPPAGE_PCT = 0.1           # Reject pairs with estimated slippage > 0.1%
MIN_ATR_PCT = 0.3                # Minimum ATR% (volatility filter) - 0.3% for 1m candles (was 1.5% for 5m)
ATR_PERIOD = 20                  # ATR calculation period (20 candles)
QUOTE_ASSET = "USDT"

# Cooldown blacklist parameters
COOLDOWN_CANDLES = 4          # Number of candles to block a pair after loss
COOLDOWN_DURATION_SECS = COOLDOWN_CANDLES * SCAN_INTERVAL_SECS  # 4 * 150sec = 600 seconds (10 min)

# SMA Trend Filter
SMA_PERIOD = 50                  # 50-period SMA for trend detection
SMA_SLOPE_LOOKBACK = 10          # Calculate slope over last 10 candles
SMA_SLOPE_THRESHOLD = 0.3        # Only block if slope magnitude > 0.3% (strong trend)

# Signal scorer weights (must sum to 1.0)
WEIGHTS = {
    "rsi": 0.30,
    "bollinger": 0.20,
    "zscore": 0.15,           # Reduced from 0.20
    "volume": 0.15,
    "spread": 0.15,           # Increased from 0.10
    "funding": 0.05,
}
ENTRY_THRESHOLD = 46.0        # Min composite score to enter (volume-first scoring system)

# Volatility bonus (10%+ hourly moves in last 7 days)
VOLATILITY_WEIGHT = 0.3       # Multiplier for volatility score bonus
VOLATILITY_REFRESH_HOURS = 24 # Refresh volatility scores every 24 hours
MIN_VOLATILITY_INSTANCES = 50   # Exclude pairs with fewer than 50 ten-percent hourly moves in 7 days (too slow)
MAX_VOLATILITY_INSTANCES = 2000 # Exclude pairs with more than 2000 instances (too chaotic, likely junk tokens)

# Z-score extreme filter
FILTER_ZSCORE_EXTREME = True  # Skip entries where |Z| > threshold
ZSCORE_EXTREME_THRESHOLD = 2.5  # Skip if absolute Z-score exceeds this value

# RSI thresholds (for inverted momentum)
RSI_LONG_THRESHOLD = 25       # Only enter on RSI < 25 (oversold → SHORT in inverted mode)
RSI_SHORT_THRESHOLD = 75      # Only enter on RSI > 75 (overbought → LONG in inverted mode)

# Safety
BTC_DUMP_THRESHOLD_4H = -0.05  # Pause longs if BTC down >5% in 4h
BTC_PUMP_THRESHOLD_4H = 0.05   # Pause shorts if BTC up >5% in 4h

# Excluded pairs (stablecoins and slow-moving pairs)
EXCLUDED_SYMBOLS = [
    # Stablecoins and pegged assets
    "USDCUSDT",  # Stablecoin pair
    "BUSDUSDT",  # Stablecoin pair
    "TUSDUSDT",  # Stablecoin pair
    "USDPUSDT",  # Stablecoin pair
    "PAXGUSDT",  # Pegged gold token - extremely low volatility
    "DAIUSDT",   # Stablecoin
    "FDUSDUSDT", # Stablecoin
    # Slow-moving/low-volatility pairs that block the scanner
    "TRXUSDT",   # Extremely low volatility, takes too long to reach TP
    # Problem pairs with leverage restrictions or API issues
    "DEGOUSDT",  # Leverage restrictions - causes 400 errors
    # Low liquidity pairs with excessive slippage
    "AIOTUSDT",  # Low liquidity - 2.28% slippage on SL execution (2026-04-12)
]

# Validate config on import
assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001, "Weights must sum to 1.0"
assert BINANCE_API_KEY, "BINANCE_API_KEY environment variable not set"
assert BINANCE_API_SECRET, "BINANCE_API_SECRET environment variable not set"
