#!/usr/bin/env python3
"""Base Size Optimization Analysis"""

def analyze_base_size(base_pct, account_balance, multiplier=1.25, max_level=10):
    """Calculate position sizes and risk for given base percentage."""
    levels = []
    for level in range(max_level + 1):
        size_usd = (account_balance * (base_pct / 100)) * (multiplier ** level)
        size_pct = (size_usd / account_balance) * 100
        levels.append({
            'level': level,
            'size_usd': size_usd,
            'size_pct': size_pct,
            'capped': size_pct > 25  # Emergency brake at 25%
        })
    return levels

def calculate_expected_pnl(base_pct, historical_pnl, current_base_pct=3.0):
    """Estimate P&L with different base size."""
    # Linear scaling assumption
    scaling_factor = base_pct / current_base_pct
    return historical_pnl * scaling_factor

def main():
    print("=" * 80)
    print("BASE SIZE OPTIMIZATION ANALYSIS")
    print("=" * 80)
    print()

    # Current account data
    account_balance = 47.27  # Current balance (excluding unrealized)
    current_base_pct = 3.0
    multiplier = 1.25
    max_level = 10

    # Historical performance
    total_positions = 58
    total_realized_pnl = 20.58
    avg_pnl_per_position = total_realized_pnl / total_positions
    win_rate = 0.431

    # Scenarios to analyze
    scenarios = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0]

    print("CURRENT CONFIGURATION:")
    print("-" * 80)
    print(f"  Account Balance:        ${account_balance:.2f}")
    print(f"  Current Base Size:      {current_base_pct}%")
    print(f"  Martingale Multiplier:  {multiplier}x")
    print(f"  Max Level:              {max_level}")
    print(f"  Emergency Brake:        25% of account")
    print()

    print("HISTORICAL PERFORMANCE (3.85 days):")
    print("-" * 80)
    print(f"  Total Positions:        {total_positions}")
    print(f"  Total P&L:              ${total_realized_pnl:.2f}")
    print(f"  Avg P&L per Position:   ${avg_pnl_per_position:.4f}")
    print(f"  Win Rate:               {win_rate*100:.1f}%")
    print()

    # Analyze each scenario
    print("=" * 80)
    print("SCENARIO ANALYSIS: BASE SIZE VARIATIONS")
    print("=" * 80)
    print()

    results = []

    for base_pct in scenarios:
        print(f"\n{'='*80}")
        print(f"SCENARIO: {base_pct}% BASE SIZE ({base_pct/current_base_pct:.1f}x current)")
        print(f"{'='*80}\n")

        levels = analyze_base_size(base_pct, account_balance, multiplier, max_level)

        # Position size table
        print("Position Sizes by Level:")
        print("-" * 80)
        print(f"{'Level':<8} {'Size (USD)':<12} {'% of Account':<15} {'Status':<20}")
        print("-" * 80)

        emergency_brake_level = None
        for level_data in levels:
            level = level_data['level']
            size_usd = level_data['size_usd']
            size_pct = level_data['size_pct']
            capped = level_data['capped']

            status = ""
            if level == 0:
                status = "Base size"
            elif capped and emergency_brake_level is None:
                status = "EMERGENCY BRAKE!"
                emergency_brake_level = level
            elif level == 6:
                status = "(current CHIPUSDT)"
            elif level == max_level:
                status = "MAX_LEVEL"

            cap_indicator = " [CAPPED]" if capped else ""
            actual_size = min(size_usd, account_balance * 0.25) if capped else size_usd

            print(f"L{level:<7} ${actual_size:<10.2f} {size_pct:<13.2f}% {status:<20}{cap_indicator}")

        print()

        # Risk analysis
        print("Risk Analysis:")
        print("-" * 80)

        # Calculate total risk if chain goes to max level
        total_chain_risk = 0
        for level_data in levels:
            if level_data['capped']:
                total_chain_risk += account_balance * 0.25 * 0.04  # 4% loss at capped size
            else:
                total_chain_risk += level_data['size_usd'] * 0.04  # 4% SL

        max_single_position = max([min(l['size_usd'], account_balance * 0.25) for l in levels])
        max_single_loss = max_single_position * 0.04

        print(f"  Max Single Position:        ${max_single_position:.2f} ({max_single_position/account_balance*100:.1f}% of account)")
        print(f"  Max Single Loss (4% SL):    ${max_single_loss:.2f} ({max_single_loss/account_balance*100:.1f}% of account)")
        print(f"  Total Chain Risk (L0-L10):  ${total_chain_risk:.2f} ({total_chain_risk/account_balance*100:.1f}% of account)")

        if emergency_brake_level:
            print(f"  Emergency Brake Triggers:   Level {emergency_brake_level}")
        else:
            print(f"  Emergency Brake Triggers:   Never (all levels < 25%)")

        print()

        # Expected returns
        print("Expected Performance:")
        print("-" * 80)

        # Scale P&L linearly with base size increase
        scaling_factor = base_pct / current_base_pct
        expected_total_pnl = total_realized_pnl * scaling_factor
        expected_pnl_per_position = avg_pnl_per_position * scaling_factor
        expected_roi = (expected_total_pnl / account_balance) * 100

        # Annualized (3.85 days)
        days = 3.85
        expected_apy = (expected_total_pnl / account_balance) * (365 / days) * 100

        print(f"  Expected Total P&L:         ${expected_total_pnl:.2f} ({scaling_factor:.1f}x current)")
        print(f"  Expected P&L per Position:  ${expected_pnl_per_position:.4f}")
        print(f"  Expected ROI:               {expected_roi:.2f}%")
        print(f"  Expected Annualized:        {expected_apy:.0f}% APY")
        print()

        # Risk/Reward ratio
        risk_reward_ratio = expected_total_pnl / total_chain_risk

        print(f"  Risk/Reward Ratio:          {risk_reward_ratio:.2f}")
        print(f"    > Earn ${risk_reward_ratio:.2f} for every $1 at risk")
        print()

        # Store results
        results.append({
            'base_pct': base_pct,
            'scaling_factor': scaling_factor,
            'max_position_pct': max_single_position / account_balance * 100,
            'total_chain_risk_pct': total_chain_risk / account_balance * 100,
            'expected_pnl': expected_total_pnl,
            'expected_roi': expected_roi,
            'risk_reward': risk_reward_ratio,
            'emergency_brake_level': emergency_brake_level
        })

    # Comparison table
    print("\n" + "=" * 80)
    print("COMPARATIVE SUMMARY")
    print("=" * 80)
    print()
    print(f"{'Base %':<8} {'Scale':<8} {'Max Pos %':<12} {'Chain Risk %':<14} {'Exp P&L':<12} {'ROI %':<10} {'R/R':<8} {'Brake @':<10}")
    print("-" * 80)

    for r in results:
        brake = f"L{r['emergency_brake_level']}" if r['emergency_brake_level'] else "Never"
        print(f"{r['base_pct']:<8.1f} {r['scaling_factor']:<8.2f} {r['max_position_pct']:<12.1f} {r['total_chain_risk_pct']:<14.1f} "
              f"${r['expected_pnl']:<10.2f} {r['expected_roi']:<10.1f} {r['risk_reward']:<8.2f} {brake:<10}")

    print()

    # Recommendations
    print("=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    print()

    print("1. CONSERVATIVE (3-4%):")
    print("   - Best for: Preserving capital, learning phase, volatile markets")
    print("   - Risk Level: LOW")
    print("   - Expected ROI: 45-60% over 4 days")
    print("   - Max Position: 3-5% (L0), 12-16% (L6)")
    print("   - Emergency brake: L8-9 (if ever triggered)")
    print()

    print("2. MODERATE (5-6%):")
    print("   - Best for: Proven strategy, moderate risk tolerance")
    print("   - Risk Level: MODERATE")
    print("   - Expected ROI: 75-90% over 4 days")
    print("   - Max Position: 5-6% (L0), 19-23% (L6)")
    print("   - Emergency brake: L6-7")
    print("   - NOTE: Approaches emergency brake faster")
    print()

    print("3. AGGRESSIVE (7-8%):")
    print("   - Best for: High confidence, high risk tolerance, larger accounts")
    print("   - Risk Level: HIGH")
    print("   - Expected ROI: 105-120% over 4 days")
    print("   - Max Position: 7-8% (L0), 27-31% (L6, CAPPED at 25%)")
    print("   - Emergency brake: L5-6")
    print("   - WARNING: Hits emergency brake quickly, higher drawdown risk")
    print()

    print("=" * 80)
    print("SPECIFIC RECOMMENDATIONS FOR YOUR ACCOUNT:")
    print("=" * 80)
    print()

    print(f"Current Account: ${account_balance:.2f}")
    print(f"Current Win Rate: {win_rate*100:.1f}%")
    print(f"Current Profit Factor: 1.36")
    print()

    print("RECOMMENDED APPROACH:")
    print()

    if account_balance < 50:
        print("  Account Size: SMALL (<$50)")
        print("  Recommendation: INCREASE to 5-6%")
        print()
        print("  Rationale:")
        print("    - Current 3% base ($1.40) generates small absolute returns")
        print("    - 5% base ($2.36) provides better position sizing")
        print("    - Account is small enough that risk is manageable")
        print("    - Allows faster growth through compounding")
        print()
        print("  Implementation:")
        print("    Step 1: Increase to 4% and monitor for 2-3 days")
        print("    Step 2: If performance stable, increase to 5%")
        print("    Step 3: Re-evaluate when account reaches $100")
    elif account_balance < 100:
        print("  Account Size: MEDIUM ($50-$100)")
        print("  Recommendation: MODERATE increase to 4-5%")
        print()
        print("  Rationale:")
        print("    - 4% provides good balance of growth and safety")
        print("    - Emergency brake still triggers at safe levels (L8-9)")
        print("    - Allows meaningful position sizes without excessive risk")
    else:
        print("  Account Size: LARGER (>$100)")
        print("  Recommendation: STAY at 3-4%")
        print()
        print("  Rationale:")
        print("    - Larger accounts benefit from capital preservation")
        print("    - Absolute returns already meaningful")
        print("    - Lower risk of catastrophic drawdowns")

    print()
    print("CONDITIONAL ADJUSTMENT:")
    print("  IF win rate improves to 50%+:")
    print("    > Consider increasing base by +1-2%")
    print("  IF profit factor reaches 2.0+:")
    print("    > Safe to use 5-7% base")
    print("  IF chain hits L8+ frequently:")
    print("    > Reduce base by -1% until signals improve")
    print()

    # Optimal recommendation
    print("=" * 80)
    print("OPTIMAL RECOMMENDATION:")
    print("=" * 80)
    print()

    optimal_base = 5.0  # For current small account
    optimal_levels = analyze_base_size(optimal_base, account_balance, multiplier, max_level)
    optimal_expected_pnl = calculate_expected_pnl(optimal_base, total_realized_pnl, current_base_pct)

    print(f"  Recommended Base Size: {optimal_base}% (current: {current_base_pct}%)")
    print(f"  Increase Factor: {optimal_base/current_base_pct:.2f}x")
    print()
    print(f"  New L0 Position Size: ${optimal_levels[0]['size_usd']:.2f} (was ${account_balance * 0.03:.2f})")
    print(f"  New L6 Position Size: ${optimal_levels[6]['size_usd']:.2f} (was ${account_balance * 0.03 * 1.25**6:.2f})")
    print()
    print(f"  Expected P&L Increase: ${optimal_expected_pnl:.2f} (was ${total_realized_pnl:.2f})")
    print(f"  Expected ROI: {(optimal_expected_pnl/account_balance)*100:.1f}% over 3.85 days")
    print()

    print("  Implementation Steps:")
    print("    1. Update src/config.py:")
    print(f"       BASE_SIZE_PCT = {optimal_base}  # Changed from {current_base_pct}")
    print()
    print("    2. Monitor for 48 hours:")
    print("       - Watch for chains hitting emergency brake (L7-8)")
    print("       - Verify position sizes feel comfortable")
    print("       - Check that max drawdown stays <10% of account")
    print()
    print("    3. Adjust if needed:")
    print("       - If chains escalate too fast: reduce to 4%")
    print("       - If performance excellent: can try 6%")
    print()

    print("=" * 80)
    print("RISK WARNING:")
    print("=" * 80)
    print()
    print("  Increasing base size increases BOTH returns AND risk:")
    print()
    print("  PROS:")
    print("    + Higher absolute returns per trade")
    print("    + Faster account growth through compounding")
    print("    + More meaningful position sizes")
    print()
    print("  CONS:")
    print("    - Larger losses when trades fail")
    print("    - Faster chain escalation to emergency brake")
    print("    - Higher drawdown during losing streaks")
    print("    - More emotional stress during volatile periods")
    print()
    print("  CRITICAL: Only increase if:")
    print("    1. You're comfortable with 2x larger losses per trade")
    print("    2. Win rate is stable at 40%+")
    print("    3. Strategy has been tested for at least 1 week")
    print("    4. You can afford the increased risk")
    print()

    print("=" * 80)

if __name__ == '__main__':
    main()
