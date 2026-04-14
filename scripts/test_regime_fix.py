"""
Test the updated regime detection logic
"""
import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_loop import detect_market_regime
from order_executor import OrderExecutor

async def main():
    print("="*80)
    print("TESTING NEW REGIME DETECTION LOGIC")
    print("="*80)
    print()

    executor = OrderExecutor()

    try:
        # Test regime detection
        regime_data = detect_market_regime(executor)

        print("="*80)
        print("REGIME DETECTION RESULTS")
        print("="*80)
        print(f"Regime:           {regime_data['regime']}")
        print(f"Trend Direction:  {regime_data['trend_direction']}")
        print(f"BTC ATR%:         {regime_data['atr_pct']:.4f}%")
        print(f"BTC Slope%:       {regime_data['slope_pct']:.4f}%")
        print()
        print("="*80)
        print("PENALTY APPLICATION")
        print("="*80)

        trend = regime_data['trend_direction']
        if trend == 'uptrend':
            print("[UPTREND DETECTED]")
            print("  - LONG signals:  NO PENALTY (100% strength)")
            print("  - SHORT signals: 70% PENALTY (30% strength)")
            print("  --> BOT WILL FAVOR LONGS")
        elif trend == 'downtrend':
            print("[DOWNTREND DETECTED]")
            print("  - LONG signals:  70% PENALTY (30% strength)")
            print("  - SHORT signals: NO PENALTY (100% strength)")
            print("  --> BOT WILL FAVOR SHORTS")
        else:
            print("[RANGING DETECTED]")
            print("  - LONG signals:  70% PENALTY (30% strength)")
            print("  - SHORT signals: NO PENALTY (100% strength)")
            print("  --> BOT WILL FAVOR SHORTS (mean-reversion)")

        print()
        print("="*80)
        print("THRESHOLDS")
        print("="*80)
        print("ATR Threshold:    0.5% (LOWERED from 1.5%)")
        print("Slope Threshold:  0.1% (LOWERED from 0.3%)")
        print()
        print(f"Current ATR:      {regime_data['atr_pct']:.4f}% {'> threshold (trending)' if regime_data['atr_pct'] > 0.5 else '< threshold (ranging)'}")
        print(f"Current |Slope|:  {abs(regime_data['slope_pct']):.4f}% {'> threshold (trending)' if abs(regime_data['slope_pct']) > 0.1 else '< threshold (ranging)'}")
        print()

        if regime_data['slope_pct'] > 0.09:
            print("[SUCCESS] BTC slope is positive and will trigger UPTREND detection!")
            print("          Bot will now FAVOR LONGS in bull markets.")
        else:
            print("[INFO] BTC slope is currently below +0.1%, no uptrend detected yet.")
            print("       When slope crosses +0.1%, bot will switch to favoring LONGS.")

    finally:
        executor.close()

if __name__ == "__main__":
    asyncio.run(main())
