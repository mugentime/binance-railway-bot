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

    state = {
        "level": manager.level,
        "in_position": manager.in_position,
        "current_symbol": manager.current_symbol,
        "current_direction": manager.current_direction,
        "entry_price": manager.entry_price,
        "entry_quantity": manager.entry_quantity,
        "current_size_usd": manager.current_size_usd,
        "entry_candle_time": manager.entry_candle_time,
        "last_max_loss_time": manager.last_max_loss_time,
        "cooldown_blacklist": manager.cooldown_blacklist,
        "max_adverse_excursion_pct": manager.max_adverse_excursion_pct,
        "mae_candle": manager.mae_candle,
        "consecutive_losses": manager.consecutive_losses,
        "regime_flipped": manager.regime_flipped,
        "chain_pnl_history": manager.chain_pnl_history,
        "saved_at": datetime.utcnow().isoformat(),
    }

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
            log(f"State saved: level={manager.level}, in_position={manager.in_position}")

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
            log(f"State loaded: level={state.get('level')}, in_position={state.get('in_position')}")
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
