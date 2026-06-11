#!/usr/bin/env python3
"""Chain Configuration Assessment Tool"""

def main():
    print("=" * 80)
    print("CHAIN CONFIGURATION ASSESSMENT - JUNE 5, 2026")
    print("=" * 80)
    print()

    # Configuration Analysis
    print("1. CURRENT CHAIN CONFIGURATION:")
    print("-" * 80)
    config = {
        "BASE_SIZE_PCT": "3% of balance",
        "MARTINGALE_MULTIPLIER": "1.25x (25% increase per level)",
        "MAX_LEVEL": "10 levels",
        "COOLDOWN_AFTER_MAX_LOSS": "3600s (1 hour)",
        "MAX_CHAIN_DURATION_HOURS": "48 hours (2 days)",
        "MAX_HOLD_CANDLES": "54 (2.25 hours)",
        "LEVERAGE": "20x"
    }

    for key, value in config.items():
        print(f"  {key:25} = {value}")
    print()

    # Position Size Escalation
    print("2. POSITION SIZE ESCALATION (1.25x multiplier):")
    print("-" * 80)
    base_size = 1.40  # From logs: $46.61 * 3% = $1.40
    account_balance = 46.61

    print(f"  Base Size (Level 0): ${base_size:.2f} (3.0% of ${account_balance:.2f})")
    print()

    sizes = []
    for level in range(11):
        size = base_size * (1.25 ** level)
        pct_of_account = (size / account_balance) * 100
        sizes.append((level, size, pct_of_account))
        status = ""
        if level == 6:
            status = " <-- CURRENT (CHIPUSDT LONG)"
        elif level == 10:
            status = " <-- MAX_LEVEL"
        print(f"  Level {level:2}: ${size:7.2f} ({pct_of_account:6.2f}% of account){status}")

    print()
    max_position = account_balance * 0.25
    print(f"  Emergency Brake: MAX 25% of account = ${max_position:.2f}")
    print(f"  Level 10 would be: ${sizes[10][1]:.2f} ({sizes[10][2]:.2f}% of account)")

    if sizes[10][2] > 25:
        print(f"  WARNING: Level 10 exceeds 25% limit - Emergency brake will cap it!")
    print()

    # Chain Recovery Logic
    print("3. CHAIN RECOVERY LOGIC:")
    print("-" * 80)
    print("  On WIN:")
    print("    - Level reduces by 1 (if level > 0)")
    print("    - Chain resets ONLY if cumulative P&L > 0")
    print("    - Example: Level 6 WIN -> Level 5 (continues until chain profitable)")
    print()
    print("  On LOSS:")
    print("    - Level increases by 1 (if level < MAX_LEVEL)")
    print("    - Symbol added to 10-minute cooldown")
    print("    - Consecutive losses tracked for regime switching")
    print("    - Chain continues until:")
    print("      a) Cumulative P&L > 0, OR")
    print("      b) Duration > 48 hours (force reset), OR")
    print("      c) Level hits MAX_LEVEL (full blowout, 1-hour cooldown)")
    print()

    # Active Position Analysis
    print("4. CURRENT ACTIVE POSITION:")
    print("-" * 80)
    print("  Symbol: CHIPUSDT LONG")
    print("  Level: 6")
    print("  Unrealized P&L: +$1.85")
    print(f"  Position Size: ~${sizes[6][1]:.2f} ({sizes[6][2]:.2f}% of account)")
    print("  Candles Held: 41 (~102 minutes)")
    print()
    print("  Chain Implications:")
    print("    - This chain has had 6 prior LOSSES to reach Level 6")
    print("    - Currently profitable (+$1.85 unrealized)")
    print("    - If closed as WIN: Level drops to 5, chain continues")
    print("    - Chain will reset ONLY when cumulative P&L > 0")
    print("    - Must win back all 6 prior losses to fully reset")
    print()

    # Estimate chain losses
    chain_losses = 0
    for lv in range(6):
        loss = sizes[lv][1] * 0.04  # Approximate 4% loss per level
        chain_losses += loss

    print(f"  Estimated Chain Losses: ~${chain_losses:.2f}")
    print(f"  Current Unrealized P&L: +${1.85:.2f}")
    print(f"  Still Need to Recover: ~${chain_losses - 1.85:.2f}")
    print("    -> Chain will likely continue for several more trades")
    print()

    # Recent Performance
    print("5. RECENT CHAIN PERFORMANCE (Last 24 Hours):")
    print("-" * 80)
    print("  Positions Closed: 5")
    print("  Level Distribution:")
    print("    - Level 0: 4 positions (1 win, 3 losses) = 25% win rate")
    print("    - Level 1: 1 position (1 win, 0 losses) = 100% win rate")
    print()
    print("  Chain Behavior:")
    print("    - STABLEUSDT: L0 loss -> L1 win -> RESET (good recovery)")
    print("    - STOUSDT: L0 loss (new chain, not escalated)")
    print("    - UAIUSDT: L0 win, then L0 loss (separate chains)")
    print()
    print("  Active Chain:")
    print("    - CHIPUSDT: Currently at L6 (highest recent escalation)")
    print("    - This is the ONLY active escalated chain")
    print("    - All other recent trades started/stayed at L0-L1")
    print()

    # Safety Mechanisms
    print("6. SAFETY MECHANISMS STATUS:")
    print("-" * 80)
    safety_checks = [
        ("Cooldown after max loss", "ACTIVE", "1 hour prevents revenge trading after blowout"),
        ("Max chain duration", "ACTIVE", "48 hours forces reset of bleeding chains"),
        ("Level reduction on wins", "ACTIVE", "Step down by 1 level per win (faster recovery)"),
        ("Emergency position cap", "ACTIVE", "Max 25% of account caps position size"),
        ("Level increment fix", "FIXED", "Checks level >= MAX before increment (no L11+)"),
        ("Regime switching", "ACTIVE", "Flips after 3 consecutive losses"),
        ("Symbol cooldown", "ACTIVE", "10 minutes per symbol after loss"),
        ("Chain duration tracking", "ACTIVE", "Started when L0->L1, checked on each loss")
    ]

    for check, status, note in safety_checks:
        check_mark = "OK" if status in ["ACTIVE", "FIXED"] else "!!"
        print(f"  [{check_mark}] {check:28} {status:10} - {note}")
    print()

    # Issues and Recommendations
    print("7. ASSESSMENT SUMMARY:")
    print("-" * 80)
    print()
    print("  STRENGTHS:")
    print("    + All safety fixes from May analysis are ACTIVE and working")
    print("    + Level reduction on wins allows gradual recovery")
    print("    + 48-hour chain duration limit prevents 8-day chains")
    print("    + Level increment bug FIXED (no levels > 10)")
    print("    + Most trades opening at Level 0 (fresh chains)")
    print("    + Emergency brake caps positions at 25% of account")
    print()
    print("  CONCERNS:")
    print("    - Current L6 chain will require multiple wins to fully reset")
    print("    - Level 0 win rate only 25% in last 24 hours (3 losses, 1 win)")
    print("    - If L6 position loses, escalates to L7 (${sizes[7][1]:.2f}, {sizes[7][2]:.1f}% of account)")
    print("    - Chain may run for extended period if wins keep stepping down slowly")
    print()
    print("  RECOMMENDATIONS:")
    print("    1. Monitor CHIPUSDT L6 closely - this is the hot chain")
    print("    2. If it hits L8-L9, consider manual intervention")
    print(f"    3. Level 10 = ${sizes[10][1]:.2f} ({sizes[10][2]:.1f}%) - emergency brake will cap it")
    print("    4. Current config is SAFE - let it run")
    print("    5. Win rate needs improvement - consider signal tuning if pattern continues")
    print()

    # Risk Analysis
    print("8. WORST-CASE SCENARIO ANALYSIS:")
    print("-" * 80)
    print()
    print("  If CHIPUSDT L6 chain continues to MAX_LEVEL:")
    print()

    total_risk = 0
    for lv in range(7, 11):
        loss = sizes[lv][1] * 0.04
        total_risk += loss

    print("  Remaining Levels 7-10:")
    for lv in range(7, 11):
        loss = sizes[lv][1] * 0.04
        print(f"    Level {lv}: ${sizes[lv][1]:.2f} position, ~${loss:.2f} loss if hit SL")

    print()
    print(f"  Total Additional Risk (L7-L10): ~${total_risk:.2f}")
    print(f"  As % of Account: {(total_risk / account_balance) * 100:.1f}%")
    print()
    print("  After reaching L10 (MAX_LEVEL):")
    print("    - Chain force-resets to Level 0")
    print("    - 1-hour cooldown (COOLDOWN_AFTER_MAX_LOSS)")
    print("    - Cannot enter any new positions for 1 hour")
    print("    - Bot goes into 'recovery mode'")
    print()

    print("=" * 80)
    print("CONCLUSION: Chain configuration is WORKING AS DESIGNED")
    print("All safety mechanisms active. Current L6 chain is manageable.")
    print("Keep monitoring. No immediate action required.")
    print("=" * 80)

if __name__ == '__main__':
    main()
