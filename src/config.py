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

# Maker entries (added 2026-10-21): place entries as LIMIT post-only (maker, 0.02%)
# instead of MARKET (taker, 0.05%). Fees ate -$30 of the martingale's +$69 gross in the
# 08-30→10-21 run, so halving entry fees is the biggest net-P&L lever. A post-only order
# can go unfilled/partial → MUST have timeout+retry+MARKET-fallback or it strands the chain
# with orphaned/partial fills. Toggle False to instantly revert to taker entries.
USE_MAKER_ENTRIES = True          # False = old MARKET (taker) entries
MAKER_ENTRY_TIMEOUT_SECS = 45     # wait this long for a post-only entry to fill before repricing
MAKER_ENTRY_POLL_SECS = 3         # poll fill status every N seconds
MAKER_ENTRY_RETRIES = 3           # reprice-and-retry this many times, then MARKET-fallback the remainder
TP_PCT = 0.10                 # 10.0% gross take profit
SL_PCT = 0.04                 # 4.0% price-based stop loss (prevents catastrophes)

# Trailing stop — native Binance TRAILING_STOP_MARKET (server-side, follows price tick-by-tick).
# The 2.5m bot loop can NEVER trail a stop properly, so trailing is offloaded to Binance's engine:
# the bot arms ONE trailing order the moment a position crosses the activation threshold below,
# then Binance moves it continuously on its own. The +10% TP LIMIT stays in place, so a full run
# is never cut short — the trailing only closes on a real callback-sized retrace from the peak.
# Values are % of PRICE (× LEVERAGE = ROI %).
TRAILING_ENABLED = True
TRAILING_ACTIVATION_PCT = 0.012   # arm once price moves +1.2% in favor from entry (≈ +24% ROI at 20x)
TRAILING_CALLBACK_RATE = 4.0      # Binance callbackRate: close on a 4.0% retrace from the running peak.
                                   # Was 1.0 — too tight: meme coins wobble 1% constantly, so it closed
                                   # EVERY winner at ~+1% (0/18 wins reached the 10% TP over 6 days),
                                   # collapsing realized R:R to ~0.5:1 and breaking the martingale's
                                   # 2.5:1 recovery math. 4% lets winners run toward the +10% TP before
                                   # locking in. Binance hard limits: min 0.1, max 5.

# Strategy: inverted momentum / mean-reversion
# SHORT on overbought (RSI>65, BB>0.8), LONG on oversold (RSI<35, BB<0.2)

# Martingale parameters
BASE_SIZE_PCT = 0.05          # 5% of account balance per trade at level 0 (increased from 3% for faster growth)
MARTINGALE_MULTIPLIER = 1.25  # Position size multiplier per level (1.25x = 25% increase)
MAX_LEVEL = 2                 # Was 5 → 2 (2026-10-21). Monte Carlo (4000 bootstrapped orderings of the
                              # martingale-only trade sequence) found L2 best risk-adjusted: P(drawdown<-50%)
                              # drops from 33% (L5) to 8% (L2) while MEDIAN return stays ~flat (+93% vs +105%).
                              # L5 had the highest median but a 1-in-3 chance of a >50% DD. L3 is worst-of-both.
                              # Was 10 originally: recovery breaks past ~L5, single SL at L8 = ~24% of account.
LEVERAGE = 20                 # 20x leverage
COOLDOWN_AFTER_MAX_LOSS = 3600  # 1 hour cooldown after blowing a full chain
MAX_CHAIN_DURATION_HOURS = 48   # Force chain reset after 2 days (prevents 8-day chains)
MAX_POSITION_PCT = 0.25       # EMERGENCY BRAKE: Never risk more than 25% of account in one position
DAILY_LOSS_LIMIT_USD = 1000.0   # Effectively disabled - high limit
MAX_HOLD_CANDLES = 120        # Maximum candles to hold position before timeout close (5.0 hours at 2.5m scan interval)
BREAKEVEN_HOLD_CANDLES = 72   # Close early if still negative after this many candles (3.0 hours at 2.5m scan interval)
                               # NOTE: candles_held counts SCAN_INTERVAL_SECS (2.5m) cycles, NOT 5m klines.
                               # 30-day backtest: 72% of 10%+ moves take >3h to peak, so this must stay
                               # comfortably below MAX_HOLD_CANDLES or winners get cut before they mature.

# Scanner parameters
SCAN_INTERVAL_SECS = 150      # 2.5 minutes (150 seconds)
KLINE_INTERVAL = "5m"        # 5 minute candles
KLINE_LIMIT = 50              # Candles to fetch per pair
MIN_24H_VOLUME_USD = 10_000_000  # $10M+ required to filter out low-liquidity meme coins (now applies to curated list too)
MIN_QUOTE_VOLUME_24H = 10_000_000  # $10M USDT 24h minimum (raised from $2M 2026-08-06: $2M let thin pairs
                                    # like INXUSDT $9.5M / SOONUSDT $4.8M through, causing stop-slippage losses)
LOW_VOLUME_THRESHOLD = 500_000    # $500k - if 24h volume below this, widen SL by 1.5x
ORDERBOOK_DEPTH_MIN_USD = 1000    # Minimum $1k orderbook depth within 1% of mid price
ORDERBOOK_DEPTH_PCT = 0.01        # Check depth within 1% of mid price
MAX_SPREAD_PCT = 0.05            # Reject pairs with spread > 0.05%
MAX_SLIPPAGE_PCT = 0.1           # Reject pairs with estimated slippage > 0.1%
MIN_ATR_PCT = 0.3                # Minimum ATR% (volatility filter) - 0.3% for 1m candles (was 1.5% for 5m)
ATR_PERIOD = 20                  # ATR calculation period (20 candles)
QUOTE_ASSET = "USDT"

# Cooldown blacklist parameters
COOLDOWN_CANDLES = 144        # Was 4 (10 min) → 144 (~6h) on 2026-10-21: CONCENTRATION LIMIT. The 10-min
                              # cooldown let the bot reload the same losing pair endlessly (CHIP = 43 trades,
                              # 37% win, -$39 net, present in nearly every blowout chain). ~6h after a loss
                              # forces diversification into the ~100-pair curated list instead of re-piling.
COOLDOWN_DURATION_SECS = COOLDOWN_CANDLES * SCAN_INTERVAL_SECS  # 144 * 150sec = 21600 seconds (6 hours)

# SMA Trend Filter (vars kept for reference; SMA computation removed from pair_scanner)
SMA_PERIOD = 50
SMA_SLOPE_LOOKBACK = 10
SMA_SLOPE_THRESHOLD = 0.3

# Signal scorer weights (volume-first, hardcoded in signal_scorer.py)
# Volume: 40%, RSI: 25%, BB: 20%, Z-score: 15%
ENTRY_THRESHOLD = 20          # Minimum score to enter — replaces vol>1.5 gate

# Safety
BTC_DUMP_THRESHOLD_4H = -0.05  # Pause longs if BTC down >5% in 4h
BTC_PUMP_THRESHOLD_4H = 0.05   # Pause shorts if BTC up >5% in 4h

# Adaptive regime switching
CONSECUTIVE_LOSS_FLIP_THRESHOLD = 3  # Flip SHORT→LONG bias after this many losses
LONG_PENALTY_MULTIPLIER = 0.9        # LONG signals get 10% penalty (allows regime flip to work)
SHORT_PENALTY_MULTIPLIER = 0.6       # SHORT signals get 40% penalty when regime flipped

# Top 100 pairs ranked by 30-day move frequency (backtest-derived)
# How often each pair makes 10%+ moves in under 1 hour
# Use this curated list for faster scanning instead of dynamic discovery
USE_CURATED_PAIR_LIST = True  # Set to False to use dynamic pair discovery

CURATED_PAIR_LIST = [
    "RAVEUSDT", "SIRENUSDT", "ARIAUSDT", "BULLAUSDT", "STOUSDT",
    "BLESSUSDT", "BASUSDT", "ONUSDT", "NOMUSDT", "TRADOORUSDT",
    "BRUSDT", "AKEUSDT", "DUSDT", "PIPPINUSDT", "PLAYUSDT",
    "BASEDUSDT", "CYSUSDT", "AGTUSDT", "HIGHUSDT",
    "TAKEUSDT", "DRIFTUSDT", "QUSDT", "CHIPUSDT", "ORDIUSDT",
    "SKYAIUSDT", "MAGMAUSDT", "KOMAUSDT", "XNYUSDT", "UBUSDT",
    "LABUSDT", "JCTUSDT", "PIEVERSEUSDT", "ENJUSDT", "PTBUSDT",
    "APRUSDT", "MOVRUSDT", "BEATUSDT", "SOLVUSDT", "AIAUSDT",
    "CTSIUSDT", "GWEIUSDT", "GENIUSUSDT", "NAORISUSDT", "COLLECTUSDT",
    "MYXUSDT", "PROMUSDT", "AINUSDT", "BLUAIUSDT", "ONTUSDT",
    "PORTALUSDT", "GTCUSDT", "PHBUSDT", "MUSDT", "LYNUSDT",
    "CLOUSDT", "RIVERUSDT", "PRLUSDT", "TSTUSDT", "BIOUSDT",
    "BANKUSDT", "REDUSDT", "GUAUSDT", "1000SATSUSDT",
    "ZEREBROUSDT", "SPKUSDT", "BTRUSDT", "UAIUSDT", "NEIROUSDT",
    "FIDAUSDT", "GUNUSDT", "GIGGLEUSDT", "ALICEUSDT", "STABLEUSDT",
    "IRYSUSDT", "INXUSDT", "EDGEUSDT", "JOEUSDT", "BANUSDT",
    "SOONUSDT", "CUSDT", "HEMIUSDT", "EDUUSDT", "PNUTUSDT",
    "FIGHTUSDT", "TAUSDT", "GRIFFAINUSDT", "BROCCOLIF3BUSDT",
    "TAGUSDT", "AIOUSDT", "FOLKSUSDT", "USUSDT", "MEGAUSDT",
    "ONGUSDT", "KERNELUSDT", "EVAAUSDT"
]

# Excluded pairs (stablecoins and slow-moving pairs)
EXCLUDED_SYMBOLS = [
    # Blacklisted by user 2026-08-03: consistent net loser (-$29 over 7 days),
    # whipsaws through the 4% SL on thin liquidity. Still in CURATED_PAIR_LIST but
    # the scanner skips EXCLUDED_SYMBOLS (pair_scanner.py:129), so this wins.
    "SOONUSDT",
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
    # Chaotic pairs: massive moves with zero volume signal (undetectable + untradeable)
    "BSBUSDT",   # Makes 40-63% moves at 0.65x avg volume — pure noise, undetectable
    "SWARMSUSDT", # Makes 35-37% moves at sub-1x volume — same pattern
    "PUMPBTCUSDT", # Makes 34-35% SHORT moves at 0.08-0.5x volume — untradeable
]

