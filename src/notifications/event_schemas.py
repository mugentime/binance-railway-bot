"""
Event schema definitions using Pydantic for type safety and JSON serialization
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Literal, Optional
from datetime import datetime


class WebhookEvent(BaseModel):
    """Base webhook event structure"""
    event_type: Literal[
        "position_entry",
        "position_exit",
        "order_failure",
        "tp_sl_integrity",
        "catastrophic_loss",
        "state_sync_issue",
        "health_check",
        "bot_startup",
        "bot_shutdown"
    ]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    severity: Literal["info", "warning", "critical"]
    bot_id: str = "binance-railway-bot"
    environment: str = Field(default="production")

    data: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class PositionEntryEvent(WebhookEvent):
    """Event triggered when a new position is opened"""
    event_type: Literal["position_entry"] = "position_entry"
    severity: Literal["info"] = "info"


class PositionExitEvent(WebhookEvent):
    """Event triggered when a position is closed"""
    event_type: Literal["position_exit"] = "position_exit"
    severity: Literal["info"] = "info"


class OrderFailureEvent(WebhookEvent):
    """Event triggered when an order fails to place"""
    event_type: Literal["order_failure"] = "order_failure"
    severity: Literal["warning"] = "warning"


class TPSLIntegrityEvent(WebhookEvent):
    """Event triggered when position is missing TP or SL orders"""
    event_type: Literal["tp_sl_integrity"] = "tp_sl_integrity"
    severity: Literal["critical"] = "critical"


class CatastrophicLossEvent(WebhookEvent):
    """Event triggered on large losses"""
    event_type: Literal["catastrophic_loss"] = "catastrophic_loss"
    severity: Literal["critical"] = "critical"


class StateSyncIssueEvent(WebhookEvent):
    """Event triggered when bot state doesn't match exchange"""
    event_type: Literal["state_sync_issue"] = "state_sync_issue"
    severity: Literal["warning"] = "warning"


class HealthCheckEvent(WebhookEvent):
    """Event for health check notifications"""
    event_type: Literal["health_check"] = "health_check"
    severity: Literal["info"] = "info"


class BotStartupEvent(WebhookEvent):
    """Event when monitoring bot starts"""
    event_type: Literal["bot_startup"] = "bot_startup"
    severity: Literal["info"] = "info"


class BotShutdownEvent(WebhookEvent):
    """Event when monitoring bot stops"""
    event_type: Literal["bot_shutdown"] = "bot_shutdown"
    severity: Literal["info"] = "info"
