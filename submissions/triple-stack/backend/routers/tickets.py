"""
Ticket management router.

Provides endpoints for:
- AI-assisted ticket creation (automatic classification)
- Manual ticket creation (human-created without AI)
- Ticket retrieval and updates
- Ticket assignment to agents
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from database.connection import get_db
from database.models import Ticket, TicketStatus, AiAuditLog, Agent
from schemas.models import (
    CreateTicketRequest,
    UpdateStatusRequest,
    ManualTicketRequest,
    TicketAssignRequest,
    TicketListResponse,
    TicketDetailResponse,
)
from ai.classifier import classify_ticket
from utils.exceptions import TicketNotFoundError, ValidationError, DatabaseError
from utils.routing import get_agent_router
from utils.websocket_manager import manager as ws_manager
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", response_model=TicketDetailResponse)
async def create_ticket(req: CreateTicketRequest, db: Session = Depends(get_db)):
    """
    Create a ticket with AI-assisted classification.

    The AI will:
    - Classify the ticket category
    - Determine priority based on content
    - Generate a summary and suggested reply
    - Set SLA deadline based on priority
    """
    try:
        classification = classify_ticket(req.title, req.description)
    except Exception as e:
        logger.error(f"AI classification failed: {e}")
        # Fallback to manual classification if AI fails
        classification = {
            "category": "General",
            "priority": "medium",
            "summary": req.description[:200],
            "suggested_reply": "Thank you for contacting support. An agent will assist you shortly.",
            "confidence": 0.0,
            "sla_hours": 24,
            "sentiment": "neutral",
            "sentiment_score": 0.5,
        }

    ticket = Ticket(
        id=str(uuid.uuid4()),
        title=req.title,
        description=req.description,
        category=classification["category"],
        priority=classification["priority"],
        ai_summary=classification["summary"],
        ai_suggested_reply=classification["suggested_reply"],
        ai_confidence=classification["confidence"],
        sentiment=classification.get("sentiment"),
        sentiment_score=classification.get("sentiment_score"),
        sla_deadline=datetime.utcnow() + timedelta(hours=classification["sla_hours"]),
        sla_hours=classification["sla_hours"],
        user_id=req.user_id,
        voice_transcript=req.voice_transcript,
        screenshot_key=req.screenshot_key,
        is_manual=False,  # AI-created ticket
    )

    try:
        db.add(ticket)

        # Audit log for AI classification
        db.add(
            AiAuditLog(
                ticket_id=ticket.id,
                action_type="classify",
                input_text=f"{req.title} {req.description}"[:500],
                ai_output=classification,
                confidence=classification["confidence"],
                model_used="bedrock" if classification.get("aws_used") else "groq",
                latency_ms=classification.get("latency_ms", 0),
                aws_used=classification.get("aws_used", False),
            )
        )
        db.commit()
        db.refresh(ticket)

        # Notify via WebSocket
        await ws_manager.broadcast(
            {
                "type": "ticket_created",
                "ticket_id": ticket.id,
                "title": ticket.title,
                "priority": ticket.priority,
                "category": ticket.category,
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Database error during ticket creation: {e}")
        raise DatabaseError(f"Failed to create ticket: {e}")

    return _ticket_to_response(ticket)


@router.post("/manual", response_model=TicketDetailResponse)
async def create_manual_ticket(req: ManualTicketRequest, db: Session = Depends(get_db)):
    """
    Create a ticket manually without AI classification.

    Use this endpoint when:
    - An agent creates a ticket on behalf of a customer
    - A ticket is created from a phone call
    - AI classification should be bypassed

    The agent must provide category and priority manually.
    """
    # Validate priority
    valid_priorities = ["low", "medium", "high", "critical"]
    if req.priority.lower() not in valid_priorities:
        raise ValidationError(f"Invalid priority. Must be one of: {valid_priorities}")

    # Calculate SLA based on priority
    sla_hours_map = {
        "critical": 4,
        "high": 8,
        "medium": 24,
        "low": 72,
    }
    sla_hours = sla_hours_map.get(req.priority.lower(), 24)

    ticket = Ticket(
        id=str(uuid.uuid4()),
        title=req.title,
        description=req.description,
        category=req.category,
        priority=req.priority.lower(),
        ai_summary=None,  # No AI summary for manual tickets
        ai_suggested_reply=None,
        ai_confidence=0.0,  # No AI confidence
        sentiment=None,
        sentiment_score=None,
        sla_deadline=datetime.utcnow() + timedelta(hours=sla_hours),
        sla_hours=sla_hours,
        user_id=req.user_id,
        is_manual=True,  # Manual ticket flag
        created_by=req.created_by,  # Agent who created it
        agent_id=req.assign_to,  # Pre-assign if specified
        tags=req.tags if req.tags else [],
    )

    try:
        db.add(ticket)

        # Audit log for manual creation
        db.add(
            AiAuditLog(
                ticket_id=ticket.id,
                action_type="manual_create",
                input_text=f"Manual ticket by {req.created_by}: {req.title}"[:500],
                ai_output={"manual": True, "created_by": req.created_by},
                confidence=0.0,
                model_used="none",
                latency_ms=0,
                aws_used=False,
            )
        )
        db.commit()
        db.refresh(ticket)

        # Notify via WebSocket
        await ws_manager.broadcast(
            {
                "type": "ticket_created",
                "ticket_id": ticket.id,
                "title": ticket.title,
                "priority": ticket.priority,
                "category": ticket.category,
                "is_manual": True,
                "created_by": req.created_by,
            }
        )

        logger.info(f"Manual ticket created: {ticket.id} by {req.created_by}")

    except Exception as e:
        db.rollback()
        logger.error(f"Database error during manual ticket creation: {e}")
        raise DatabaseError(f"Failed to create manual ticket: {e}")

    return _ticket_to_response(ticket)


@router.get("/", response_model=List[TicketListResponse])
async def get_tickets(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    category: Optional[str] = Query(None, description="Filter by category"),
    agent_id: Optional[str] = Query(None, description="Filter by assigned agent"),
    is_manual: Optional[bool] = Query(None, description="Filter by manual/AI-created"),
    sla_breached: Optional[bool] = Query(
        None, description="Filter by SLA breach status"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Get all tickets with optional filters.
    """
    query = db.query(Ticket)

    # Apply filters
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if category:
        query = query.filter(Ticket.category == category)
    if agent_id:
        query = query.filter(Ticket.agent_id == agent_id)
    if is_manual is not None:
        query = query.filter(Ticket.is_manual == is_manual)
    if sla_breached is not None:
        query = query.filter(Ticket.sla_breached == sla_breached)

    tickets = query.order_by(Ticket.created_at.desc()).offset(offset).limit(limit).all()

    return [
        TicketListResponse(
            id=t.id,
            title=t.title,
            status=t.status,
            priority=t.priority,
            category=t.category,
            ai_confidence=t.ai_confidence or 0.0,
            sentiment=t.sentiment,
            sla_deadline=str(t.sla_deadline) if t.sla_deadline else None,
            sla_breached=t.sla_breached or False,
            agent_id=t.agent_id,
            is_manual=t.is_manual or False,
            created_at=str(t.created_at),
        )
        for t in tickets
    ]


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    """Get detailed information about a specific ticket."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise TicketNotFoundError(ticket_id)
    return _ticket_to_response(ticket)


@router.patch("/{ticket_id}/status")
async def update_status(
    ticket_id: str, req: UpdateStatusRequest, db: Session = Depends(get_db)
):
    """Update ticket status."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise TicketNotFoundError(ticket_id)

    valid_statuses = ["open", "in_progress", "pending", "resolved", "closed"]
    if req.status.lower() not in valid_statuses:
        raise ValidationError(f"Invalid status. Must be one of: {valid_statuses}")

    old_status = ticket.status
    ticket.status = req.status.lower()

    if req.status.lower() in ["resolved", "closed"]:
        ticket.resolved_at = datetime.utcnow()

    try:
        db.commit()

        # Notify via WebSocket
        await ws_manager.broadcast(
            {
                "type": "ticket_status_changed",
                "ticket_id": ticket_id,
                "old_status": old_status,
                "new_status": req.status,
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Database error during ticket update: {e}")
        raise DatabaseError(f"Failed to update ticket status: {e}")

    return {"success": True, "ticket_id": ticket_id, "status": req.status}


@router.patch("/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: str, req: TicketAssignRequest, db: Session = Depends(get_db)
):
    """
    Assign a ticket to an agent.

    If agent_id is None, the ticket will be unassigned.
    If use_smart_routing is True, the system will automatically select the best agent.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise TicketNotFoundError(ticket_id)

    agent_id = req.agent_id

    # Use smart routing if requested
    if req.use_smart_routing and not agent_id:
        agent_router = get_agent_router()
        agent_id = await agent_router.route_ticket(ticket, db, strategy="smart")

    # Validate agent exists if specified
    if agent_id:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            raise ValidationError(f"Agent {agent_id} not found")

    old_agent = ticket.agent_id
    ticket.agent_id = agent_id

    try:
        db.commit()

        # Notify via WebSocket
        await ws_manager.broadcast(
            {
                "type": "ticket_assigned",
                "ticket_id": ticket_id,
                "old_agent_id": old_agent,
                "new_agent_id": agent_id,
            }
        )

        # Notify the assigned agent specifically
        if agent_id:
            await ws_manager.send_to_user(
                agent_id,
                {
                    "type": "ticket_assigned_to_you",
                    "ticket_id": ticket_id,
                    "title": ticket.title,
                    "priority": ticket.priority,
                },
            )

    except Exception as e:
        db.rollback()
        logger.error(f"Database error during ticket assignment: {e}")
        raise DatabaseError(f"Failed to assign ticket: {e}")

    return {
        "success": True,
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "smart_routing_used": req.use_smart_routing,
    }


@router.delete("/{ticket_id}")
async def delete_ticket(ticket_id: str, db: Session = Depends(get_db)):
    """
    Delete a ticket (soft delete - marks as closed).

    Tickets are never hard-deleted to maintain audit trail.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise TicketNotFoundError(ticket_id)

    ticket.status = "closed"
    ticket.resolved_at = datetime.utcnow()

    try:
        db.commit()
        logger.info(f"Ticket {ticket_id} soft-deleted (closed)")
    except Exception as e:
        db.rollback()
        logger.error(f"Database error during ticket deletion: {e}")
        raise DatabaseError(f"Failed to delete ticket: {e}")

    return {"success": True, "ticket_id": ticket_id, "action": "soft_deleted"}


@router.get("/{ticket_id}/audit")
async def get_ticket_audit_log(ticket_id: str, db: Session = Depends(get_db)):
    """Get all AI audit logs for a specific ticket."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise TicketNotFoundError(ticket_id)

    logs = (
        db.query(AiAuditLog)
        .filter(AiAuditLog.ticket_id == ticket_id)
        .order_by(AiAuditLog.timestamp.desc())
        .all()
    )

    return [
        {
            "id": log.id,
            "action_type": log.action_type,
            "input_text": log.input_text,
            "ai_output": log.ai_output,
            "confidence": log.confidence,
            "model_used": log.model_used,
            "latency_ms": log.latency_ms,
            "aws_used": log.aws_used,
            "timestamp": str(log.timestamp),
        }
        for log in logs
    ]


def _ticket_to_response(ticket: Ticket) -> TicketDetailResponse:
    """Convert a Ticket model to TicketDetailResponse."""
    return TicketDetailResponse(
        id=ticket.id,
        title=ticket.title,
        description=ticket.description,
        status=ticket.status,
        priority=ticket.priority,
        category=ticket.category,
        ai_summary=ticket.ai_summary,
        ai_suggested_reply=ticket.ai_suggested_reply,
        ai_confidence=ticket.ai_confidence or 0.0,
        sentiment=ticket.sentiment,
        sentiment_score=ticket.sentiment_score,
        sla_deadline=str(ticket.sla_deadline) if ticket.sla_deadline else None,
        sla_hours=ticket.sla_hours,
        sla_breached=ticket.sla_breached or False,
        user_id=ticket.user_id,
        agent_id=ticket.agent_id,
        is_manual=ticket.is_manual or False,
        created_by=ticket.created_by,
        voice_transcript=ticket.voice_transcript,
        screenshot_key=ticket.screenshot_key,
        tags=ticket.tags or [],
        created_at=str(ticket.created_at),
        resolved_at=str(ticket.resolved_at) if ticket.resolved_at else None,
    )
