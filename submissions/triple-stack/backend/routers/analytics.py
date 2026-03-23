"""
==============================================================================
Analytics Router
==============================================================================

Provides dashboard metrics and analytics for NexDesk.
Includes ticket statistics, deflection rates, SLA compliance, and trends.

Endpoints:
    GET /api/analytics/ - Main dashboard metrics
    GET /api/analytics/trends - Ticket trends over time
    GET /api/analytics/performance - AI performance metrics

==============================================================================
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.connection import get_db
from database.models import Ticket, ChatMessage, TicketStatus, AiAuditLog
from utils.exceptions import DatabaseError, error_response
from utils.performance import PerformanceMonitor, track_time, get_metrics

logger = logging.getLogger("nexdesk.analytics")

router = APIRouter()


@router.get("/")
@track_time("analytics_dashboard")
async def get_analytics(db: Session = Depends(get_db)):
    """
    Get main dashboard analytics.

    Returns comprehensive metrics including:
    - Ticket counts by status
    - AI deflection rates
    - SLA compliance
    - Distribution by category, priority, sentiment

    Raises:
        DatabaseError: If database queries fail
    """
    try:
        # ─────────────────────────────────────────────────────────────────────
        # TICKET STATISTICS
        # ─────────────────────────────────────────────────────────────────────

        total = db.query(Ticket).count()
        resolved = (
            db.query(Ticket).filter(Ticket.status == TicketStatus.resolved).count()
        )
        open_t = db.query(Ticket).filter(Ticket.status == TicketStatus.open).count()
        in_progress = (
            db.query(Ticket).filter(Ticket.status == TicketStatus.in_progress).count()
        )

        # ─────────────────────────────────────────────────────────────────────
        # DEFLECTION METRICS
        # ─────────────────────────────────────────────────────────────────────

        total_chats = db.query(ChatMessage).filter(ChatMessage.role == "user").count()

        deflected = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.role == "user",
                ChatMessage.was_deflected == True,  # noqa: E712
            )
            .count()
        )

        deflection_rate = (
            round(deflected / total_chats * 100, 1) if total_chats > 0 else 0.0
        )

        # ─────────────────────────────────────────────────────────────────────
        # DISTRIBUTIONS
        # ─────────────────────────────────────────────────────────────────────

        by_category = (
            db.query(Ticket.category, func.count(Ticket.id))
            .group_by(Ticket.category)
            .all()
        )

        by_priority = (
            db.query(Ticket.priority, func.count(Ticket.id))
            .group_by(Ticket.priority)
            .all()
        )

        by_sentiment = (
            db.query(Ticket.sentiment, func.count(Ticket.id))
            .filter(
                Ticket.sentiment.isnot(None)  # Proper NULL check
            )
            .group_by(Ticket.sentiment)
            .all()
        )

        # ─────────────────────────────────────────────────────────────────────
        # SLA METRICS
        # ─────────────────────────────────────────────────────────────────────

        sla_breached = (
            db.query(Ticket)
            .filter(
                Ticket.sla_deadline < datetime.utcnow(),
                Ticket.status != TicketStatus.resolved,
            )
            .count()
        )

        # ─────────────────────────────────────────────────────────────────────
        # AI CONFIDENCE
        # ─────────────────────────────────────────────────────────────────────

        avg_conf_result = db.query(func.avg(Ticket.ai_confidence)).scalar()
        avg_conf = float(avg_conf_result) if avg_conf_result is not None else 0.0

        logger.info(
            f"Analytics retrieved: {total} tickets, {deflection_rate}% deflection rate"
        )

        return {
            "total_tickets": total,
            "resolved": resolved,
            "open": open_t,
            "in_progress": in_progress,
            "deflection_rate": deflection_rate,
            "total_deflected": deflected,
            "total_chats": total_chats,
            "sla_breached": sla_breached,
            "avg_ai_confidence": round(avg_conf, 2),
            "by_category": [
                {"category": c or "unknown", "count": n} for c, n in by_category
            ],
            "by_priority": [
                {"priority": p or "medium", "count": n} for p, n in by_priority
            ],
            "by_sentiment": [
                {"sentiment": s or "neutral", "count": n} for s, n in by_sentiment
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    except Exception as e:
        logger.exception(f"Analytics query failed: {e}")
        raise DatabaseError(
            message=f"Failed to retrieve analytics: {str(e)}",
            details={"error_type": type(e).__name__},
        )


@router.get("/trends")
@track_time("analytics_trends")
async def get_trends(
    days: int = Query(default=7, ge=1, le=90, description="Number of days to analyze"),
    db: Session = Depends(get_db),
):
    """
    Get ticket trends over time.

    Args:
        days: Number of days to analyze (1-90)

    Returns:
        Daily ticket counts and status breakdown
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Get daily ticket counts
        # Note: This is SQLite-compatible; PostgreSQL would use DATE_TRUNC
        daily_tickets = (
            db.query(
                func.date(Ticket.created_at).label("date"),
                func.count(Ticket.id).label("count"),
            )
            .filter(Ticket.created_at >= cutoff)
            .group_by(func.date(Ticket.created_at))
            .order_by(func.date(Ticket.created_at))
            .all()
        )

        # Get daily resolution counts
        daily_resolved = (
            db.query(
                func.date(Ticket.resolved_at).label("date"),
                func.count(Ticket.id).label("count"),
            )
            .filter(Ticket.resolved_at >= cutoff, Ticket.resolved_at.isnot(None))
            .group_by(func.date(Ticket.resolved_at))
            .order_by(func.date(Ticket.resolved_at))
            .all()
        )

        # Get daily deflection counts
        daily_deflections = (
            db.query(
                func.date(ChatMessage.created_at).label("date"),
                func.count(ChatMessage.id).label("count"),
            )
            .filter(
                ChatMessage.created_at >= cutoff,
                ChatMessage.role == "user",
                ChatMessage.was_deflected == True,  # noqa: E712
            )
            .group_by(func.date(ChatMessage.created_at))
            .order_by(func.date(ChatMessage.created_at))
            .all()
        )

        return {
            "period_days": days,
            "start_date": cutoff.isoformat() + "Z",
            "end_date": datetime.utcnow().isoformat() + "Z",
            "daily_tickets": [{"date": str(d), "count": c} for d, c in daily_tickets],
            "daily_resolved": [{"date": str(d), "count": c} for d, c in daily_resolved],
            "daily_deflections": [
                {"date": str(d), "count": c} for d, c in daily_deflections
            ],
        }

    except Exception as e:
        logger.exception(f"Trends query failed: {e}")
        raise DatabaseError(
            message=f"Failed to retrieve trends: {str(e)}",
            details={"days": days, "error_type": type(e).__name__},
        )


@router.get("/performance")
@track_time("analytics_performance")
async def get_performance_metrics():
    """
    Get AI and system performance metrics.

    Returns:
        Performance statistics including latency, throughput, and error rates
    """
    try:
        # Get performance metrics from the monitoring system
        metrics = get_metrics()

        # Add some computed metrics
        operations = metrics.get("operations", {})

        # Calculate overall health score
        slow_count = sum(op.get("slow_count", 0) for op in operations.values())
        total_count = sum(op.get("count", 0) for op in operations.values())

        health_score = (
            round((1 - slow_count / total_count) * 100, 1) if total_count > 0 else 100.0
        )

        return {
            "health_score": health_score,
            "total_operations": total_count,
            "slow_operations": slow_count,
            "operations": operations,
            "slow_operations_last_5min": metrics.get("slow_operations_last_5min", 0),
            "generated_at": metrics.get("generated_at"),
        }

    except Exception as e:
        logger.exception(f"Performance metrics query failed: {e}")
        # Don't fail hard - return minimal response
        return {
            "health_score": None,
            "error": str(e),
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }


@router.get("/ai-audit")
@track_time("analytics_ai_audit")
async def get_ai_audit_summary(
    hours: int = Query(default=24, ge=1, le=168, description="Hours to analyze"),
    db: Session = Depends(get_db),
):
    """
    Get AI decision audit summary.

    Shows how AI decisions are being made and their accuracy.

    Args:
        hours: Number of hours to analyze (1-168)

    Returns:
        Summary of AI deflection/escalation decisions with confidence distribution
    """
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Count by action type
        by_action = (
            db.query(AiAuditLog.action_type, func.count(AiAuditLog.id))
            .filter(AiAuditLog.created_at >= cutoff)
            .group_by(AiAuditLog.action_type)
            .all()
        )

        # Average confidence by action type
        avg_conf_by_action = (
            db.query(AiAuditLog.action_type, func.avg(AiAuditLog.confidence))
            .filter(AiAuditLog.created_at >= cutoff)
            .group_by(AiAuditLog.action_type)
            .all()
        )

        # Count by model used
        by_model = (
            db.query(AiAuditLog.model_used, func.count(AiAuditLog.id))
            .filter(AiAuditLog.created_at >= cutoff)
            .group_by(AiAuditLog.model_used)
            .all()
        )

        # Average latency
        avg_latency = (
            db.query(func.avg(AiAuditLog.latency_ms))
            .filter(AiAuditLog.created_at >= cutoff)
            .scalar()
            or 0.0
        )

        return {
            "period_hours": hours,
            "start_time": cutoff.isoformat() + "Z",
            "by_action": [{"action": a, "count": c} for a, c in by_action],
            "avg_confidence_by_action": [
                {"action": a, "avg_confidence": round(float(c or 0), 3)}
                for a, c in avg_conf_by_action
            ],
            "by_model": [{"model": m or "unknown", "count": c} for m, c in by_model],
            "avg_latency_ms": round(float(avg_latency), 2),
        }

    except Exception as e:
        logger.exception(f"AI audit query failed: {e}")
        raise DatabaseError(
            message=f"Failed to retrieve AI audit data: {str(e)}",
            details={"hours": hours, "error_type": type(e).__name__},
        )
