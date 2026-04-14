# Complete Trading Strategy Documentation

## Overview

This bot implements a mean-reversion martingale strategy on Binance Futures with time-based exits and intelligent signal filtering.

## Core Strategy Logic

### 1. Time-Based Exit System

**Break-Even Protection (12 Candles = 1 Hour):**
```python
if candles_held >= 12 and unrealized_pnl < 0:
    close_position_at_market()
    record_as_loss()
```

**Timeout Protection (54 Candles = 4.5 Hours):**
```python
if manager.is_timed_out(current_time):
    close_position_at_market()
    record_as_loss()
```

**Why Time-Based?**
- Prevents positions from bleeding slowly
- Captures quick mean reversion moves
- Avoids large drawdowns from trending markets
- Forces capital rotation

### 2. Take Profit System

**2% LIMIT Order:**
```python
TP_PCT = 0.020  # 2% gross take profit
# Uses LIMIT order for maker fee (0.02%)
# Net profit after fees: ~1.93%
```

**Fee Structure:**
- Entry: MARKET (taker 0.05%)
- TP Exit: LIMIT (maker 0.02%)
- Total fees on win: 0.07%

### 3. Martingale Position Sizing

**Sizing Formula:**
```python
notional_size = BASE_SIZE_USD * (1.5 ** level) * LEVERAGE
margin_required = BASE_SIZE_USD * (1.5 ** level)
```

**Example Chain:**
- Level 0: $0.50 margin = $10 notional at 20x
- Level 1: $0.75 margin = $15 notional at 20x
- Level 2: $1.13 margin = $22.50 notional at 20x
- ...
- Level 10: $28.64 margin = $572.80 notional at 20x

**Total chain margin:** ~$114 for full 10-level chain

### 4. Signal Scoring System

**Composite Score (0-100):**

```python
score = (
    rsi_score * 0.30 +           # 30%
    bollinger_score * 0.20 +     # 20%
    zscore_score * 0.15 +        # 15%
    volume_score * 0.15 +        # 15%
    spread_score * 0.15 +        # 15%
    funding_score * 0.05         # 5%
)
```

**Entry Threshold:** 55.0 (lowered for more signals)

**Individual Scoring:**

**RSI (Inverted Mode):**
```python
# Oversold → SHORT signal
if rsi < 25:
    direction = "SHORT"
    score = (25 - rsi) / 25 * 100

# Overbought → LONG signal
if rsi > 75:
    direction = "LONG"
    score = (rsi - 75) / 25 * 100
```

**Bollinger Bands:**
```python
bb_pct_b = (close - bb_lower) / (bb_upper - bb_lower)

# Below lower band → SHORT (inverted)
if bb_pct_b < 0.1:
    score = (0.1 - bb_pct_b) / 0.1 * 100
    direction = "SHORT"

# Above upper band → LONG (inverted)
if bb_pct_b > 0.9:
    score = (bb_pct_b - 0.9) / 0.1 * 100
    direction = "LONG"
```

**Z-Score:**
```python
zscore = (close - sma_50) / std_50

# Extreme deviation scores higher
score = min(abs(zscore) / 3 * 100, 100)
```

**Volume:**
```python
volume_ratio = current_volume / avg_volume_20

# High volume = stronger signal
score = min(volume_ratio / 2 * 100, 100)
```

**Spread:**
```python
spread_pct = (ask - bid) / mid_price

# Tighter spread = higher quality
if spread_pct < 0.02:
    score = 100 - (spread_pct / 0.02 * 50)
```

**Funding Rate:**
```python
# Negative funding → LONG bias
# Positive funding → SHORT bias
score = (1 - abs(funding_rate) / 0.001) * 100
```

### 5. Regime Detection

**Automatic Signal Inversion:**

```python
# Calculate BTC 24h volatility and trend
atr_pct = calculate_atr(btc_24h) / btc_price * 100
slope_pct = calculate_slope(btc_24h) / btc_price * 100

if atr_pct > 1.5% and abs(slope_pct) > 0.3%:
    mode = "inverted"  # Trending → mean reversion
else:
    mode = "normal"    # Ranging → trend following
```

**Why Inversion?**
- Strong trends mean overextensions
- Oversold in uptrend = SHORT opportunity
- Overbought in downtrend = LONG opportunity

### 6. Multi-Layer Filtering

**ATR Filter:**
```python
MIN_ATR_PCT = 0.3  # Minimum 0.3% volatility
# Rejects dead/stablecoin pairs
```

**Spread Filter:**
```python
MAX_SPREAD_PCT = 0.05  # Max 0.05% bid-ask spread
# Ensures liquidity
```

**Slippage Filter:**
```python
MAX_SLIPPAGE_PCT = 0.1  # Max 0.1% estimated slippage
# Protects from thin orderbooks
```

**Volume Filter:**
```python
MIN_24H_VOLUME_USD = 10_000_000  # $10M minimum
# Filters out meme coins and low liquidity
```

### 7. Cooldown Blacklist

**After Each Loss:**
```python
cooldown_duration = COOLDOWN_CANDLES * SCAN_INTERVAL_SECS
# 4 candles * 300 seconds = 20 minutes

blacklist[symbol] = current_time + cooldown_duration
```

**Purpose:**
- Avoids re-entering losing pairs immediately
- Lets market structure reset
- Prevents chain doubling on same symbol

### 8. MAE Tracking

**Maximum Adverse Excursion:**

```python
# During position holding
drawdown_pct = calculate_drawdown(entry, current_price)

if drawdown_pct < max_adverse_excursion:
    max_adverse_excursion = drawdown_pct
    mae_candle = current_candle
```

**Logged on Exit:**
```
WIN: BTCUSDT LONG @ 50870.00 | PnL=$0.42 | Level=0 → 0
MAE: -0.87% (candle 3 of 8)
```

**Analysis:**
- Shows worst drawdown before TP
- Identifies optimal SL placement
- Tracks position efficiency

### 9. Safety Checks

**BTC Correlation Protection:**

```python
btc_4h_change = (btc_close_4h - btc_open_4h) / btc_open_4h

if btc_4h_change < -0.05:  # -5%
    block_longs = True

if btc_4h_change > 0.05:   # +5%
    block_shorts = True
```

**Daily Loss Limit:**
```python
if daily_pnl < -DAILY_LOSS_LIMIT_USD:
    block_all_entries = True
```

### 10. State Persistence

**Saved Every Cycle:**
```json
{
  "level": 0,
  "in_position": true,
  "current_symbol": "BTCUSDT",
  "current_direction": "LONG",
  "entry_price": 50000.0,
  "entry_quantity": 0.0004,
  "current_size_usd": 10.0,
  "entry_candle_time": 1709683200.0,
  "max_adverse_excursion_pct": -0.87,
  "mae_candle": 3,
  "cooldown_blacklist": {
    "ETHUSDT": 1709684400.0
  }
}
```

**Crash Recovery:**
- Bot restarts with exact state
- Verifies against exchange positions
- Adopts exchange reality if mismatch

## Risk Management

### Position Sizing Safety
- Max $114 total margin for full chain
- Fits in $200+ account
- Leaves buffer for volatility

### Time Limits
- 12-candle break-even prevents slow bleeds
- 54-candle timeout caps max exposure
- Forces capital rotation

### Quality Filters
- Only $10M+ volume pairs
- Tight spreads required
- Low slippage verification
- No stablecoins or pegged assets

### Blacklist System
- Prevents revenge trading
- 20-minute cooldown after loss
- Symbol-specific tracking

## Performance Optimization

### Fee Optimization
- TP uses LIMIT orders (maker fee)
- Saves 0.03% per winning trade
- Symmetric win/loss after fees

### Entry Quality
- Composite 55+ score required
- Multiple confirmations needed
- Regime-adaptive signals

### Capital Efficiency
- 20x leverage on liquid pairs
- Small base size allows scaling
- Martingale recovers losses quickly

## Monitoring

### Key Metrics Logged
- Entry/exit prices
- Hold duration (candles)
- MAE (worst drawdown)
- Win rate
- Total PnL
- Current level
- Blacklist size

### Alert Conditions
- Multiple positions detected
- State mismatch with exchange
- Max level exceeded
- Daily loss limit hit

## Excluded Pairs

**Stablecoins:**
- USDCUSDT, BUSDUSDT, TUSDUSDT, DAIUSDT, FDUSDUSDT

**Low Volatility:**
- TRXUSDT (too slow to reach TP)
- PAXGUSDT (pegged gold, no movement)

**Restricted:**
- DEGOUSDT (leverage restrictions)

---

**Strategy Type:** Mean-reversion martingale
**Risk Level:** Medium-High (martingale scaling)
**Time Frame:** 5-minute candles
**Best For:** Ranging/choppy markets
**Avg Hold Time:** 1-4 hours
