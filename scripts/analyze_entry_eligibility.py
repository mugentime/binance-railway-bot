#!/usr/bin/env python3
"""
Analyze which of the 226 10%+ movers would have triggered our entry system
Evaluates against: signal scorer, filters, and curated pair list
"""
import json
import sys
import io

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Import config
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import config

def load_movers_data(filepath="../docs/trades_export/24h_movers.json"):
    """Load 24h movers data from JSON"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['movers']

def evaluate_entry_eligibility(mover):
    """
    Evaluate if a mover would have passed our entry criteria

    Returns: (would_enter: bool, reasons: list, score_estimate: float)
    """
    symbol = mover['symbol']
    price_change_pct = mover['price_change_pct']
    range_pct = mover['range_pct']
    quote_volume = mover['quote_volume']
    num_trades = mover['num_trades']

    reasons = []
    blockers = []

    # ========== FILTER CHECKS ==========

    # 1. Check if symbol is excluded
    if symbol in config.EXCLUDED_SYMBOLS:
        blockers.append(f"EXCLUDED: {symbol} is in the exclusion list")
        return False, blockers, 0.0

    # 2. Check if symbol is in curated list (or if curated list is disabled)
    if config.USE_CURATED_PAIR_LIST:
        if symbol not in config.CURATED_PAIR_LIST:
            blockers.append(f"NOT IN CURATED LIST: {symbol} not in top 100 movers list")
            return False, blockers, 0.0
        else:
            reasons.append(f"✓ In curated list")

    # 3. Volume filter
    if quote_volume < config.MIN_QUOTE_VOLUME_24H:
        blockers.append(f"LOW VOLUME: ${quote_volume:,.0f} < ${config.MIN_QUOTE_VOLUME_24H:,.0f} minimum")
        return False, blockers, 0.0
    else:
        reasons.append(f"✓ Volume OK: ${quote_volume:,.0f}")

    # 4. ATR/Volatility check (we can't calculate exact ATR from 24h data, but range_pct gives us an idea)
    # A 10%+ move in 24h definitely exceeds the 0.3% ATR threshold
    if range_pct >= 10.0:
        reasons.append(f"✓ High volatility: {range_pct:.2f}% range")
    else:
        reasons.append(f"⚠ Moderate volatility: {range_pct:.2f}% range (borderline)")

    # Spread and slippage: can't evaluate from 24h data, assume OK for analysis
    reasons.append(f"? Spread/slippage: Unknown (requires live orderbook)")

    # ========== SIGNAL SCORING ESTIMATION ==========

    # We don't have historical RSI/BB/Z-score at the exact moment before the move
    # But we can make educated estimates based on the price action:

    # For a 10%+ move to happen:
    # - If price went UP significantly, it was likely oversold BEFORE (good for LONG entry)
    # - If price went DOWN significantly, it was likely overbought BEFORE (good for SHORT entry)

    # Our strategy is MEAN-REVERSION:
    # - We SHORT when overbought (RSI>60, BB>0.6, Z>0.5) expecting price to fall
    # - We LONG when oversold (RSI<40, BB<0.4, Z<-0.5) expecting price to rise

    direction = "UP" if price_change_pct > 0 else "DOWN"
    abs_change = abs(price_change_pct)

    estimated_score = 0.0
    scoring_breakdown = []

    if direction == "UP":
        # Price went UP - we would have wanted to LONG (buy low before the rise)
        # For a LONG signal, we need: RSI<40, BB<0.4, Z<-0.5

        # Larger moves suggest stronger oversold conditions before the move
        if abs_change >= 30:
            # Very strong move - likely very oversold before
            rsi_score = 40.0  # Near-max LONG RSI signal
            bb_score = 25.0   # Strong LONG BB signal
            z_score = 16.0    # Strong LONG Z-score signal
            scoring_breakdown.append("Strong LONG signals (30%+ move)")
        elif abs_change >= 20:
            rsi_score = 30.0
            bb_score = 20.0
            z_score = 12.0
            scoring_breakdown.append("Moderate LONG signals (20%+ move)")
        elif abs_change >= 15:
            rsi_score = 20.0
            bb_score = 15.0
            z_score = 8.0
            scoring_breakdown.append("Weak-moderate LONG signals (15%+ move)")
        else:  # 10-15%
            rsi_score = 10.0
            bb_score = 8.0
            z_score = 4.0
            scoring_breakdown.append("Weak LONG signals (10-15% move)")

        # Volume bonus
        volume_score = 5.0  # Assume moderate volume during the move

        raw_score = rsi_score + bb_score + z_score + volume_score

        # LONG penalty: 0.9x (10% penalty)
        estimated_score = raw_score * config.LONG_PENALTY_MULTIPLIER

        signal_direction = "LONG"
        scoring_breakdown.append(f"Raw score: {raw_score:.1f} → After LONG penalty (0.9x): {estimated_score:.1f}")

    else:  # direction == "DOWN"
        # Price went DOWN - we would have wanted to SHORT (sell high before the fall)
        # For a SHORT signal, we need: RSI>60, BB>0.6, Z>0.5

        # Larger drops suggest stronger overbought conditions before the move
        if abs_change >= 30:
            rsi_score = 45.0  # Near-max SHORT RSI signal
            bb_score = 28.0   # Strong SHORT BB signal
            z_score = 18.0    # Strong SHORT Z-score signal
            scoring_breakdown.append("Strong SHORT signals (30%+ move)")
        elif abs_change >= 20:
            rsi_score = 35.0
            bb_score = 22.0
            z_score = 14.0
            scoring_breakdown.append("Moderate SHORT signals (20%+ move)")
        elif abs_change >= 15:
            rsi_score = 25.0
            bb_score = 18.0
            z_score = 10.0
            scoring_breakdown.append("Weak-moderate SHORT signals (15%+ move)")
        else:  # 10-15%
            rsi_score = 15.0
            bb_score = 12.0
            z_score = 6.0
            scoring_breakdown.append("Weak SHORT signals (10-15% move)")

        volume_score = 5.0

        raw_score = rsi_score + bb_score + z_score + volume_score
        estimated_score = raw_score  # No penalty for SHORTs in normal regime

        signal_direction = "SHORT"
        scoring_breakdown.append(f"Raw score: {raw_score:.1f} → After penalties: {estimated_score:.1f}")

    # Check if score passes entry threshold
    if estimated_score >= config.ENTRY_THRESHOLD:
        reasons.append(f"✓ SCORE PASSES: {estimated_score:.1f} >= {config.ENTRY_THRESHOLD} threshold")
        reasons.append(f"  Signal direction: {signal_direction}")
        reasons.extend([f"  {s}" for s in scoring_breakdown])
        return True, reasons, estimated_score
    else:
        blockers.append(f"SCORE TOO LOW: {estimated_score:.1f} < {config.ENTRY_THRESHOLD} threshold ({signal_direction})")
        blockers.extend([f"  {s}" for s in scoring_breakdown])
        return False, blockers, estimated_score

def main():
    """Main analysis"""
    print("="*120)
    print("ENTRY ELIGIBILITY ANALYSIS: 24-Hour 10% Movers")
    print("="*120)
    print()

    # Load movers
    movers = load_movers_data()
    print(f"Loaded {len(movers)} movers with 10%+ price movement\n")

    # Stats
    total = len(movers)
    would_enter = []
    would_not_enter = []

    blockers_stats = {
        "excluded": 0,
        "not_in_curated": 0,
        "low_volume": 0,
        "score_too_low": 0
    }

    # Analyze each mover
    for mover in movers:
        passes, details, score = evaluate_entry_eligibility(mover)

        mover['would_enter'] = passes
        mover['entry_details'] = details
        mover['estimated_score'] = score

        if passes:
            would_enter.append(mover)
        else:
            would_not_enter.append(mover)

            # Track blocker reasons
            blocker_text = details[0] if details else ""
            if "EXCLUDED" in blocker_text:
                blockers_stats["excluded"] += 1
            elif "NOT IN CURATED LIST" in blocker_text:
                blockers_stats["not_in_curated"] += 1
            elif "LOW VOLUME" in blocker_text:
                blockers_stats["low_volume"] += 1
            elif "SCORE TOO LOW" in blocker_text:
                blockers_stats["score_too_low"] += 1

    # Summary
    print("="*120)
    print("SUMMARY")
    print("="*120)
    print(f"Total 10%+ movers:        {total}")
    print(f"Would ENTER:              {len(would_enter)} ({len(would_enter)/total*100:.1f}%)")
    print(f"Would NOT enter:          {len(would_not_enter)} ({len(would_not_enter)/total*100:.1f}%)")
    print()
    print("BLOCKER BREAKDOWN:")
    print(f"  Excluded symbols:       {blockers_stats['excluded']}")
    print(f"  Not in curated list:    {blockers_stats['not_in_curated']}")
    print(f"  Low volume (<$2M):      {blockers_stats['low_volume']}")
    print(f"  Score too low (<20):    {blockers_stats['score_too_low']}")
    print()

    # ========== WOULD ENTER ==========
    print("="*120)
    print(f"WOULD ENTER ({len(would_enter)} symbols)")
    print("="*120)
    print()

    if would_enter:
        # Sort by estimated score
        would_enter.sort(key=lambda x: x['estimated_score'], reverse=True)

        print(f"{'Symbol':<15} {'24h %':<10} {'Range %':<10} {'Volume (USDT)':<18} {'Est. Score':<12} {'Direction':<10}")
        print("-"*120)

        for m in would_enter:
            symbol = m['symbol']
            pct = m['price_change_pct']
            range_pct = m['range_pct']
            vol = m['quote_volume']
            score = m['estimated_score']
            direction = "LONG (UP)" if pct > 0 else "SHORT (DOWN)"

            print(f"{symbol:<15} {pct:>8.2f}% {range_pct:>8.2f}% ${vol:>15,.0f} {score:>10.1f} {direction:<10}")

        print()
        print("DETAILED REASONING (Top 10):")
        print("-"*120)
        for i, m in enumerate(would_enter[:10], 1):
            print(f"\n{i}. {m['symbol']} ({m['price_change_pct']:+.2f}%) - Score: {m['estimated_score']:.1f}")
            for detail in m['entry_details']:
                print(f"   {detail}")
    else:
        print("None - all movers were filtered out\n")

    # ========== WOULD NOT ENTER ==========
    print()
    print("="*120)
    print(f"WOULD NOT ENTER ({len(would_not_enter)} symbols)")
    print("="*120)
    print()

    if would_not_enter:
        # Group by blocker type
        by_blocker = {
            "Excluded": [],
            "Not in curated list": [],
            "Low volume": [],
            "Score too low": []
        }

        for m in would_not_enter:
            blocker = m['entry_details'][0] if m['entry_details'] else "Unknown"
            if "EXCLUDED" in blocker:
                by_blocker["Excluded"].append(m)
            elif "NOT IN CURATED LIST" in blocker:
                by_blocker["Not in curated list"].append(m)
            elif "LOW VOLUME" in blocker:
                by_blocker["Low volume"].append(m)
            elif "SCORE TOO LOW" in blocker:
                by_blocker["Score too low"].append(m)

        for blocker_type, movers_list in by_blocker.items():
            if movers_list:
                print(f"\n{blocker_type} ({len(movers_list)} symbols):")
                print("-"*120)

                # Show first 20 of each category
                for m in movers_list[:20]:
                    print(f"  {m['symbol']:<15} {m['price_change_pct']:>8.2f}% - {m['entry_details'][0]}")

                if len(movers_list) > 20:
                    print(f"  ... and {len(movers_list) - 20} more")

    # ========== MISSED OPPORTUNITIES ==========
    print()
    print("="*120)
    print("MISSED OPPORTUNITIES ANALYSIS")
    print("="*120)
    print()

    # Find high-magnitude movers we would NOT have entered
    missed_big_movers = [m for m in would_not_enter if abs(m['price_change_pct']) >= 20]
    missed_big_movers.sort(key=lambda x: abs(x['price_change_pct']), reverse=True)

    if missed_big_movers:
        print(f"Large moves (20%+) we MISSED: {len(missed_big_movers)}")
        print()
        print(f"{'Symbol':<15} {'24h %':<10} {'Range %':<10} {'Volume':<18} {'Reason Blocked':<50}")
        print("-"*120)

        for m in missed_big_movers[:15]:
            reason = m['entry_details'][0][:47] + "..." if len(m['entry_details'][0]) > 50 else m['entry_details'][0]
            print(f"{m['symbol']:<15} {m['price_change_pct']:>8.2f}% {m['range_pct']:>8.2f}% "
                  f"${m['quote_volume']:>15,.0f} {reason:<50}")
    else:
        print("No large moves (20%+) were missed - good filtering!")

    print()
    print("="*120)
    print("ANALYSIS COMPLETE")
    print("="*120)

    # Save results
    output_file = "../docs/trades_export/entry_eligibility_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': {
                'total_movers': total,
                'would_enter': len(would_enter),
                'would_not_enter': len(would_not_enter),
                'entry_rate': len(would_enter) / total * 100,
                'blockers': blockers_stats
            },
            'would_enter': would_enter,
            'would_not_enter': would_not_enter
        }, f, indent=2)

    print(f"\nDetailed results saved to: {output_file}")

if __name__ == "__main__":
    main()
