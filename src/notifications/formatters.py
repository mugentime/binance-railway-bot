"""
Platform-specific formatters for webhook payloads
"""
from typing import Dict, Any
from .event_schemas import WebhookEvent


class DiscordFormatter:
    """Format events for Discord webhooks"""

    SEVERITY_COLORS = {
        "info": 0x3498db,      # Blue
        "warning": 0xf39c12,   # Orange
        "critical": 0xe74c3c   # Red
    }

    SEVERITY_EMOJIS = {
        "info": "ℹ️",
        "warning": "⚠️",
        "critical": "🚨"
    }

    def format(self, event: WebhookEvent) -> Dict[str, Any]:
        """Format event as Discord embed"""
        emoji = self.SEVERITY_EMOJIS[event.severity]
        color = self.SEVERITY_COLORS[event.severity]

        embed = {
            "embeds": [{
                "title": f"{emoji} {event.event_type.replace('_', ' ').title()}",
                "color": color,
                "timestamp": event.timestamp.isoformat(),
                "fields": self._build_fields(event),
                "footer": {
                    "text": f"{event.bot_id} | {event.environment}"
                }
            }]
        }

        # Add context if available
        if event.context:
            embed["embeds"][0]["fields"].append({
                "name": "Context",
                "value": self._format_context(event.context),
                "inline": False
            })

        return embed

    def _build_fields(self, event: WebhookEvent) -> list:
        """Convert event data to Discord fields"""
        fields = []

        for key, value in event.data.items():
            # Skip None values
            if value is None:
                continue

            fields.append({
                "name": key.replace('_', ' ').title(),
                "value": self._format_value(value),
                "inline": True
            })

        return fields

    def _format_value(self, value: Any) -> str:
        """Format value for display"""
        if isinstance(value, float):
            # Format numbers with appropriate precision
            if abs(value) < 0.01:
                return f"{value:.8f}"
            elif abs(value) < 1:
                return f"{value:.6f}"
            else:
                return f"{value:.4f}"
        elif isinstance(value, bool):
            return "✅ Yes" if value else "❌ No"
        return str(value)

    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context dictionary"""
        lines = []
        for key, value in context.items():
            lines.append(f"**{key.replace('_', ' ').title()}:** {self._format_value(value)}")
        return "\n".join(lines)


class SlackFormatter:
    """Format events for Slack webhooks"""

    SEVERITY_COLORS = {
        "info": "#36a64f",
        "warning": "#ff9900",
        "critical": "#ff0000"
    }

    SEVERITY_EMOJIS = {
        "info": ":information_source:",
        "warning": ":warning:",
        "critical": ":rotating_light:"
    }

    def format(self, event: WebhookEvent) -> Dict[str, Any]:
        """Format event as Slack attachment"""
        emoji = self.SEVERITY_EMOJIS[event.severity]

        return {
            "attachments": [{
                "color": self.SEVERITY_COLORS[event.severity],
                "title": f"{emoji} {event.event_type.replace('_', ' ').title()}",
                "text": self._build_text(event),
                "ts": int(event.timestamp.timestamp()),
                "footer": f"{event.bot_id} | {event.environment}"
            }]
        }

    def _build_text(self, event: WebhookEvent) -> str:
        """Build formatted text from event data"""
        lines = []

        # Add main data
        for key, value in event.data.items():
            if value is None:
                continue
            lines.append(f"*{key.replace('_', ' ').title()}:* {self._format_value(value)}")

        # Add context if available
        if event.context:
            lines.append("\n*Context:*")
            for key, value in event.context.items():
                lines.append(f"  • {key.replace('_', ' ').title()}: {self._format_value(value)}")

        return "\n".join(lines)

    def _format_value(self, value: Any) -> str:
        """Format value for display"""
        if isinstance(value, float):
            if abs(value) < 0.01:
                return f"{value:.8f}"
            elif abs(value) < 1:
                return f"{value:.6f}"
            else:
                return f"{value:.4f}"
        elif isinstance(value, bool):
            return "✓" if value else "✗"
        return str(value)


class GenericFormatter:
    """Generic JSON formatter for custom webhooks"""

    def format(self, event: WebhookEvent) -> Dict[str, Any]:
        """Return event as-is (JSON schema)"""
        return event.dict()
