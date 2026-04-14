"""
Test insufficient balance auto-reset functionality
"""
import sys
import os
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import config
from martingale_manager import MartingaleManager
from order_executor import OrderExecutor
from safety_checks import SafetyChecker
from utils import save_state, load_state

def main():
    print("="*80)
    print("TESTING INSUFFICIENT BALANCE AUTO-RESET")
    print("="*80)
    print()

    # Initialize components
    manager = MartingaleManager()
    executor = OrderExecutor()
    checker = SafetyChecker()

    manager.set_executor(executor)

    try:
        # Get real balance
        balance = executor.get_account_balance()
        print(f"Current balance: ${balance:.2f}")
        print()

        # Simulate high level that would require more balance
        print("SIMULATING HIGH MARTINGALE LEVEL...")

        # IMPORTANT: Must update balance cache first
        manager.update_chain_start_balance()

        manager.level = 8  # High level
        print(f"  Set level to: {manager.level}")

        # Calculate required margin at level 8
        required_margin = manager.margin_required()
        required_with_buffer = required_margin * 1.5
        print(f"  Required margin at level 8: ${required_margin:.2f}")
        print(f"  Required with 1.5x buffer: ${required_with_buffer:.2f}")
        print(f"  Available balance: ${balance:.2f}")
        print()

        if balance < required_with_buffer:
            print("[TEST CONDITION MET] Balance IS insufficient for level 8")
            print("  Expected: Bot will auto-reset to level 0")
        else:
            print("[TEST CONDITION NOT MET] Balance is actually sufficient for level 8")
            print("  Note: Auto-reset only triggers when balance is truly insufficient")
        print()

        # Save state before check
        save_state(manager)
        print("State saved with level 8")
        print()

        # Run balance check (should trigger auto-reset)
        print("RUNNING BALANCE CHECK...")
        result = checker.check_balance(manager, executor)
        print()

        # Verify reset happened
        print("="*80)
        print("VERIFICATION")
        print("="*80)
        print(f"Balance check result: {'PASSED' if result else 'FAILED (as expected)'}")
        print(f"Manager level after check: {manager.level}")
        print()

        # Load state from disk to verify persistence
        saved_state = load_state()
        if saved_state:
            print(f"State file level: {saved_state.get('level', 'N/A')}")

            if manager.level == 0 and saved_state.get('level') == 0:
                print()
                print("[SUCCESS] Auto-reset worked correctly!")
                print("  - Manager level reset to 0")
                print("  - State saved to disk")
                print("  - Next bot cycle will start at level 0")
            elif manager.level == 8:
                print()
                print("[INFO] Level 8 unchanged (balance was sufficient)")
                print("  This is normal if your balance can handle level 8")
            else:
                print()
                print("[UNEXPECTED] State mismatch")
        else:
            print("[WARNING] No state file found")

        print()
        print("="*80)
        print("TEST COMPLETE")
        print("="*80)

    finally:
        executor.close()

if __name__ == "__main__":
    main()
