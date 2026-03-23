"""
Human-in-the-Loop Feedback Router.

Provides endpoints for:
- Submitting feedback on AI responses
- Viewing feedback statistics
- Managing corrections for retraining
- Acknowledging feedback items
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.connection import get_db
from database.models import AgentFeedback, Ticket, AiAuditLog, RetrainingJob
from schemas.models import (
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackStatsResponse,
)
from utils.exceptions import ValidationError, DatabaseError
from utils.websocket_manager import manager as ws_manager
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# Feedback Submission
# =============================================================================


@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(
    req: FeedbackCreateRequest,
    agent_id: str = Query(..., description="ID of agent submitting feedback"),
    db: Session = Depends(get_db),
):
    """
    Submit feedback on an AI response.

    Feedback types:
    - positive: AI response was helpful
    - negative: AI response was unhelpful or wrong
    - correction: Agent provides corrected response for retraining

    Corrections are queued for the retraining pipeline.
    """
    # Validate that at least one reference is provided
    if not req.ticket_id and not req.session_id:
        raise ValidationError(
            "reference", "Either ticket_id or session_id must be provided"
        )

    # Validate correction has correction text
    if req.feedback_type.value == "correction" and not req.agent_correction:
        raise ValidationError(
            "agent_correction", "Correction text required for correction feedback"
        )

    feedback = AgentFeedback(
        id=str(uuid.uuid4()),
        ticket_id=req.ticket_id,
        session_id=req.session_id,
        agent_id=agent_id,
        feedback_type=req.feedback_type.value,
        ai_response=req.ai_response,
        agent_correction=req.agent_correction,
        rating=req.rating,
        comments=req.comments,
        tags=req.tags,
        created_at=datetime.utcnow(),
        acknowledged=False,
    )

    try:
        db.add(feedback)

        # If it's a correction, create a retraining job entry
        if req.feedback_type.value == "correction":
            retraining_job = RetrainingJob(
                id=str(uuid.uuid4()),
                feedback_id=feedback.id,
                status="pending",
                created_at=datetime.utcnow(),
            )
            db.add(retraining_job)
            logger.info(f"Retraining job queued for feedback {feedback.id}")

        db.commit()
        db.refresh(feedback)

        # Notify via WebSocket
        await ws_manager.broadcast(
            {
                "type": "feedback_submitted",
                "feedback_id": feedback.id,
                "feedback_type": req.feedback_type.value,
                "ticket_id": req.ticket_id,
                "has_correction": bool(req.agent_correction),
            }
        )

        logger.info(f"Feedback submitted: {feedback.id} ({req.feedback_type.value})")

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to submit feedback: {e}")
        raise DatabaseError(f"Failed to submit feedback: {e}")

    return FeedbackResponse(
        id=feedback.id,
        feedback_type=feedback.feedback_type,
        ticket_id=feedback.ticket_id,
        session_id=feedback.session_id,
        rating=feedback.rating,
        created_at=str(feedback.created_at),
        acknowledged=feedback.acknowledged,
    )


@router.get("/", response_model=List[FeedbackResponse])
async def list_feedback(
    db: Session = Depends(get_db),
    feedback_type: Optional[str] = Query(None, description="Filter by type"),
    acknowledged: Optional[bool] = Query(
        None, description="Filter by acknowledged status"
    ),
    agent_id: Optional[str] = Query(None, description="Filter by agent"),
    ticket_id: Optional[str] = Query(None, description="Filter by ticket"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get feedback entries with filters."""
    query = db.query(AgentFeedback)

    if feedback_type:
        query = query.filter(AgentFeedback.feedback_type == feedback_type)
    if acknowledged is not None:
        query = query.filter(AgentFeedback.acknowledged == acknowledged)
    if agent_id:
        query = query.filter(AgentFeedback.agent_id == agent_id)
    if ticket_id:
        query = query.filter(AgentFeedback.ticket_id == ticket_id)

    feedback_items = (
        query.order_by(AgentFeedback.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        FeedbackResponse(
            id=f.id,
            feedback_type=f.feedback_type,
            ticket_id=f.ticket_id,
            session_id=f.session_id,
            rating=f.rating,
            created_at=str(f.created_at),
            acknowledged=f.acknowledged,
        )
        for f in feedback_items
    ]


@router.get("/corrections", response_model=List[dict])
async def get_corrections(
    db: Session = Depends(get_db),
    status: str = Query("pending", description="Filter by retraining status"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get AI corrections awaiting retraining.

    These are feedback entries where agents provided corrected responses.
    """
    query = (
        db.query(AgentFeedback)
        .join(RetrainingJob, AgentFeedback.id == RetrainingJob.feedback_id)
        .filter(
            AgentFeedback.feedback_type == "correction", RetrainingJob.status == status
        )
    )

    corrections = query.order_by(AgentFeedback.created_at.desc()).limit(limit).all()

    return [
        {
            "feedback_id": c.id,
            "ticket_id": c.ticket_id,
            "session_id": c.session_id,
            "original_response": c.ai_response,
            "corrected_response": c.agent_correction,
            "agent_id": c.agent_id,
            "comments": c.comments,
            "tags": c.tags,
            "created_at": str(c.created_at),
        }
        for c in corrections
    ]


# =============================================================================
# Feedback Actions
# =============================================================================


@router.post("/{feedback_id}/acknowledge")
async def acknowledge_feedback(
    feedback_id: str,
    db: Session = Depends(get_db),
):
    """Mark feedback as acknowledged (reviewed by admin)."""
    feedback = db.query(AgentFeedback).filter(AgentFeedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    feedback.acknowledged = True
    feedback.acknowledged_at = datetime.utcnow()

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to acknowledge feedback: {e}")

    return {"success": True, "feedback_id": feedback_id}


@router.post("/corrections/{feedback_id}/process")
async def process_correction(
    feedback_id: str,
    action: str = Query(..., description="Action: approve, reject, or defer"),
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Process a correction for retraining.

    Actions:
    - approve: Add to retraining dataset
    - reject: Discard the correction
    - defer: Keep pending for later review
    """
    if action not in ["approve", "reject", "defer"]:
        raise ValidationError("action", "Must be 'approve', 'reject', or 'defer'")

    job = (
        db.query(RetrainingJob).filter(RetrainingJob.feedback_id == feedback_id).first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Retraining job not found")

    if action == "approve":
        job.status = "approved"
        job.approved_at = datetime.utcnow()
    elif action == "reject":
        job.status = "rejected"
        job.rejected_at = datetime.utcnow()
    else:
        job.status = "deferred"

    if notes:
        job.notes = notes

    try:
        db.commit()
        logger.info(f"Correction {feedback_id} processed: {action}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to process correction: {e}")

    return {"success": True, "feedback_id": feedback_id, "action": action}


# =============================================================================
# Statistics
# =============================================================================


@router.get("/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365, description="Days to analyze"),
):
    """Get aggregated feedback statistics."""
    since = datetime.utcnow() - timedelta(days=days)

    # Count by type
    total = db.query(AgentFeedback).filter(AgentFeedback.created_at >= since).count()
    positive = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.created_at >= since, AgentFeedback.feedback_type == "positive"
        )
        .count()
    )
    negative = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.created_at >= since, AgentFeedback.feedback_type == "negative"
        )
        .count()
    )
    correction = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.created_at >= since,
            AgentFeedback.feedback_type == "correction",
        )
        .count()
    )

    # Average rating
    avg_rating_result = (
        db.query(func.avg(AgentFeedback.rating))
        .filter(AgentFeedback.created_at >= since, AgentFeedback.rating.isnot(None))
        .scalar()
    )
    avg_rating = float(avg_rating_result) if avg_rating_result else 0.0

    # Group by tags (for feedback_by_category)
    # Since tags is a JSON array, this is simplified
    feedback_by_category = {
        "positive": positive,
        "negative": negative,
        "correction": correction,
    }

    # Recent corrections
    recent = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.created_at >= since,
            AgentFeedback.feedback_type == "correction",
        )
        .order_by(AgentFeedback.created_at.desc())
        .limit(5)
        .all()
    )

    recent_corrections = [
        {
            "id": c.id,
            "ticket_id": c.ticket_id,
            "created_at": str(c.created_at),
            "has_correction": bool(c.agent_correction),
        }
        for c in recent
    ]

    return FeedbackStatsResponse(
        total_feedback=total,
        positive_count=positive,
        negative_count=negative,
        correction_count=correction,
        average_rating=round(avg_rating, 2),
        feedback_by_category=feedback_by_category,
        recent_corrections=recent_corrections,
    )


@router.get("/stats/by-agent")
async def get_feedback_by_agent(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Get feedback statistics grouped by agent."""
    since = datetime.utcnow() - timedelta(days=days)

    results = (
        db.query(
            AgentFeedback.agent_id,
            AgentFeedback.feedback_type,
            func.count(AgentFeedback.id).label("count"),
        )
        .filter(AgentFeedback.created_at >= since)
        .group_by(AgentFeedback.agent_id, AgentFeedback.feedback_type)
        .all()
    )

    # Organize by agent
    by_agent = {}
    for agent_id, feedback_type, count in results:
        if agent_id not in by_agent:
            by_agent[agent_id] = {"positive": 0, "negative": 0, "correction": 0}
        by_agent[agent_id][feedback_type] = count

    return {
        "period_days": days,
        "by_agent": by_agent,
    }


@router.get("/stats/ai-accuracy")
async def get_ai_accuracy_stats(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """
    Calculate AI accuracy based on feedback.

    Accuracy = (positive + (total - correction)) / total
    This treats corrections as "AI was wrong" cases.
    """
    since = datetime.utcnow() - timedelta(days=days)

    total = db.query(AgentFeedback).filter(AgentFeedback.created_at >= since).count()
    positive = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.created_at >= since, AgentFeedback.feedback_type == "positive"
        )
        .count()
    )
    correction = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.created_at >= since,
            AgentFeedback.feedback_type == "correction",
        )
        .count()
    )

    # Calculate accuracy
    if total > 0:
        # Positive feedback = correct
        # Corrections = incorrect
        # Negative feedback = unhelpful but not necessarily wrong
        accuracy = (positive / total) * 100 if total > 0 else 100.0
        correction_rate = (correction / total) * 100 if total > 0 else 0.0
    else:
        accuracy = 100.0
        correction_rate = 0.0

    return {
        "period_days": days,
        "total_feedback": total,
        "positive_feedback": positive,
        "corrections": correction,
        "estimated_accuracy": round(accuracy, 2),
        "correction_rate": round(correction_rate, 2),
        "recommendation": _get_accuracy_recommendation(accuracy, correction_rate),
    }


def _get_accuracy_recommendation(accuracy: float, correction_rate: float) -> str:
    """Generate recommendation based on accuracy metrics."""
    if accuracy >= 90 and correction_rate < 5:
        return "AI performing well. Continue monitoring."
    elif accuracy >= 80:
        return "AI performing adequately. Review recent corrections for patterns."
    elif accuracy >= 70:
        return "AI needs improvement. Consider retraining with correction data."
    else:
        return "AI accuracy is low. Urgent retraining recommended. Review deflection threshold."
