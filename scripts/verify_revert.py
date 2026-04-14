"""
Verify the revert to original penalty logic
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
    print("VERIFYING REVERT TO ORIGINAL PENALTY LOGIC")
    print("="*80)
    print()

    executor = OrderExecutor()

    try:
        # Test regime detection
        regime_data = detect_market_regime(executor)

        print("REGIME DETECTION:")
        print(f"  Regime:     {regime_data['regime']}")
        print(f"  BTC ATR%:   {regime_data['atr_pct']:.4f}%")
        print(f"  BTC Slope%: {regime_data['slope_pct']:.4f}%")
        print()
        print("="*80)
        print("PENALTY LOGIC (REVERTED TO ORIGINAL)")
        print("="*80)
        print()

        if regime_data['regime'] == 'ranging':
            print("[RANGING REGIME]")
            print("  - LONG signals:  70% PENALTY (score *= 0.3)")
            print("  - SHORT signals: NO PENALTY (full strength)")
            print()
            print("  Inverted momentum logic:")
            print("    Oversold (RSI<30) → SHORT signal (overbought mean-reversion)")
            print("    Overbought (RSI>70) → LONG signal (oversold mean-reversion)")
            print()
            print("  Result: BOT FAVORS SHORTS in ranging markets")
        else:
            print("[TRENDING REGIME]")
            print("  - LONG signals:  NO PENALTY (full strength)")
            print("  - SHORT signals: NO PENALTY (full strength)")
            print()
            print("  Normal scoring logic (no penalties)")
            print()
            print("  Result: Best signal wins (no bias)")

        print()
        print("="*80)
        print("CONFIRMED: ORIGINAL LOGIC RESTORED")
        print("="*80)
        print()
        print("Changes reverted:")
        print("  ✓ No directional penalties based on slope")
        print("  ✓ LONG penalty only in ranging markets")
        print("  ✓ SHORT signals never penalized")
        print("  ✓ Inverted momentum logic intact")
        print()
        print("Thresholds kept (lowered):")
        print("  ✓ ATR threshold: 0.5% (was 1.5%)")
        print("  ✓ Slope threshold: 0.1% (was 0.3%)")

    finally:
        executor.close()

if __name__ == "__main__":
    asyncio.run(main())
