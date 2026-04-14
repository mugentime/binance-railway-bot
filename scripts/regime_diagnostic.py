"""
Regime Detection Diagnostic Tool
Shows current BTC regime and signal scores with/without penalties
"""
import asyncio
import numpy as np
import httpx
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import config
from pair_scanner import PairScanner
from signal_scorer import SignalScorer

async def main():
    print("="*100)
    print("REGIME DETECTION DIAGNOSTIC")
    print("="*100)
    print()

    # 1. Fetch BTC data and detect regime
    print("[*] FETCHING BTC DATA FOR REGIME DETECTION...")
    print()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.BINANCE_BASE_URL}/fapi/v1/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "limit": 24
                }
            )
            resp.raise_for_status()
            candles = resp.json()

        # Extract data
        closes = np.array([float(c[4]) for c in candles])
        highs = np.array([float(c[2]) for c in candles])
        lows = np.array([float(c[3]) for c in candles])

        # Calculate ATR
        high_low = highs - lows
        high_close = np.abs(highs[1:] - closes[:-1])
        low_close = np.abs(lows[1:] - closes[:-1])
        true_ranges = np.maximum(high_low[1:], np.maximum(high_close, low_close))
        atr = np.mean(true_ranges)
        current_price = closes[-1]
        atr_pct = (atr / current_price) * 100

        # Calculate SMA slope
        x = np.arange(len(closes))
        slope, _ = np.polyfit(x, closes, 1)
        slope_pct = (slope / current_price) * 100

        # Regime thresholds
        ATR_THRESHOLD = 1.5
        SLOPE_THRESHOLD = 0.3

        if atr_pct > ATR_THRESHOLD and abs(slope_pct) > SLOPE_THRESHOLD:
            regime = "INVERTED (TRENDING)"
            signal_direction = "inverted"
        else:
            regime = "NORMAL (RANGING)"
            signal_direction = "normal"

        print(f"BTC CURRENT PRICE: ${current_price:,.2f}")
        print(f"BTC ATR%:          {atr_pct:.2f}% (threshold: {ATR_THRESHOLD}%)")
        print(f"BTC SMA SLOPE%:    {slope_pct:.4f}% per candle (threshold: ±{SLOPE_THRESHOLD}%)")
        print()
        print(f"[REGIME] {regime}")
        print()

        if regime == "NORMAL (RANGING)":
            print("[!] RANGING MARKET DETECTED:")
            print("    - ATR% is below threshold (low volatility)")
            print("    - SMA slope is flat (no strong trend)")
            print("    - LONG signals will be PENALIZED by 70% (multiplied by 0.3)")
            print("    - SHORT signals are NOT penalized")
        else:
            print("[OK] TRENDING MARKET DETECTED:")
            print("    - ATR% is above threshold (high volatility)")
            print("    - SMA slope shows strong trend")
            print("    - Signal direction inverted for trend-following")
            print("    - No penalties applied")

        print()
        print("="*100)
        print()

        # 2. Scan pairs and score
        print("[*] SCANNING PAIRS AND GENERATING SIGNALS...")
        print()

        scanner = PairScanner()
        scorer = SignalScorer()

        try:
            # Scan all pairs
            pair_data = await scanner.scan_all_pairs()

            # Score all pairs - get ALL scores (not just filtered)
            all_signals = []

            for symbol, data in pair_data.items():
                closes_data = data["closes"]
                volumes = data["volumes"]
                spread_pct = data["spread_pct"]
                funding_rate = data["funding_rate"]
                sma_slope_pct = data.get("sma_slope_pct", 0.0)

                # Calculate indicators
                rsi = scorer.calculate_rsi(closes_data)
                bb_pct_b = scorer.calculate_bollinger_pct_b(closes_data)
                zscore = scorer.calculate_zscore(closes_data)
                volume_ratio = scorer.calculate_volume_ratio(volumes)

                # Score LONG (before penalty)
                long_scores = scorer.normalize_long_score(
                    rsi, bb_pct_b, zscore, volume_ratio, spread_pct, funding_rate
                )
                long_composite_raw = scorer.calculate_composite_score(long_scores)

                # Apply penalty if ranging market
                long_composite_final = long_composite_raw
                penalty_applied = False
                if signal_direction == 'normal':
                    long_composite_final = long_composite_raw * 0.3
                    penalty_applied = True

                # Apply trend filter
                trend_blocked = False
                if sma_slope_pct < -config.SMA_SLOPE_THRESHOLD:
                    long_composite_final = 0.0
                    trend_blocked = True

                all_signals.append({
                    'symbol': symbol,
                    'direction': 'LONG',
                    'score_raw': long_composite_raw,
                    'score_final': long_composite_final,
                    'penalty_applied': penalty_applied,
                    'trend_blocked': trend_blocked,
                    'rsi': rsi,
                    'bb_pct_b': bb_pct_b,
                    'zscore': zscore,
                    'volume_ratio': volume_ratio,
                    'spread_pct': spread_pct,
                    'funding_rate': funding_rate,
                    'sma_slope_pct': sma_slope_pct
                })

                # Score SHORT (no penalty in ranging markets)
                short_scores = scorer.normalize_short_score(
                    rsi, bb_pct_b, zscore, volume_ratio, spread_pct, funding_rate
                )
                short_composite = scorer.calculate_composite_score(short_scores)

                # Apply trend filter
                trend_blocked_short = False
                if sma_slope_pct > config.SMA_SLOPE_THRESHOLD:
                    short_composite = 0.0
                    trend_blocked_short = True

                all_signals.append({
                    'symbol': symbol,
                    'direction': 'SHORT',
                    'score_raw': short_composite,
                    'score_final': short_composite,
                    'penalty_applied': False,
                    'trend_blocked': trend_blocked_short,
                    'rsi': rsi,
                    'bb_pct_b': bb_pct_b,
                    'zscore': zscore,
                    'volume_ratio': volume_ratio,
                    'spread_pct': spread_pct,
                    'funding_rate': funding_rate,
                    'sma_slope_pct': sma_slope_pct
                })

            # Sort by raw score
            all_signals.sort(key=lambda x: x['score_raw'], reverse=True)

            # Get top 5 LONG and top 5 SHORT by raw score
            long_signals = [s for s in all_signals if s['direction'] == 'LONG'][:5]
            short_signals = [s for s in all_signals if s['direction'] == 'SHORT'][:5]

            print("="*100)
            print("TOP 5 LONG SIGNALS (BEFORE PENALTY)")
            print("="*100)
            print(f"{'Rank':<6} {'Symbol':<15} {'Raw Score':<12} {'Final Score':<12} {'Penalty':<10} {'Blocked':<10} {'RSI':<8} {'BB%B':<8} {'Z-Score':<10}")
            print("-"*100)

            if not long_signals:
                print("[X] NO LONG SIGNALS GENERATED")
                print()
                print("POSSIBLE REASONS:")
                print("  1. All pairs have strongly negative SMA slope (< -0.3%)")
                print("  2. No pairs meet the LONG signal criteria (oversold conditions)")
                print("  3. Filtering pipeline removed all potential LONG candidates")
            else:
                for i, sig in enumerate(long_signals, 1):
                    penalty_str = "YES 70%" if sig['penalty_applied'] else "NO"
                    blocked_str = "YES Trend" if sig['trend_blocked'] else "NO"
                    print(f"{i:<6} {sig['symbol']:<15} {sig['score_raw']:<12.2f} {sig['score_final']:<12.2f} {penalty_str:<10} {blocked_str:<10} "
                          f"{sig['rsi']:<8.2f} {sig['bb_pct_b']:<8.2f} {sig['zscore']:<10.2f}")

            print()
            print("="*100)
            print("TOP 5 SHORT SIGNALS (NO PENALTY APPLIED)")
            print("="*100)
            print(f"{'Rank':<6} {'Symbol':<15} {'Score':<12} {'Blocked':<10} {'RSI':<8} {'BB%B':<8} {'Z-Score':<10}")
            print("-"*100)

            for i, sig in enumerate(short_signals, 1):
                blocked_str = "YES Trend" if sig['trend_blocked'] else "NO"
                print(f"{i:<6} {sig['symbol']:<15} {sig['score_raw']:<12.2f} {blocked_str:<10} "
                      f"{sig['rsi']:<8.2f} {sig['bb_pct_b']:<8.2f} {sig['zscore']:<10.2f}")

            print()
            print("="*100)
            print("ANALYSIS SUMMARY")
            print("="*100)

            # Count total LONG signals
            total_long = len([s for s in all_signals if s['direction'] == 'LONG'])
            penalized_long = len([s for s in all_signals if s['direction'] == 'LONG' and s['penalty_applied']])
            blocked_long = len([s for s in all_signals if s['direction'] == 'LONG' and s['trend_blocked']])

            print(f"Total LONG signals generated:     {total_long}")
            print(f"LONG signals with penalty:        {penalized_long} (score reduced by 70%)")
            print(f"LONG signals trend-blocked:       {blocked_long} (score set to 0)")
            print()
            print(f"Total SHORT signals generated:    {len([s for s in all_signals if s['direction'] == 'SHORT'])}")
            print(f"SHORT signals trend-blocked:      {len([s for s in all_signals if s['direction'] == 'SHORT' and s['trend_blocked']])}")
            print()

            if penalized_long > 0 and long_signals:
                print("[!] KEY INSIGHT:")
                print(f"   In RANGING markets, LONG signals are heavily penalized.")
                print(f"   Best LONG score BEFORE penalty: {long_signals[0]['score_raw']:.2f}")
                print(f"   Best LONG score AFTER penalty:  {long_signals[0]['score_final']:.2f}")
                print(f"   Reduction: {((long_signals[0]['score_raw'] - long_signals[0]['score_final']) / long_signals[0]['score_raw'] * 100):.1f}%")
                print()
                print(f"   This is why SHORT signals dominate in ranging markets.")

        finally:
            await scanner.close()

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
