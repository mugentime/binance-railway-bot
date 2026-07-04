"""
Load webhook configuration from environment variables
"""
import os
from typing import Dict, List


def load_webhook_config() -> Dict[str, List[str]]:
    """Load webhook URLs from environment variables"""
    config = {
        "critical": [],
        "warning": [],
        "info": []
    }

    # Collect all webhook URLs by severity
    for severity in ["critical", "warning", "info"]:
        # Check for platform-specific webhooks
        for platform in ["discord", "slack", "ifttt", "custom"]:
            env_var = f"WEBHOOK_{platform.upper()}_{severity.upper()}"
            url = os.getenv(env_var)
            if url:
                config[severity].append(url)

        # Check for "all" webhooks that receive all severities
        for platform in ["discord", "slack", "ifttt", "custom"]:
            env_var = f"WEBHOOK_{platform.upper()}_ALL"
            url = os.getenv(env_var)
            if url and url not in config[severity]:
                config[severity].append(url)

    return config


def get_notifier_settings() -> Dict[str, any]:
    """Load notifier configuration"""
    return {
        "timeout": int(os.getenv("WEBHOOK_TIMEOUT", "10")),
        "max_retries": int(os.getenv("WEBHOOK_MAX_RETRIES", "3")),
        "retry_backoff": float(os.getenv("WEBHOOK_RETRY_BACKOFF", "2.0"))
    }


def get_monitoring_settings() -> Dict[str, any]:
    """Load monitoring daemon settings"""
    return {
        "check_interval": int(os.getenv("MONITORING_CHECK_INTERVAL", "30")),  # seconds
        "tp_sl_check_delay": int(os.getenv("MONITORING_TP_SL_CHECK_DELAY", "5")),  # seconds after position entry
        "loss_threshold_usd": float(os.getenv("MONITORING_LOSS_THRESHOLD", "200.0")),
        "warning_loss_usd": float(os.getenv("MONITORING_WARNING_LOSS", "50.0")),
    }
