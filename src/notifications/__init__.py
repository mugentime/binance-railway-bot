"""
Webhook-based notification system for trading bot monitoring
Lightweight, flexible, works with Discord, Slack, IFTTT, Zapier, custom endpoints
"""

from .webhook_notifier import WebhookNotifier
from .event_schemas import (
    WebhookEvent,
    PositionEntryEvent,
    PositionExitEvent,
    OrderFailureEvent,
    TPSLIntegrityEvent,
    CatastrophicLossEvent,
    StateSyncIssueEvent
)
from .formatters import DiscordFormatter, SlackFormatter, GenericFormatter

__all__ = [
    'WebhookNotifier',
    'WebhookEvent',
    'PositionEntryEvent',
    'PositionExitEvent',
    'OrderFailureEvent',
    'TPSLIntegrityEvent',
    'CatastrophicLossEvent',
    'StateSyncIssueEvent',
    'DiscordFormatter',
    'SlackFormatter',
    'GenericFormatter',
]
