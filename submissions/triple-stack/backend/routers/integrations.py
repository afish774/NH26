"""
Slack/Teams Integration Router.

Provides endpoints for:
- Slack events and slash commands
- Teams incoming webhooks
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Ticket
from schemas.models import (
    SlackWebhookEvent,
    SlackCommandRequest,
    SlackTicketCreateRequest,
    SlackMessageResponse,
    TeamsWebhookEvent,
    TeamsCardResponse,
)
from services.slack import get_slack_teams_service
from ai.classifier import classify_ticket
from ai.triage import triage_engine
from utils.performance import track_time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


# =============================================================================
# Slack Events
# =============================================================================


@router.post("/slack/events")
@track_time("slack_events")
async def slack_events(request: Request):
    """
    Handle Slack event subscriptions.
    """
    body = await request.body()
    payload = await request.json()

    service = get_slack_teams_service()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    signature = request.headers.get("X-Slack-Signature", "")

    if not service.verify_slack_request(timestamp, body.decode("utf-8"), signature):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    return {"ok": True}


# =============================================================================
# Slack Slash Commands
# =============================================================================


@router.post("/slack/command", response_model=SlackMessageResponse)
@track_time("slack_command")
async def slack_command(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Handle Slack slash commands.

    Supported commands:
    - /ticket <title> | <description>
    """
    form = await request.form()
    command = form.get("command")
    text = form.get("text", "")

    if command != "/ticket":
        return SlackMessageResponse(
            response_type="ephemeral",
            text="Unsupported command. Use /ticket <title> | <description>",
        )

    if "|" not in text:
        return SlackMessageResponse(
            response_type="ephemeral",
            text="Usage: /ticket <title> | <description>",
        )

    title, description = [part.strip() for part in text.split("|", 1)]

    classification = classify_ticket(title, description)
    triage_result = triage_engine.analyze_ticket(
        title=title,
        description=description,
        user_id=form.get("user_id", "slack_user"),
        db=db,
    )

    from database.models import Ticket
    import uuid
    from datetime import datetime, timedelta

    ticket = Ticket(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        category=classification.get("category", "other"),
        priority=triage_result.priority,
        status="open",
        user_id=form.get("user_id", "slack_user"),
        ai_confidence=classification.get("confidence", 0.0),
        sentiment=classification.get("sentiment", "neutral"),
        sla_hours=triage_result.sla_hours,
        sla_deadline=datetime.utcnow() + timedelta(hours=triage_result.sla_hours),
    )

    db.add(ticket)
    db.commit()

    service = get_slack_teams_service()
    return SlackMessageResponse(
        **service.build_slack_ticket_message(
            ticket_id=ticket.id,
            title=ticket.title,
            priority=str(ticket.priority.value)
            if ticket.priority
            else triage_result.priority,
            category=str(ticket.category.value) if ticket.category else "other",
            status=str(ticket.status.value) if ticket.status else "open",
        )
    )


# =============================================================================
# Teams Webhook
# =============================================================================


@router.post("/teams/webhook", response_model=TeamsCardResponse)
@track_time("teams_webhook")
async def teams_webhook(
    payload: TeamsWebhookEvent,
    db: Session = Depends(get_db),
):
    """
    Handle Teams webhook events.

    For simplicity, this endpoint echoes a help response.
    """
    service = get_slack_teams_service()
    card = service.build_teams_card(
        ticket_id="example",
        title="Teams integration active",
        priority="medium",
        category="general",
        status="ok",
    )

    return TeamsCardResponse(**card)
