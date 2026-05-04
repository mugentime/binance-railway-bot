"""
Martingale Signal Scanner - Utility Functions
Logging, state persistence, helper functions
"""
import logging
import time
import json
import signal
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("martingale")

def log(msg, level="info"):
    """Log a message at specified level"""
    getattr(logger, level)(msg)

def save_state(manager, filepath="state.json"):
    """
    Save manager state to JSON file with atomic write and backup
    This prevents corruption if write fails or bot crashes during save
    """
    import os
    import shutil
    import tempfile

    state = manager.to_dict()
    state["saved_at"] = datetime.utcnow().isoformat()

    try:
        # Create backup of current state file (if exists)
        backup_path = f"{filepath}.backup"
        if os.path.exists(filepath):
            shutil.copy2(filepath, backup_path)

        # Write to temporary file first (atomic operation)
        temp_fd, temp_path = tempfile.mkstemp(suffix=".json", text=True)
        try:
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(state, f, indent=2)

            # Atomic move (overwrites target safely)
            shutil.move(temp_path, filepath)
            log(f"State saved: {manager.num_open} open positions")

        except Exception as e:
            # Clean up temp file if move failed
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    except Exception as e:
        log(f"ERROR: Failed to save state: {e}", "error")
        # Try to restore from backup if available
        if os.path.exists(backup_path) and not os.path.exists(filepath):
            shutil.copy2(backup_path, filepath)
            log(f"State restored from backup after save failure", "warning")
        raise Exception(f"Critical: State save failed - {e}")

def load_state(filepath="state.json"):
    """Load state from JSON file"""
    try:
        with open(filepath) as f:
            state = json.load(f)
            if "positions" in state:
                log(f"State loaded: {len(state['positions'])} positions")
            else:
                log(f"Old state format loaded (will reconcile from exchange)")
            return state
    except FileNotFoundError:
        log("No existing state file found, starting fresh")
        return None

def round_down(value, decimals):
    """Round down to specified decimal places"""
    factor = 10 ** decimals
    return int(value * factor) / factor

def round_to_precision(value, decimals):
    """Round to specified decimal places (standard rounding)"""
    return round(value, decimals)

def timestamp_ms():
    """Get current timestamp in milliseconds"""
    return int(time.time() * 1000)

def format_usd(value):
    """Format value as USD string"""
    return f"${value:.2f}"

def format_pct(value):
    """Format value as percentage string"""
    return f"{value * 100:.2f}%"

def setup_signal_handlers(manager):
    """Handle Railway graceful shutdown"""
    def signal_handler(sig, frame):
        log("Shutdown signal received, saving state...")
        save_state(manager)
        log("Shutdown complete")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
