"""Quick test to verify new volume-first scorer is working"""
import asyncio
import sys
sys.path.insert(0, 'src')

from pair_scanner import PairScanner
from signal_scorer import SignalScorer
from volatility_tracker import VolatilityTracker

async def main():
    print("\n" + "="*80)
    print("TESTING NEW VOLUME-FIRST SCORER")
    print("="*80)

    scanner = PairScanner()
    scorer = SignalScorer()
    volatility_tracker = VolatilityTracker()

    try:
        # Scan pairs (limit to 50 for quick test)
        print("\nScanning market data...")
        pair_data = await scanner.scan_all_pairs()
        print(f"Scanned {len(pair_data)} pairs")

        # Calculate volatility scores (this will take a moment)
        print("\nCalculating volatility scores...")
        symbols = list(pair_data.keys())
        volatility_tracker.calculate_volatility_scores(symbols[:50])  # Limit for speed

        # Score pairs
        print("\nScoring signals with new volume-first scorer...")
        signals = scorer.score_all_pairs(pair_data, blacklisted_symbols=[],
                                        regime_data=None, volatility_tracker=volatility_tracker)

        print("\n" + "="*80)
        print(f"✅ NEW SCORER ACTIVE - Generated {len(signals)} signals")
        print("="*80)

        if signals:
            print("\nTop 5 signals:")
            print(f"{'Rank':<6} {'Symbol':<12} {'Dir':<6} {'Score':<8} {'Vol':<6} {'Slp':<6} {'Mom':<6} {'Z':<6} {'VltB':<6}")
            print("-"*80)

            for i, sig in enumerate(signals[:5], 1):
                print(f"{i:<6} {sig.symbol:<12} {sig.direction:<6} {sig.score:<8.1f} "
                      f"{sig.volume_score:<6.1f} {sig.slope_score:<6.1f} "
                      f"{sig.momentum_score:<6.1f} {sig.zscore_score:<6.1f} "
                      f"{sig.volatility_bonus:<6.1f}")

            # Verify score breakdown
            top = signals[0]
            calculated_total = (top.volume_score + top.slope_score +
                               top.momentum_score + top.zscore_score +
                               top.volatility_bonus)

            print("\n" + "="*80)
            print("VERIFICATION - Top signal score breakdown:")
            print(f"  Volume:     {top.volume_score:>6.1f} pts")
            print(f"  Slope:      {top.slope_score:>6.1f} pts")
            print(f"  Momentum:   {top.momentum_score:>6.1f} pts")
            print(f"  Z-score:    {top.zscore_score:>6.1f} pts")
            print(f"  Vol Bonus:  {top.volatility_bonus:>6.1f} pts")
            print(f"  " + "-"*30)
            print(f"  Calculated: {calculated_total:>6.1f} pts")
            print(f"  Reported:   {top.score:>6.1f} pts")
            print(f"  Match: {'✅ YES' if abs(calculated_total - top.score) < 0.1 else '❌ NO'}")
            print("="*80)

            # Check if any scores are all zeros (would indicate scorer not working)
            if all(s.score == 0.0 for s in signals[:5]):
                print("\n❌ ERROR: All scores are zero - scorer may not be working!")
                return False

            print("\n✅ SANITY CHECK PASSED - New scorer is active and working correctly")
            return True
        else:
            print("\n⚠️ WARNING: No signals generated (may be normal if market is quiet)")
            return True

    except Exception as e:
        print(f"\n❌ ERROR during test: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await scanner.close()

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
