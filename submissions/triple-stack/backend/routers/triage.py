"""
Triage Router - REST API for Ticket Triage System.

Provides endpoints for:
- Analyzing tickets for priority and routing
- Managing escalations
- Configuring SLA and escalation rules
- Routing tickets to agents
- Triage dashboard and statistics
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.connection import get_db
from database.models import Ticket, Agent, AiAuditLog
from schemas.models import (
    TriageAnalyzeRequest,
    TriageResultResponse,
    EscalationCheckRequest,
    EscalationResultResponse,
    ManualEscalationRequest,
    TriageRouteRequest,
    TriageRouteResponse,
    TriageBulkAnalyzeRequest,
    TriageBulkAnalyzeResponse,
    SLAConfigRequest,
    SLAConfigResponse,
    EscalationConfigRequest,
    EscalationConfigResponse,
    TriageDashboardResponse,
)
from ai.triage import (
    triage_engine,
    escalation_manager,
    triage_router as triage_router_service,
    run_escalation_check,
    DEFAULT_SLA_HOURS,
    ESCALATION_CONFIG,
)
from utils.performance import track_time
from utils.websocket_manager import manager as ws_manager

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triage", tags=["triage"])


# =============================================================================
# Triage Analysis Endpoints
# =============================================================================


@router.post("/analyze", response_model=TriageResultResponse)
@track_time("triage_analyze")
async def analyze_ticket(
    request: TriageAnalyzeRequest,
    db: Session = Depends(get_db),
):
    """
    Analyze a ticket and return triage recommendations.

    This endpoint evaluates:
    - Keywords indicating urgency
    - User/department priority
    - Sentiment analysis
    - Historical patterns

    Returns priority level, SLA, and routing recommendations.
    """
    try:
        result = triage_engine.analyze_ticket(
            title=request.title,
            description=request.description,
            user_id=request.user_id,
            department=request.department,
            sentiment_score=request.sentiment_score,
            category=request.category,
            db=db,
        )

        # Log to audit
        audit_log = AiAuditLog(
            action_type="triage_analysis",
            input_text=f"{request.title}: {request.description[:200]}",
            ai_output={
                "priority": result.priority,
                "score": result.score,
                "escalation_reasons": result.escalation_reasons,
            },
            confidence=result.confidence,
            model_used="triage_engine",
        )
        db.add(audit_log)
        db.commit()

        return TriageResultResponse(
            priority=result.priority,
            triage_level=result.triage_level.value,
            score=result.score,
            sla_hours=result.sla_hours,
            requires_manual_intervention=result.requires_manual_intervention,
            escalation_reasons=result.escalation_reasons,
            suggested_agent_skills=result.suggested_agent_skills,
            routing_notes=result.routing_notes,
            confidence=result.confidence,
        )

    except Exception as e:
        logger.error(f"Triage analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Triage analysis failed: {str(e)}")


@router.post("/analyze/bulk", response_model=TriageBulkAnalyzeResponse)
@track_time("triage_bulk_analyze")
async def bulk_analyze_tickets(
    request: TriageBulkAnalyzeRequest,
    db: Session = Depends(get_db),
):
    """
    Analyze multiple tickets for triage in a single request.

    Useful for batch processing or re-prioritizing a queue.
    """
    results = []
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for ticket_req in request.tickets:
        try:
            result = triage_engine.analyze_ticket(
                title=ticket_req.title,
                description=ticket_req.description,
                user_id=ticket_req.user_id,
                department=ticket_req.department,
                sentiment_score=ticket_req.sentiment_score,
                category=ticket_req.category,
                db=db,
            )

            results.append(
                TriageResultResponse(
                    priority=result.priority,
                    triage_level=result.triage_level.value,
                    score=result.score,
                    sla_hours=result.sla_hours,
                    requires_manual_intervention=result.requires_manual_intervention,
                    escalation_reasons=result.escalation_reasons,
                    suggested_agent_skills=result.suggested_agent_skills,
                    routing_notes=result.routing_notes,
                    confidence=result.confidence,
                )
            )

            counts[result.priority] += 1

        except Exception as e:
            logger.warning(f"Failed to analyze ticket: {e}")
            # Add a default result for failed analysis
            results.append(
                TriageResultResponse(
                    priority="medium",
                    triage_level="medium",
                    score=50.0,
                    sla_hours=24,
                    requires_manual_intervention=True,
                    escalation_reasons=["Analysis failed - manual review required"],
                    suggested_agent_skills=[],
                    routing_notes="Analysis error - requires manual triage",
                    confidence=0.0,
                )
            )
            counts["medium"] += 1

    return TriageBulkAnalyzeResponse(
        results=results,
        total_analyzed=len(results),
        critical_count=counts["critical"],
        high_count=counts["high"],
        medium_count=counts["medium"],
        low_count=counts["low"],
    )


@router.post("/ticket/{ticket_id}/analyze", response_model=TriageResultResponse)
@track_time("triage_ticket_analyze")
async def analyze_existing_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    Analyze an existing ticket for triage.

    Re-evaluates the ticket and optionally updates its priority.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    result = triage_engine.analyze_ticket(
        title=ticket.title,
        description=ticket.description or "",
        user_id=ticket.user_id or "unknown",
        department=None,  # Could be fetched from user profile
        sentiment_score=ticket.sentiment_score,
        category=ticket.category,
        db=db,
    )

    return TriageResultResponse(
        priority=result.priority,
        triage_level=result.triage_level.value,
        score=result.score,
        sla_hours=result.sla_hours,
        requires_manual_intervention=result.requires_manual_intervention,
        escalation_reasons=result.escalation_reasons,
        suggested_agent_skills=result.suggested_agent_skills,
        routing_notes=result.routing_notes,
        confidence=result.confidence,
    )


# =============================================================================
# Escalation Endpoints
# =============================================================================


@router.post("/escalation/check", response_model=EscalationResultResponse)
@track_time("escalation_check")
async def check_escalation(
    request: EscalationCheckRequest,
    db: Session = Depends(get_db),
):
    """
    Check if a ticket should be escalated based on SLA and other triggers.
    """
    result = escalation_manager.check_escalation(request.ticket_id, db)

    return EscalationResultResponse(
        ticket_id=request.ticket_id,
        should_escalate=result.should_escalate,
        new_priority=result.new_priority,
        reasons=[r.value for r in result.reasons],
        notification_targets=result.notification_targets,
        message=result.message,
    )


@router.post("/escalation/process/{ticket_id}")
@track_time("escalation_process")
async def process_escalation(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    Check and process escalation for a specific ticket.

    If escalation is needed, updates the ticket and sends notifications.
    """
    escalation = escalation_manager.check_escalation(ticket_id, db)

    if not escalation.should_escalate:
        return {
            "ticket_id": ticket_id,
            "escalated": False,
            "message": "No escalation required",
        }

    result = await escalation_manager.process_escalation(ticket_id, escalation, db)
    return result


@router.post("/escalation/manual")
@track_time("manual_escalation")
async def manual_escalation(
    request: ManualEscalationRequest,
    db: Session = Depends(get_db),
):
    """
    Manually escalate a ticket.

    Use this when an agent determines a ticket needs immediate attention
    regardless of automated triggers.
    """
    ticket = db.query(Ticket).filter(Ticket.id == request.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    old_priority = ticket.priority

    # Update priority if specified
    if request.new_priority:
        ticket.priority = request.new_priority
    else:
        # Auto-escalate to next level
        escalation_map = {
            "low": "medium",
            "medium": "high",
            "high": "critical",
            "critical": "critical",
        }
        ticket.priority = escalation_map.get(ticket.priority, "high")

    # Log the manual escalation
    audit_log = AiAuditLog(
        ticket_id=request.ticket_id,
        action_type="manual_escalation",
        input_text=request.reason,
        ai_output={
            "old_priority": old_priority,
            "new_priority": ticket.priority,
            "reason": request.reason,
        },
        confidence=1.0,
        model_used="manual",
    )
    db.add(audit_log)
    db.commit()

    # Send WebSocket notifications
    notification_targets = request.notify_agents or []

    for target_id in notification_targets:
        try:
            await ws_manager.broadcast_to_user(
                target_id,
                {
                    "type": "manual_escalation",
                    "ticket_id": request.ticket_id,
                    "reason": request.reason,
                    "old_priority": old_priority,
                    "new_priority": ticket.priority,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to notify agent {target_id}: {e}")

    # Broadcast to tickets channel
    await ws_manager.broadcast_to_channel(
        "tickets",
        {
            "type": "ticket_escalated",
            "ticket_id": request.ticket_id,
            "old_priority": old_priority,
            "new_priority": ticket.priority,
            "reason": request.reason,
            "manual": True,
        },
    )

    return {
        "success": True,
        "ticket_id": request.ticket_id,
        "old_priority": old_priority,
        "new_priority": ticket.priority,
        "notifications_sent": len(notification_targets),
    }


@router.post("/escalation/run-check")
@track_time("escalation_batch_check")
async def run_batch_escalation_check(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Run escalation check on all open tickets.

    This can be triggered manually or scheduled via cron.
    Returns immediately and processes in background.
    """
    # Get count of open tickets
    open_count = (
        db.query(Ticket)
        .filter(Ticket.status.in_(["open", "in_progress", "pending_feedback"]))
        .count()
    )

    # Run in background
    background_tasks.add_task(run_escalation_check, db)

    return {
        "message": "Escalation check started",
        "tickets_to_check": open_count,
        "status": "processing",
    }


# =============================================================================
# Routing Endpoints
# =============================================================================


@router.post("/route", response_model=TriageRouteResponse)
@track_time("triage_route")
async def route_ticket(
    request: TriageRouteRequest,
    db: Session = Depends(get_db),
):
    """
    Route a ticket to the best available agent based on triage analysis.

    Considers:
    - Agent skills and specializations
    - Current workload
    - Historical performance
    - Ticket requirements
    """
    ticket = db.query(Ticket).filter(Ticket.id == request.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # First, analyze the ticket
    triage_result = triage_engine.analyze_ticket(
        title=ticket.title,
        description=ticket.description or "",
        user_id=ticket.user_id or "unknown",
        category=ticket.category,
        db=db,
    )

    # Override skills if specified
    if request.force_skills:
        triage_result.suggested_agent_skills = request.force_skills

    # Route the ticket
    agent_id = await triage_router_service.route_ticket(
        request.ticket_id,
        triage_result,
        db,
    )

    if agent_id:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        agent_name = agent.name if agent else "Unknown"

        # Broadcast assignment via WebSocket
        await ws_manager.broadcast_to_channel(
            "tickets",
            {
                "type": "ticket_assigned",
                "ticket_id": request.ticket_id,
                "agent_id": agent_id,
                "agent_name": agent_name,
            },
        )

        return TriageRouteResponse(
            ticket_id=request.ticket_id,
            assigned_agent_id=agent_id,
            assigned_agent_name=agent_name,
            routing_score=triage_result.score,
            routing_reason=triage_result.routing_notes,
        )
    else:
        return TriageRouteResponse(
            ticket_id=request.ticket_id,
            assigned_agent_id=None,
            assigned_agent_name=None,
            routing_score=triage_result.score,
            routing_reason="No available agents matching requirements",
        )


@router.post("/route/auto/{ticket_id}")
@track_time("triage_auto_route")
async def auto_route_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """
    Automatically analyze, triage, and route a ticket in one step.

    Convenience endpoint that combines analyze + route.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Analyze
    triage_result = triage_engine.analyze_ticket(
        title=ticket.title,
        description=ticket.description or "",
        user_id=ticket.user_id or "unknown",
        sentiment_score=ticket.sentiment_score,
        category=ticket.category,
        db=db,
    )

    # Update ticket with triage results
    ticket.priority = triage_result.priority
    ticket.sla_hours = triage_result.sla_hours

    # Route
    agent_id = await triage_router_service.route_ticket(
        ticket_id,
        triage_result,
        db,
    )

    db.commit()

    return {
        "ticket_id": ticket_id,
        "triage": {
            "priority": triage_result.priority,
            "score": triage_result.score,
            "sla_hours": triage_result.sla_hours,
            "requires_manual": triage_result.requires_manual_intervention,
        },
        "routing": {
            "assigned_agent_id": agent_id,
            "routing_notes": triage_result.routing_notes,
        },
    }


# =============================================================================
# Configuration Endpoints
# =============================================================================


@router.get("/config/sla", response_model=SLAConfigResponse)
async def get_sla_config():
    """Get current SLA configuration."""
    return SLAConfigResponse(
        critical_hours=DEFAULT_SLA_HOURS["critical"],
        high_hours=DEFAULT_SLA_HOURS["high"],
        medium_hours=DEFAULT_SLA_HOURS["medium"],
        low_hours=DEFAULT_SLA_HOURS["low"],
        updated_at=datetime.utcnow().isoformat(),
    )


@router.put("/config/sla", response_model=SLAConfigResponse)
async def update_sla_config(request: SLAConfigRequest):
    """
    Update SLA configuration.

    Note: In production, this should persist to database or config store.
    """
    # Update the global config (in production, persist this)
    DEFAULT_SLA_HOURS["critical"] = request.critical_hours
    DEFAULT_SLA_HOURS["high"] = request.high_hours
    DEFAULT_SLA_HOURS["medium"] = request.medium_hours
    DEFAULT_SLA_HOURS["low"] = request.low_hours

    logger.info(f"SLA config updated: {DEFAULT_SLA_HOURS}")

    return SLAConfigResponse(
        critical_hours=request.critical_hours,
        high_hours=request.high_hours,
        medium_hours=request.medium_hours,
        low_hours=request.low_hours,
        updated_at=datetime.utcnow().isoformat(),
    )


@router.get("/config/escalation", response_model=EscalationConfigResponse)
async def get_escalation_config():
    """Get current escalation configuration."""
    return EscalationConfigResponse(
        sla_warning_threshold=ESCALATION_CONFIG["sla_warning_threshold"],
        sla_critical_threshold=ESCALATION_CONFIG["sla_critical_threshold"],
        max_reassignments=ESCALATION_CONFIG["max_reassignments"],
        idle_hours_escalate=ESCALATION_CONFIG["idle_hours_escalate"],
        updated_at=datetime.utcnow().isoformat(),
    )


@router.put("/config/escalation", response_model=EscalationConfigResponse)
async def update_escalation_config(request: EscalationConfigRequest):
    """
    Update escalation configuration.

    Note: In production, this should persist to database or config store.
    """
    ESCALATION_CONFIG["sla_warning_threshold"] = request.sla_warning_threshold
    ESCALATION_CONFIG["sla_critical_threshold"] = request.sla_critical_threshold
    ESCALATION_CONFIG["max_reassignments"] = request.max_reassignments
    ESCALATION_CONFIG["idle_hours_escalate"] = request.idle_hours_escalate

    logger.info(f"Escalation config updated: {ESCALATION_CONFIG}")

    return EscalationConfigResponse(
        sla_warning_threshold=request.sla_warning_threshold,
        sla_critical_threshold=request.sla_critical_threshold,
        max_reassignments=request.max_reassignments,
        idle_hours_escalate=request.idle_hours_escalate,
        updated_at=datetime.utcnow().isoformat(),
    )


# =============================================================================
# Dashboard Endpoint
# =============================================================================


@router.get("/dashboard", response_model=TriageDashboardResponse)
@track_time("triage_dashboard")
async def get_triage_dashboard(db: Session = Depends(get_db)):
    """
    Get triage system dashboard with statistics and configuration.
    """
    from datetime import timedelta

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Total tickets
    total_tickets = db.query(Ticket).count()

    # Pending triage (open without assignment)
    pending_triage = (
        db.query(Ticket)
        .filter(
            Ticket.status == "open",
            Ticket.agent_id.is_(None),
        )
        .count()
    )

    # Priority counts
    critical_tickets = (
        db.query(Ticket)
        .filter(
            Ticket.priority == "critical",
            Ticket.status.in_(["open", "in_progress"]),
        )
        .count()
    )

    high_tickets = (
        db.query(Ticket)
        .filter(
            Ticket.priority == "high",
            Ticket.status.in_(["open", "in_progress"]),
        )
        .count()
    )

    # SLA breaches
    breached_sla = (
        db.query(Ticket)
        .filter(
            Ticket.sla_breached == True,
            Ticket.status.in_(["open", "in_progress", "pending_feedback"]),
        )
        .count()
    )

    # Approaching SLA (within 75% of deadline)
    approaching_sla = (
        db.query(Ticket)
        .filter(
            Ticket.sla_deadline.isnot(None),
            Ticket.sla_deadline <= now + timedelta(hours=2),
            Ticket.sla_deadline > now,
            Ticket.status.in_(["open", "in_progress", "pending_feedback"]),
        )
        .count()
    )

    # Escalations today
    escalations_today = (
        db.query(AiAuditLog)
        .filter(
            AiAuditLog.action_type.in_(["escalation", "manual_escalation"]),
            AiAuditLog.created_at >= today_start,
        )
        .count()
    )

    # Average triage time (from audit logs)
    # This would require tracking triage duration - using placeholder
    avg_triage_time = 150.0  # ms placeholder

    return TriageDashboardResponse(
        total_tickets=total_tickets,
        pending_triage=pending_triage,
        critical_tickets=critical_tickets,
        high_tickets=high_tickets,
        breached_sla_count=breached_sla,
        approaching_sla_count=approaching_sla,
        escalations_today=escalations_today,
        avg_triage_time_ms=avg_triage_time,
        sla_config=SLAConfigResponse(
            critical_hours=DEFAULT_SLA_HOURS["critical"],
            high_hours=DEFAULT_SLA_HOURS["high"],
            medium_hours=DEFAULT_SLA_HOURS["medium"],
            low_hours=DEFAULT_SLA_HOURS["low"],
            updated_at=now.isoformat(),
        ),
        escalation_config=EscalationConfigResponse(
            sla_warning_threshold=ESCALATION_CONFIG["sla_warning_threshold"],
            sla_critical_threshold=ESCALATION_CONFIG["sla_critical_threshold"],
            max_reassignments=ESCALATION_CONFIG["max_reassignments"],
            idle_hours_escalate=ESCALATION_CONFIG["idle_hours_escalate"],
            updated_at=now.isoformat(),
        ),
    )


# =============================================================================
# Utility Endpoints
# =============================================================================


@router.get("/keywords")
async def get_triage_keywords():
    """
    Get the current keyword lists used for triage analysis.

    Useful for understanding how triage scoring works.
    """
    from ai.triage import CRITICAL_KEYWORDS, HIGH_PRIORITY_KEYWORDS, VIP_DEPARTMENTS

    return {
        "critical_keywords": CRITICAL_KEYWORDS,
        "high_priority_keywords": HIGH_PRIORITY_KEYWORDS,
        "vip_departments": VIP_DEPARTMENTS,
    }


@router.get("/queue")
@track_time("triage_queue")
async def get_triage_queue(
    limit: int = 20,
    include_assigned: bool = False,
    db: Session = Depends(get_db),
):
    """
    Get tickets awaiting triage, sorted by priority.

    Returns tickets that need attention, with triage scores.
    """
    query = db.query(Ticket).filter(Ticket.status.in_(["open", "pending_feedback"]))

    if not include_assigned:
        query = query.filter(Ticket.agent_id.is_(None))

    # Order by priority (critical first) and creation date
    priority_order = func.case(
        (Ticket.priority == "critical", 1),
        (Ticket.priority == "high", 2),
        (Ticket.priority == "medium", 3),
        else_=4,
    )

    tickets = query.order_by(priority_order, Ticket.created_at.asc()).limit(limit).all()

    queue_items = []
    for ticket in tickets:
        # Quick triage analysis
        triage_result = triage_engine.analyze_ticket(
            title=ticket.title,
            description=ticket.description or "",
            user_id=ticket.user_id or "unknown",
            category=ticket.category,
            db=db,
        )

        queue_items.append(
            {
                "ticket_id": str(ticket.id),
                "title": ticket.title,
                "current_priority": ticket.priority,
                "recommended_priority": triage_result.priority,
                "triage_score": triage_result.score,
                "requires_manual": triage_result.requires_manual_intervention,
                "sla_deadline": ticket.sla_deadline.isoformat()
                if ticket.sla_deadline
                else None,
                "created_at": ticket.created_at.isoformat()
                if ticket.created_at
                else None,
                "escalation_reasons": triage_result.escalation_reasons[:3],
            }
        )

    return {
        "queue": queue_items,
        "total": len(queue_items),
    }
