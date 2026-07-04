"""
Lightweight webhook-only notification system
Minimal dependencies (uses existing httpx), maximum flexibility
"""
import httpx
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import logging
from .event_schemas import WebhookEvent
from .formatters import DiscordFormatter, SlackFormatter, GenericFormatter

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """Lightweight webhook-only notification system"""

    def __init__(
        self,
        webhook_urls: Dict[str, List[str]],
        timeout: int = 10,
        max_retries: int = 3,
        retry_backoff: float = 2.0
    ):
        """
        Args:
            webhook_urls: Dict mapping severity to list of webhook URLs
                Example: {
                    "critical": ["discord_url", "slack_url"],
                    "warning": ["discord_url"],
                    "info": ["logging_url"]
                }
            timeout: HTTP request timeout in seconds
            max_retries: Max retry attempts on failure
            retry_backoff: Exponential backoff multiplier
        """
        self.webhook_urls = webhook_urls
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.client = httpx.AsyncClient(timeout=timeout)

        # Auto-detect platform from URL
        self.formatters = {
            'discord': DiscordFormatter(),
            'slack': SlackFormatter(),
            'generic': GenericFormatter()
        }

        # Metrics
        self.metrics = {
            "sent": 0,
            "failed": 0,
            "retries": 0,
            "by_severity": {"info": 0, "warning": 0, "critical": 0},
        }

    def _detect_platform(self, url: str) -> str:
        """Auto-detect webhook platform from URL"""
        if 'discord.com' in url:
            return 'discord'
        elif 'hooks.slack.com' in url:
            return 'slack'
        else:
            return 'generic'

    async def send_event(self, event: WebhookEvent) -> None:
        """Send event to all configured webhooks for its severity"""
        urls = self.webhook_urls.get(event.severity, [])

        if not urls:
            logger.debug(f"No webhooks configured for severity: {event.severity}")
            return

        # Update metrics
        self.metrics["by_severity"][event.severity] += 1

        # Send to all webhooks in parallel
        tasks = [self._send_to_webhook(url, event) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for failures
        failures = sum(1 for r in results if isinstance(r, Exception))
        if failures > 0:
            self.metrics["failed"] += failures
        else:
            self.metrics["sent"] += len(urls)

    async def _send_to_webhook(self, url: str, event: WebhookEvent) -> None:
        """Send event to single webhook with retry logic"""
        platform = self._detect_platform(url)
        formatter = self.formatters[platform]
        payload = formatter.format(event)

        for attempt in range(self.max_retries):
            try:
                response = await self.client.post(url, json=payload)
                response.raise_for_status()
                logger.info(f"Webhook sent successfully to {platform} (attempt {attempt + 1})")
                return

            except httpx.HTTPStatusError as e:
                logger.warning(f"Webhook failed (HTTP {e.response.status_code}): {url[:50]}...")

                if e.response.status_code == 429:  # Rate limit
                    await asyncio.sleep(self.retry_backoff ** attempt * 2)
                    self.metrics["retries"] += 1
                elif e.response.status_code >= 500:  # Server error
                    await asyncio.sleep(self.retry_backoff ** attempt)
                    self.metrics["retries"] += 1
                else:  # Client error (4xx) - don't retry
                    break

            except httpx.TimeoutException:
                logger.warning(f"Webhook timeout (attempt {attempt + 1}): {url[:50]}...")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_backoff ** attempt)
                    self.metrics["retries"] += 1

            except Exception as e:
                logger.error(f"Webhook error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_backoff ** attempt)
                    self.metrics["retries"] += 1

        logger.error(f"Webhook failed after {self.max_retries} attempts: {url[:50]}...")

    async def health_check(self) -> Dict[str, bool]:
        """Test all configured webhooks"""
        results = {}

        from .event_schemas import HealthCheckEvent

        test_event = HealthCheckEvent(
            data={"status": "testing", "message": "Webhook health check"}
        )

        for severity, urls in self.webhook_urls.items():
            for url in urls:
                try:
                    platform = self._detect_platform(url)
                    formatter = self.formatters[platform]
                    payload = formatter.format(test_event)

                    response = await self.client.post(url, json=payload)
                    response.raise_for_status()
                    results[f"{severity}_{url[:30]}"] = True
                except Exception as e:
                    logger.error(f"Webhook health check failed: {url[:50]}... - {e}")
                    results[f"{severity}_{url[:30]}"] = False

        return results

    def get_metrics(self) -> Dict:
        """Return webhook metrics"""
        return self.metrics

    async def close(self):
        """Cleanup HTTP client"""
        await self.client.aclose()
