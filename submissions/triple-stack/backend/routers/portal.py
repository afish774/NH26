"""
Self-Service Portal API Router.

Provides endpoints for:
- Ticket status checks
- FAQ listing and search
- Ticket submission
- Adding comments
"""

import uuid
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Ticket
from schemas.models import (
    PortalTicketStatusRequest,
    PortalTicketStatusResponse,
    PortalFAQResponse,
    PortalFAQListResponse,
    PortalSearchRequest,
    PortalSearchResponse,
    PortalSubmitRequest,
    PortalSubmitResponse,
    PortalCommentRequest,
    PortalCommentResponse,
)
from ai.knowledge_base import KNOWLEDGE_BASE
from ai.classifier import classify_ticket
from ai.triage import triage_engine
from utils.performance import track_time

router = APIRouter(prefix="/portal", tags=["portal"])


# =============================================================================
# Ticket Status
# =============================================================================


@router.post("/ticket/status", response_model=PortalTicketStatusResponse)
@track_time("portal_ticket_status")
async def check_ticket_status(
    request: PortalTicketStatusRequest,
    db: Session = Depends(get_db),
):
    ticket = db.query(Ticket).filter(Ticket.id == request.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    updated_at = ticket.updated_at or ticket.created_at
    return PortalTicketStatusResponse(
        ticket_id=str(ticket.id),
        title=ticket.title,
        status=str(ticket.status.value) if ticket.status else "open",
        priority=str(ticket.priority.value) if ticket.priority else "medium",
        created_at=ticket.created_at.isoformat() if ticket.created_at else "",
        updated_at=updated_at.isoformat() if updated_at else "",
        estimated_resolution=None,
        last_update_message=ticket.ai_suggested_reply,
        can_add_comment=True,
    )


# =============================================================================
# FAQs
# =============================================================================


@router.get("/faqs", response_model=PortalFAQListResponse)
@track_time("portal_faqs")
async def list_faqs():
    categories = sorted({item.get("category", "general") for item in KNOWLEDGE_BASE})
    faqs = [
        PortalFAQResponse(
            id=item.get("id", ""),
            question=item.get("question", ""),
            answer=item.get("answer", ""),
            category=item.get("category", "general"),
            helpful_count=0,
            views=0,
        )
        for item in KNOWLEDGE_BASE
    ]

    return PortalFAQListResponse(
        categories=categories,
        faqs=faqs,
        total=len(faqs),
    )


@router.post("/search", response_model=PortalSearchResponse)
@track_time("portal_search")
async def search_faqs(request: PortalSearchRequest):
    query = request.query.lower()
    results = []

    for item in KNOWLEDGE_BASE:
        if (
            query in item.get("question", "").lower()
            or query in item.get("answer", "").lower()
        ):
            results.append(item)

    limited = results[: request.limit]
    formatted = [
        {
            "id": item.get("id"),
            "question": item.get("question"),
            "answer": item.get("answer"),
            "category": item.get("category"),
        }
        for item in limited
    ]

    return PortalSearchResponse(
        query=request.query,
        results=formatted,
        total_results=len(results),
        suggested_queries=[],
    )


# =============================================================================
# Ticket Submission
# =============================================================================


@router.post("/submit", response_model=PortalSubmitResponse)
@track_time("portal_submit")
async def submit_ticket(
    request: PortalSubmitRequest,
    db: Session = Depends(get_db),
):
    classification = classify_ticket(request.subject, request.description)
    triage_result = triage_engine.analyze_ticket(
        title=request.subject,
        description=request.description,
        user_id=request.email,
        category=request.category,
        db=db,
    )

    ticket = Ticket(
        id=str(uuid.uuid4()),
        title=request.subject,
        description=request.description,
        category=classification.get("category", "other"),
        priority=triage_result.priority,
        status="open",
        user_id=request.email,
        ai_confidence=classification.get("confidence", 0.0),
        sentiment=classification.get("sentiment", "neutral"),
        sla_hours=triage_result.sla_hours,
        sla_deadline=datetime.utcnow() + timedelta(hours=triage_result.sla_hours),
    )

    db.add(ticket)
    db.commit()

    tracking_code = ticket.id[:8]
    similar_faqs = []

    for item in KNOWLEDGE_BASE[:3]:
        similar_faqs.append(
            PortalFAQResponse(
                id=item.get("id", ""),
                question=item.get("question", ""),
                answer=item.get("answer", ""),
                category=item.get("category", "general"),
                helpful_count=0,
                views=0,
            )
        )

    return PortalSubmitResponse(
        ticket_id=ticket.id,
        tracking_code=tracking_code,
        estimated_response_hours=triage_result.sla_hours,
        auto_reply_sent=False,
        similar_faqs=similar_faqs,
    )


# =============================================================================
# Ticket Comments
# =============================================================================


@router.post("/comment", response_model=PortalCommentResponse)
@track_time("portal_comment")
async def add_comment(
    request: PortalCommentRequest,
    db: Session = Depends(get_db),
):
    ticket = db.query(Ticket).filter(Ticket.id == request.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.description = f"{ticket.description}\n\n---\nPortal comment from {request.email}:\n{request.comment}"
    ticket.updated_at = datetime.utcnow()

    db.commit()

    return PortalCommentResponse(
        success=True,
        comment_id=str(uuid.uuid4()),
        ticket_id=request.ticket_id,
        added_at=datetime.utcnow().isoformat(),
    )
