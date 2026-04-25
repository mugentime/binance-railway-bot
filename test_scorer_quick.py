"""Quick test to verify new volume-first scorer (no volatility calculation)"""
import asyncio
import sys
sys.path.insert(0, 'src')

from pair_scanner import PairScanner
from signal_scorer import SignalScorer

async def main():
    print("\n" + "="*80)
    print("QUICK TEST - NEW VOLUME-FIRST SCORER")
    print("="*80)

    scanner = PairScanner()
    scorer = SignalScorer()

    try:
        # Scan pairs
        print("\nScanning market data...")
        pair_data = await scanner.scan_all_pairs()
        print(f"Scanned {len(pair_data)} pairs")

        # Score pairs (without volatility tracker for speed)
        print("\nScoring signals with new volume-first scorer...")
        signals = scorer.score_all_pairs(pair_data, blacklisted_symbols=[],
                                        regime_data=None, volatility_tracker=None)

        print("\n" + "="*80)
        print(f"✅ NEW SCORER ACTIVE - Generated {len(signals)} signals")
        print("="*80)

        if signals:
            print("\nTop 5 signals:")
            print(f"{'Rank':<6} {'Symbol':<12} {'Dir':<6} {'Score':<8} {'Vol':<6} {'Slp':<6} {'Mom':<6} {'Z':<6}")
            print("-"*75)

            for i, sig in enumerate(signals[:5], 1):
                print(f"{i:<6} {sig.symbol:<12} {sig.direction:<6} {sig.score:<8.1f} "
                      f"{sig.volume_score:<6.1f} {sig.slope_score:<6.1f} "
                      f"{sig.momentum_score:<6.1f} {sig.zscore_score:<6.1f}")

            # Verify score breakdown
            top = signals[0]
            calculated_total = (top.volume_score + top.slope_score +
                               top.momentum_score + top.zscore_score +
                               top.volatility_bonus)

            print("\n" + "="*75)
            print("VERIFICATION - Top signal score breakdown:")
            print(f"  Symbol:     {top.symbol}")
            print(f"  Direction:  {top.direction}")
            print(f"  Volume:     {top.volume_score:>6.1f} pts (RSI={top.rsi:.1f}, Vol ratio={top.volume_ratio:.2f}x)")
            print(f"  Slope:      {top.slope_score:>6.1f} pts (SMA slope={top.sma_slope_pct:.4f}%)")
            print(f"  Momentum:   {top.momentum_score:>6.1f} pts (BB%B={top.bb_pct_b:.2f})")
            print(f"  Z-score:    {top.zscore_score:>6.1f} pts (Z={top.zscore:.2f})")
            print(f"  Vol Bonus:  {top.volatility_bonus:>6.1f} pts (no tracker)")
            print(f"  " + "-"*35)
            print(f"  Calculated: {calculated_total:>6.1f} pts")
            print(f"  Reported:   {top.score:>6.1f} pts")
            print(f"  Match: {'✅ YES' if abs(calculated_total - top.score) < 0.1 else '❌ NO'}")
            print("="*75)

            # Check if all scores are zero
            if top.score == 0.0:
                print("\n❌ ERROR: Top score is zero - scorer may not be working!")
                return False

            print("\n✅ SANITY CHECK PASSED - New scorer active and generating non-zero scores")
            return True
        else:
            print("\n⚠️ WARNING: No signals generated")
            print("This could be normal if all pairs are filtered out by volume < 1.0x")
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
