"""
Slack alerts for campaign moderation — hard-blocks and escalations.

Standard Slack Incoming Webhook (one POST, no SDK). Silently no-ops if
unconfigured, and never raises — a failed Slack notification must not
break the actual moderation action it's reporting on.
"""

import logging

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


def notify_slack(text: str) -> None:
    if not settings.slack_webhook_url:
        logger.debug("SLACK_WEBHOOK_URL not configured, skipping notification")
        return

    try:
        httpx.post(settings.slack_webhook_url, json={"text": text}, timeout=5.0)
    except Exception as e:
        logger.warning(f"Slack notification failed: {e}")
