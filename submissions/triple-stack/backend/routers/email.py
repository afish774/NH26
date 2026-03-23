"""
Email Integration Router.

Provides endpoints for:
- Email-to-ticket ingestion
- Ticket reply notifications
- Inbox sync
- Email configuration visibility
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Ticket
from schemas.models import (
    EmailTicketCreateRequest,
    EmailTicketResponse,
    EmailReplyRequest,
    EmailReplyResponse,
    EmailConfigResponse,
)
from services.email import get_email_service, ParsedEmail
from utils.exceptions import DatabaseError, ValidationError
from utils.performance import track_time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email"])


# =============================================================================
# Email-to-Ticket Ingestion
# =============================================================================


@router.post("/incoming", response_model=EmailTicketResponse)
@track_time("email_incoming")
async def ingest_email(
    request: EmailTicketCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Ingest an incoming email and create or update a ticket.

    This endpoint is intended for email webhook integrations or polling systems.
    """
    email_service = get_email_service()

    try:
        received_at = (
            datetime.fromisoformat(request.received_at)
            if request.received_at
            else datetime.utcnow()
        )
    except Exception:
        raise ValidationError("received_at", "Invalid datetime format")

    parsed_email = ParsedEmail(
        message_id=request.headers.get("Message-ID") if request.headers else "",
        from_address=request.from_address,
        from_name=request.headers.get("From-Name", "") if request.headers else "",
        to_address=request.to_address,
        subject=request.subject,
        body_text=request.body_text,
        body_html=request.body_html,
        received_at=received_at,
        in_reply_to=request.headers.get("In-Reply-To") if request.headers else None,
        references=(
            request.headers.get("References", "").split()
            if request.headers and request.headers.get("References")
            else []
        ),
        attachments=request.attachments,
        headers=request.headers,
    )

    result = email_service.create_ticket_from_email(parsed_email, db)

    if not result.get("success"):
        raise HTTPException(
            status_code=500, detail=result.get("error", "Failed to process email")
        )

    ticket_id = result.get("ticket_id")

    ticket = None
    if ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    return EmailTicketResponse(
        ticket_id=ticket_id or "",
        title=ticket.title if ticket else parsed_email.subject,
        category=str(ticket.category.value) if ticket and ticket.category else "other",
        priority=str(ticket.priority.value) if ticket and ticket.priority else "medium",
        from_address=parsed_email.from_address,
        auto_reply_sent=bool(result.get("auto_reply_sent", False)),
        confidence=float(result.get("confidence", 0.0)),
    )


# =============================================================================
# Email Replies
# =============================================================================


@router.post("/reply", response_model=EmailReplyResponse)
@track_time("email_reply")
async def send_email_reply(
    request: EmailReplyRequest,
    db: Session = Depends(get_db),
):
    """
    Send an email reply for a ticket.
    """
    email_service = get_email_service()

    ticket = db.query(Ticket).filter(Ticket.id == request.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    subject = request.subject
    if not subject:
        subject = f"[Ticket #{ticket.id}] {ticket.title}"

    body_text = request.body

    if request.include_ticket_history:
        history = f"\n\n---\nTicket Summary:\n{ticket.description[:2000]}"
        body_text = f"{body_text}{history}"

    success, message_id = email_service.send_email(
        to_address=request.to_address,
        subject=subject,
        body_text=body_text,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to send email reply")

    return EmailReplyResponse(
        success=True,
        message_id=message_id,
        ticket_id=request.ticket_id,
        sent_at=datetime.utcnow().isoformat(),
    )


# =============================================================================
# Inbox Sync
# =============================================================================


@router.post("/sync")
@track_time("email_sync")
async def sync_inbox(db: Session = Depends(get_db)):
    """
    Sync the email inbox and process new messages.
    """
    email_service = get_email_service()

    try:
        results = await email_service.sync_inbox(db)
        return results
    except Exception as e:
        logger.error(f"Email sync failed: {e}")
        raise DatabaseError(f"Email sync failed: {e}")


# =============================================================================
# Configuration
# =============================================================================


@router.get("/config", response_model=EmailConfigResponse)
async def get_email_config():
    """
    Get current email configuration (read-only).
    """
    email_service = get_email_service()
    config = email_service.config

    return EmailConfigResponse(
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port,
        smtp_username=config.smtp_username,
        smtp_use_tls=config.smtp_use_tls,
        from_address=config.from_address,
        from_name=config.from_name,
        auto_reply_enabled=config.auto_reply_enabled,
        imap_configured=bool(config.imap_host and config.imap_username),
        last_sync=None,
    )
