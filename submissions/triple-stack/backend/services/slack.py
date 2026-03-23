"""
Slack and Teams integration service.

Provides helpers for:
- Formatting Slack responses
- Basic webhook verification
- Ticket notifications
"""

import os
import hmac
import hashlib
import time
from typing import Optional, Dict, Any, List

import httpx


class SlackTeamsService:
    """Service for Slack and Teams integrations."""

    def __init__(self):
        self.slack_signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
        self.slack_verification_token = os.getenv("SLACK_VERIFICATION_TOKEN", "")
        self.slack_default_channel = os.getenv("SLACK_DEFAULT_CHANNEL", "")
        self.teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")

    # ---------------------------------------------------------------------
    # Slack helpers
    # ---------------------------------------------------------------------

    def verify_slack_request(
        self,
        timestamp: str,
        body: str,
        signature: str,
    ) -> bool:
        """Verify Slack request signature if signing secret is configured."""
        if not self.slack_signing_secret:
            return True

        try:
            if abs(time.time() - int(timestamp)) > 60 * 5:
                return False
        except Exception:
            return False

        basestring = f"v0:{timestamp}:{body}".encode("utf-8")
        digest = hmac.new(
            self.slack_signing_secret.encode("utf-8"),
            basestring,
            hashlib.sha256,
        ).hexdigest()
        expected = f"v0={digest}"
        return hmac.compare_digest(expected, signature)

    def build_slack_ticket_message(
        self,
        ticket_id: str,
        title: str,
        priority: str,
        category: str,
        status: str = "open",
    ) -> Dict[str, Any]:
        """Build a Slack message payload for a ticket."""
        text = f"Ticket created: #{ticket_id} - {title}"
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*New Ticket Created*\n*ID:* {ticket_id}\n*Title:* {title}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Priority*\n{priority}"},
                    {"type": "mrkdwn", "text": f"*Category*\n{category}"},
                    {"type": "mrkdwn", "text": f"*Status*\n{status}"},
                ],
            },
        ]
        return {"response_type": "in_channel", "text": text, "blocks": blocks}

    # ---------------------------------------------------------------------
    # Teams helpers
    # ---------------------------------------------------------------------

    def build_teams_card(
        self,
        ticket_id: str,
        title: str,
        priority: str,
        category: str,
        status: str = "open",
    ) -> Dict[str, Any]:
        """Build a Teams adaptive card payload for a ticket."""
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "size": "Medium",
                                "weight": "Bolder",
                                "text": "New Ticket Created",
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "ID", "value": ticket_id},
                                    {"title": "Title", "value": title},
                                    {"title": "Priority", "value": priority},
                                    {"title": "Category", "value": category},
                                    {"title": "Status", "value": status},
                                ],
                            },
                        ],
                    },
                }
            ],
        }

    async def post_teams_message(self, payload: Dict[str, Any]) -> bool:
        """Post a message to Teams via incoming webhook."""
        if not self.teams_webhook_url:
            return False

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self.teams_webhook_url, json=payload)
            return resp.status_code in [200, 201, 202]


_service: Optional[SlackTeamsService] = None


def get_slack_teams_service() -> SlackTeamsService:
    """Get global Slack/Teams service instance."""
    global _service
    if _service is None:
        _service = SlackTeamsService()
    return _service
