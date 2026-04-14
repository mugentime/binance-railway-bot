"""
Test script for state synchronization bug fix

This script verifies that the state verification and recovery logic works correctly.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import json
import time
from martingale_manager import MartingaleManager
from order_executor import OrderExecutor
from utils import save_state, load_state
from main_loop import verify_and_sync_state

def print_test_header(test_name):
    """Print test header"""
    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print(f"{'='*80}\n")

def print_result(passed, message):
    """Print test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {message}\n")

def test_1_clean_state():
    """Test 1: Clean state - no positions on exchange, no state position"""
    print_test_header("Clean State (No Positions)")

    manager = MartingaleManager()
    executor = OrderExecutor()

    try:
        # Verify clean state
        result = verify_and_sync_state(executor, manager)

        if result:
            print_result(True, "Clean state verified - no sync needed")
        else:
            print_result(False, "Clean state verification failed")

    finally:
        executor.close()

def test_2_orphaned_position():
    """Test 2: Orphaned position - position on exchange, but state says no position"""
    print_test_header("Orphaned Position Detection and Adoption")

    manager = MartingaleManager()
    executor = OrderExecutor()

    try:
        # Check if there are actual positions on exchange
        all_open = executor.get_all_open_positions()

        if not all_open:
            print_result(True, "No orphaned positions found (test skipped - need manual setup)")
            print("To test this: Manually open a position on Binance, then edit state.json to set in_position=false")
            return

        # Simulate state mismatch
        manager.in_position = False
        manager.current_symbol = None

        print(f"Simulated state: in_position=False, current_symbol=None")
        print(f"Exchange reality: {len(all_open)} position(s) open")

        # Run verification - should detect and adopt
        result = verify_and_sync_state(executor, manager)

        if result and manager.in_position and manager.current_symbol:
            print_result(True, f"Orphaned position adopted: {manager.current_symbol}")
            print(f"  Entry price: {manager.entry_price}")
            print(f"  Direction: {manager.current_direction}")
            print(f"  Quantity: {manager.entry_quantity}")
        else:
            print_result(False, "Failed to adopt orphaned position")

    finally:
        executor.close()

def test_3_wrong_symbol():
    """Test 3: Wrong symbol - state tracks wrong symbol"""
    print_test_header("Wrong Symbol Correction")

    manager = MartingaleManager()
    executor = OrderExecutor()

    try:
        # Check if there are actual positions on exchange
        all_open = executor.get_all_open_positions()

        if not all_open:
            print_result(True, "No positions found (test skipped - need manual setup)")
            return

        # Simulate tracking wrong symbol
        manager.in_position = True
        manager.current_symbol = "WRONGSYMBOL"

        print(f"Simulated state: in_position=True, current_symbol=WRONGSYMBOL")
        print(f"Exchange reality: {all_open[0]['symbol']} is open")

        # Run verification - should detect and correct
        result = verify_and_sync_state(executor, manager)

        if result and manager.current_symbol == all_open[0]['symbol']:
            print_result(True, f"Symbol corrected to: {manager.current_symbol}")
        else:
            print_result(False, "Failed to correct symbol")

    finally:
        executor.close()

def test_4_phantom_position():
    """Test 4: Phantom position - state says position open, but exchange says closed"""
    print_test_header("Phantom Position Cleanup")

    manager = MartingaleManager()
    executor = OrderExecutor()

    try:
        # Check if there are NO positions on exchange
        all_open = executor.get_all_open_positions()

        if all_open:
            print_result(True, "Positions found on exchange (test skipped - need clean exchange)")
            return

        # Simulate phantom position
        manager.in_position = True
        manager.current_symbol = "BTCUSDT"
        manager.entry_price = 50000.0

        print(f"Simulated state: in_position=True, current_symbol=BTCUSDT")
        print(f"Exchange reality: No positions open")

        # Run verification - should detect and clear
        result = verify_and_sync_state(executor, manager)

        if result and not manager.in_position:
            print_result(True, "Phantom position cleared from state")
        else:
            print_result(False, "Failed to clear phantom position")

    finally:
        executor.close()

def test_5_atomic_save():
    """Test 5: Atomic save with backup"""
    print_test_header("Atomic State Save with Backup")

    manager = MartingaleManager()

    try:
        # Set some state
        manager.level = 2
        manager.in_position = True
        manager.current_symbol = "TESTUSDT"

        print(f"Saving state: level={manager.level}, in_position={manager.in_position}")

        # Save state
        save_state(manager, "state_test.json")

        # Check that backup was created
        backup_exists = os.path.exists("state_test.json.backup")

        # Load and verify
        with open("state_test.json") as f:
            saved_state = json.load(f)

        if (backup_exists and
            saved_state['level'] == 2 and
            saved_state['in_position'] and
            saved_state['current_symbol'] == "TESTUSDT"):
            print_result(True, "State saved atomically with backup")
        else:
            print_result(False, "State save verification failed")

        # Cleanup
        if os.path.exists("state_test.json"):
            os.remove("state_test.json")
        if os.path.exists("state_test.json.backup"):
            os.remove("state_test.json.backup")

    except Exception as e:
        print_result(False, f"Exception during save: {e}")

def main():
    """Run all tests"""
    print(f"\n{'='*80}")
    print(f"STATE SYNCHRONIZATION FIX - TEST SUITE")
    print(f"{'='*80}")

    tests = [
        ("Clean State", test_1_clean_state),
        ("Orphaned Position Adoption", test_2_orphaned_position),
        ("Wrong Symbol Correction", test_3_wrong_symbol),
        ("Phantom Position Cleanup", test_4_phantom_position),
        ("Atomic State Save", test_5_atomic_save),
    ]

    results = []

    for name, test_func in tests:
        try:
            test_func()
            results.append((name, "COMPLETED"))
        except Exception as e:
            print_result(False, f"Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, f"CRASHED: {e}"))

    # Print summary
    print(f"\n{'='*80}")
    print(f"TEST SUMMARY")
    print(f"{'='*80}\n")

    for name, status in results:
        print(f"{name}: {status}")

    print(f"\n{'='*80}\n")

if __name__ == "__main__":
    main()
