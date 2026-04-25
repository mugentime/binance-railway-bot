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

# Strategy: inverted momentum / mean-reversion
# SHORT on overbought (RSI>65, BB>0.8), LONG on oversold (RSI<35, BB<0.2)

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

# Signal scorer weights (volume-first, hardcoded in signal_scorer.py)
# Volume: 40%, RSI: 25%, BB: 20%, Z-score: 15%
ENTRY_THRESHOLD = 0           # No threshold - volume_ratio > 1.5 is the only gate, score ranks pairs

# Safety
BTC_DUMP_THRESHOLD_4H = -0.05  # Pause longs if BTC down >5% in 4h
BTC_PUMP_THRESHOLD_4H = 0.05   # Pause shorts if BTC up >5% in 4h

# Top 100 pairs ranked by 30-day move frequency (backtest-derived)
# How often each pair makes 10%+ moves in under 1 hour
# Use this curated list for faster scanning instead of dynamic discovery
USE_CURATED_PAIR_LIST = True  # Set to False to use dynamic pair discovery

CURATED_PAIR_LIST = [
    "RAVEUSDT", "SIRENUSDT", "ARIAUSDT", "BULLAUSDT", "STOUSDT",
    "BLESSUSDT", "BASUSDT", "ONUSDT", "NOMUSDT", "TRADOORUSDT",
    "BRUSDT", "AKEUSDT", "DUSDT", "PIPPINUSDT", "PLAYUSDT",
    "BSBUSDT", "BASEDUSDT", "CYSUSDT", "AGTUSDT", "HIGHUSDT",
    "TAKEUSDT", "DRIFTUSDT", "QUSDT", "CHIPUSDT", "ORDIUSDT",
    "SKYAIUSDT", "MAGMAUSDT", "KOMAUSDT", "XNYUSDT", "UBUSDT",
    "LABUSDT", "JCTUSDT", "PIEVERSEUSDT", "ENJUSDT", "PTBUSDT",
    "APRUSDT", "MOVRUSDT", "BEATUSDT", "SOLVUSDT", "AIAUSDT",
    "CTSIUSDT", "GWEIUSDT", "GENIUSUSDT", "NAORISUSDT", "COLLECTUSDT",
    "MYXUSDT", "PROMUSDT", "AINUSDT", "BLUAIUSDT", "ONTUSDT",
    "PORTALUSDT", "GTCUSDT", "PHBUSDT", "MUSDT", "LYNUSDT",
    "CLOUSDT", "RIVERUSDT", "PRLUSDT", "TSTUSDT", "BIOUSDT",
    "BANKUSDT", "SWARMSUSDT", "REDUSDT", "GUAUSDT", "1000SATSUSDT",
    "ZEREBROUSDT", "SPKUSDT", "BTRUSDT", "UAIUSDT", "NEIROUSDT",
    "FIDAUSDT", "GUNUSDT", "GIGGLEUSDT", "ALICEUSDT", "STABLEUSDT",
    "IRYSUSDT", "INXUSDT", "EDGEUSDT", "JOEUSDT", "BANUSDT",
    "SOONUSDT", "CUSDT", "HEMIUSDT", "EDUUSDT", "PNUTUSDT",
    "FIGHTUSDT", "TAUSDT", "GRIFFAINUSDT", "BROCCOLIF3BUSDT",
    "TAGUSDT", "AIOUSDT", "FOLKSUSDT", "USUSDT", "MEGAUSDT",
    "ONGUSDT", "KERNELUSDT", "PUMPBTCUSDT", "EVAAUSDT"
]

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

