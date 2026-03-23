"""
Triage System for Intelligent Ticket Prioritization and Routing.

This module provides:
- Automatic priority scoring based on multiple factors
- Escalation rules and triggers
- SLA-based routing for urgent tickets
- Manual intervention flagging for high-priority cases
- Workload-aware agent assignment
- Real-time triage updates via WebSocket

Triage Levels:
- CRITICAL: Immediate attention, auto-escalate to senior agents
- HIGH: Priority queue, strict SLA enforcement
- MEDIUM: Normal queue with monitoring
- LOW: Background queue, batch processing allowed
"""

import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Default SLA hours by priority
DEFAULT_SLA_HOURS = {
    "critical": 1,
    "high": 4,
    "medium": 24,
    "low": 72,
}

# Escalation thresholds
ESCALATION_CONFIG = {
    "sla_warning_threshold": 0.75,  # 75% of SLA elapsed = warning
    "sla_critical_threshold": 0.90,  # 90% of SLA elapsed = auto-escalate
    "max_reassignments": 3,  # Max times a ticket can be reassigned
    "idle_hours_escalate": 4,  # Escalate if no response after X hours
}

# Keywords that trigger priority boosts
CRITICAL_KEYWORDS = [
    "urgent",
    "emergency",
    "critical",
    "down",
    "outage",
    "production",
    "security breach",
    "data loss",
    "system failure",
    "cannot work",
    "completely blocked",
    "revenue impact",
    "ceo",
    "executive",
]

HIGH_PRIORITY_KEYWORDS = [
    "asap",
    "important",
    "deadline",
    "meeting",
    "presentation",
    "client",
    "customer",
    "demo",
    "broken",
    "not working",
]

# VIP users/departments that get priority boost
VIP_DEPARTMENTS = ["executive", "sales", "customer_success", "finance"]


# =============================================================================
# Data Classes
# =============================================================================


class TriageLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EscalationReason(str, Enum):
    SLA_BREACH = "sla_breach"
    SLA_WARNING = "sla_warning"
    KEYWORD_TRIGGER = "keyword_trigger"
    VIP_USER = "vip_user"
    SENTIMENT_NEGATIVE = "sentiment_negative"
    REPEATED_CONTACT = "repeated_contact"
    MANUAL_ESCALATION = "manual_escalation"
    IDLE_TIMEOUT = "idle_timeout"
    COMPLEXITY_HIGH = "complexity_high"


@dataclass
class TriageResult:
    """Result of triage analysis."""

    priority: str
    triage_level: TriageLevel
    score: float  # 0-100
    sla_hours: int
    requires_manual_intervention: bool
    escalation_reasons: List[str]
    suggested_agent_skills: List[str]
    routing_notes: str
    confidence: float


@dataclass
class EscalationResult:
    """Result of escalation check."""

    should_escalate: bool
    new_priority: Optional[str]
    reasons: List[EscalationReason]
    notification_targets: List[str]  # Agent IDs to notify
    message: str


# =============================================================================
# Triage Engine
# =============================================================================


class TriageEngine:
    """
    Intelligent triage engine for ticket prioritization.

    Analyzes tickets based on:
    - Content keywords
    - User/department priority
    - Historical patterns
    - Sentiment analysis
    - Current workload
    - SLA requirements
    """

    def __init__(self):
        self.critical_keywords = CRITICAL_KEYWORDS
        self.high_priority_keywords = HIGH_PRIORITY_KEYWORDS
        self.vip_departments = VIP_DEPARTMENTS

    def analyze_ticket(
        self,
        title: str,
        description: str,
        user_id: str,
        department: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        category: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> TriageResult:
        """
        Analyze a ticket and return triage recommendations.

        Args:
            title: Ticket title
            description: Ticket description
            user_id: User who created the ticket
            department: User's department
            sentiment_score: AI-detected sentiment (-1 to 1)
            category: Ticket category
            db: Database session for historical analysis

        Returns:
            TriageResult with priority, score, and recommendations
        """
        score = 50.0  # Base score (medium)
        escalation_reasons = []
        suggested_skills = []

        combined_text = f"{title} {description}".lower()

        # ─────────────────────────────────────────────────────────────────────
        # 1. Keyword Analysis
        # ─────────────────────────────────────────────────────────────────────

        critical_matches = [kw for kw in self.critical_keywords if kw in combined_text]
        high_matches = [kw for kw in self.high_priority_keywords if kw in combined_text]

        if critical_matches:
            score += 40
            escalation_reasons.append(
                f"Critical keywords: {', '.join(critical_matches[:3])}"
            )
        elif high_matches:
            score += 20
            escalation_reasons.append(
                f"High priority keywords: {', '.join(high_matches[:3])}"
            )

        # ─────────────────────────────────────────────────────────────────────
        # 2. VIP/Department Analysis
        # ─────────────────────────────────────────────────────────────────────

        if department and department.lower() in [
            d.lower() for d in self.vip_departments
        ]:
            score += 15
            escalation_reasons.append(f"VIP department: {department}")

        # ─────────────────────────────────────────────────────────────────────
        # 3. Sentiment Analysis
        # ─────────────────────────────────────────────────────────────────────

        if sentiment_score is not None:
            if sentiment_score < -0.5:  # Very negative
                score += 15
                escalation_reasons.append("Highly negative sentiment")
            elif sentiment_score < -0.2:  # Negative
                score += 8
                escalation_reasons.append("Negative sentiment")

        # ─────────────────────────────────────────────────────────────────────
        # 4. Historical Analysis (if DB provided)
        # ─────────────────────────────────────────────────────────────────────

        if db:
            from database.models import Ticket

            # Check for repeated contacts (same user, multiple tickets recently)
            recent_tickets = (
                db.query(Ticket)
                .filter(
                    Ticket.user_id == user_id,
                    Ticket.created_at >= datetime.utcnow() - timedelta(days=7),
                )
                .count()
            )

            if recent_tickets >= 3:
                score += 10
                escalation_reasons.append(
                    f"Repeated contact ({recent_tickets} tickets in 7 days)"
                )

        # ─────────────────────────────────────────────────────────────────────
        # 5. Category-Based Skills
        # ─────────────────────────────────────────────────────────────────────

        if category:
            category_skills = {
                "network": ["networking", "infrastructure"],
                "hardware": ["hardware", "desktop_support"],
                "software": ["software", "applications"],
                "access": ["identity", "security"],
                "billing": ["billing", "finance"],
                "security": ["security", "compliance"],
            }
            suggested_skills = category_skills.get(category.lower(), [])

        # ─────────────────────────────────────────────────────────────────────
        # 6. Complexity Detection
        # ─────────────────────────────────────────────────────────────────────

        # Long descriptions may indicate complex issues
        if len(description) > 500:
            score += 5
            suggested_skills.append("complex_issues")

        # Technical jargon detection
        technical_terms = [
            "error code",
            "stack trace",
            "log",
            "api",
            "database",
            "server",
            "timeout",
        ]
        if any(term in combined_text for term in technical_terms):
            suggested_skills.append("technical")

        # ─────────────────────────────────────────────────────────────────────
        # Calculate Final Priority
        # ─────────────────────────────────────────────────────────────────────

        score = min(100, max(0, score))  # Clamp to 0-100

        if score >= 85:
            priority = "critical"
            triage_level = TriageLevel.CRITICAL
            sla_hours = DEFAULT_SLA_HOURS["critical"]
            requires_manual = True
        elif score >= 65:
            priority = "high"
            triage_level = TriageLevel.HIGH
            sla_hours = DEFAULT_SLA_HOURS["high"]
            requires_manual = score >= 75
        elif score >= 40:
            priority = "medium"
            triage_level = TriageLevel.MEDIUM
            sla_hours = DEFAULT_SLA_HOURS["medium"]
            requires_manual = False
        else:
            priority = "low"
            triage_level = TriageLevel.LOW
            sla_hours = DEFAULT_SLA_HOURS["low"]
            requires_manual = False

        # Generate routing notes
        routing_notes = self._generate_routing_notes(
            priority, escalation_reasons, suggested_skills
        )

        return TriageResult(
            priority=priority,
            triage_level=triage_level,
            score=score,
            sla_hours=sla_hours,
            requires_manual_intervention=requires_manual,
            escalation_reasons=escalation_reasons,
            suggested_agent_skills=list(set(suggested_skills)),
            routing_notes=routing_notes,
            confidence=min(1.0, score / 100 + 0.2),
        )

    def _generate_routing_notes(
        self, priority: str, reasons: List[str], skills: List[str]
    ) -> str:
        """Generate human-readable routing notes."""
        notes = []

        if priority == "critical":
            notes.append("URGENT: Requires immediate attention.")
        elif priority == "high":
            notes.append("Priority: Route to available senior agent.")

        if reasons:
            notes.append(f"Escalation triggers: {'; '.join(reasons[:3])}")

        if skills:
            notes.append(f"Suggested skills: {', '.join(skills)}")

        return " ".join(notes) if notes else "Standard routing."


# =============================================================================
# Escalation Manager
# =============================================================================


class EscalationManager:
    """
    Manages ticket escalation based on SLA and other triggers.

    Monitors tickets and escalates when:
    - SLA is about to breach
    - Ticket has been idle too long
    - Manual escalation requested
    - Customer sentiment degrades
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or ESCALATION_CONFIG

    def check_escalation(
        self,
        ticket_id: str,
        db: Session,
    ) -> EscalationResult:
        """
        Check if a ticket should be escalated.

        Args:
            ticket_id: Ticket to check
            db: Database session

        Returns:
            EscalationResult with escalation decision
        """
        from database.models import Ticket, Agent

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return EscalationResult(
                should_escalate=False,
                new_priority=None,
                reasons=[],
                notification_targets=[],
                message="Ticket not found",
            )

        reasons = []
        should_escalate = False
        new_priority = None
        notification_targets = []

        # ─────────────────────────────────────────────────────────────────────
        # 1. SLA Check
        # ─────────────────────────────────────────────────────────────────────

        if ticket.sla_deadline:
            now = datetime.utcnow()
            time_to_deadline = (ticket.sla_deadline - now).total_seconds()
            total_sla_time = (ticket.sla_hours or 24) * 3600

            elapsed_ratio = (
                1 - (time_to_deadline / total_sla_time) if total_sla_time > 0 else 1
            )

            if elapsed_ratio >= 1.0:  # SLA breached
                reasons.append(EscalationReason.SLA_BREACH)
                should_escalate = True
                new_priority = self._escalate_priority(ticket.priority)
            elif elapsed_ratio >= self.config["sla_critical_threshold"]:
                reasons.append(EscalationReason.SLA_WARNING)
                should_escalate = True

        # ─────────────────────────────────────────────────────────────────────
        # 2. Idle Time Check
        # ─────────────────────────────────────────────────────────────────────

        last_activity = ticket.updated_at or ticket.created_at
        idle_hours = (datetime.utcnow() - last_activity).total_seconds() / 3600

        if idle_hours >= self.config["idle_hours_escalate"]:
            if ticket.status in ["open", "in_progress"]:
                reasons.append(EscalationReason.IDLE_TIMEOUT)
                should_escalate = True

        # ─────────────────────────────────────────────────────────────────────
        # 3. Determine Notification Targets
        # ─────────────────────────────────────────────────────────────────────

        if should_escalate:
            # Get available senior agents
            senior_agents = (
                db.query(Agent)
                .filter(
                    Agent.is_available == True,
                    Agent.role.in_(["senior", "supervisor", "manager"]),
                )
                .limit(3)
                .all()
            )

            notification_targets = [str(a.id) for a in senior_agents]

            # Also notify current assignee's supervisor if assigned
            if ticket.agent_id:
                notification_targets.append(str(ticket.agent_id))

        # ─────────────────────────────────────────────────────────────────────
        # Generate Message
        # ─────────────────────────────────────────────────────────────────────

        if should_escalate:
            reason_strs = [r.value for r in reasons]
            message = f"Ticket {ticket_id} escalated: {', '.join(reason_strs)}"
        else:
            message = "No escalation required"

        return EscalationResult(
            should_escalate=should_escalate,
            new_priority=new_priority,
            reasons=reasons,
            notification_targets=notification_targets,
            message=message,
        )

    def _escalate_priority(self, current_priority: str) -> str:
        """Escalate to next priority level."""
        escalation_map = {
            "low": "medium",
            "medium": "high",
            "high": "critical",
            "critical": "critical",  # Can't escalate further
        }
        return escalation_map.get(current_priority, "high")

    async def process_escalation(
        self,
        ticket_id: str,
        escalation: EscalationResult,
        db: Session,
    ) -> Dict[str, Any]:
        """
        Process an escalation decision.

        Updates ticket priority and sends notifications.
        """
        from database.models import Ticket, AiAuditLog
        from utils.websocket_manager import manager as ws_manager

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return {"success": False, "error": "Ticket not found"}

        old_priority = ticket.priority

        # Update priority if needed
        if escalation.new_priority:
            ticket.priority = escalation.new_priority
            ticket.sla_breached = True

        # Log the escalation
        audit_log = AiAuditLog(
            ticket_id=ticket_id,
            action_type="escalation",
            input_text=f"Escalation check for ticket {ticket_id}",
            ai_output={
                "old_priority": old_priority,
                "new_priority": escalation.new_priority,
                "reasons": [r.value for r in escalation.reasons],
            },
            confidence=1.0,
            model_used="triage_engine",
        )
        db.add(audit_log)
        db.commit()

        # Send WebSocket notifications
        for target_id in escalation.notification_targets:
            try:
                await ws_manager.broadcast_to_user(
                    target_id,
                    {
                        "type": "escalation_alert",
                        "ticket_id": ticket_id,
                        "message": escalation.message,
                        "priority": escalation.new_priority or ticket.priority,
                        "reasons": [r.value for r in escalation.reasons],
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to notify {target_id}: {e}")

        # Broadcast to escalation channel
        await ws_manager.broadcast_to_channel(
            "tickets",
            {
                "type": "ticket_escalated",
                "ticket_id": ticket_id,
                "old_priority": old_priority,
                "new_priority": escalation.new_priority or ticket.priority,
                "reasons": [r.value for r in escalation.reasons],
            },
        )

        return {
            "success": True,
            "ticket_id": ticket_id,
            "escalated": True,
            "new_priority": escalation.new_priority,
            "notifications_sent": len(escalation.notification_targets),
        }


# =============================================================================
# Triage Router (Smart Agent Assignment)
# =============================================================================


class TriageRouter:
    """
    Routes tickets to the best available agent based on triage results.

    Considers:
    - Agent skills and specializations
    - Current workload
    - Historical performance
    - Ticket priority and requirements
    """

    def __init__(self):
        self.triage_engine = TriageEngine()

    async def route_ticket(
        self,
        ticket_id: str,
        triage_result: TriageResult,
        db: Session,
    ) -> Optional[str]:
        """
        Route a ticket to the best available agent.

        Args:
            ticket_id: Ticket to route
            triage_result: Triage analysis result
            db: Database session

        Returns:
            Agent ID if assigned, None otherwise
        """
        from database.models import Agent, Ticket

        # Get available agents
        query = db.query(Agent).filter(Agent.is_available == True)

        # Filter by skills if specified
        if triage_result.suggested_agent_skills:
            # This is simplified - in production, use proper JSON/array queries
            pass

        agents = query.all()

        if not agents:
            logger.warning(f"No available agents for ticket {ticket_id}")
            return None

        # Score agents
        scored_agents = []
        for agent in agents:
            score = self._score_agent(agent, triage_result)
            scored_agents.append((agent, score))

        # Sort by score (highest first)
        scored_agents.sort(key=lambda x: x[1], reverse=True)

        # Assign to best agent
        best_agent = scored_agents[0][0]

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if ticket:
            ticket.agent_id = best_agent.id
            ticket.status = "in_progress"
            best_agent.queue_depth = (best_agent.queue_depth or 0) + 1
            db.commit()

            logger.info(f"Ticket {ticket_id} assigned to agent {best_agent.name}")
            return str(best_agent.id)

        return None

    def _score_agent(self, agent, triage_result: TriageResult) -> float:
        """Score an agent for a ticket based on multiple factors."""
        score = 100.0

        # Penalize high workload
        queue_depth = agent.queue_depth or 0
        score -= queue_depth * 10

        # Boost for matching specialization
        if agent.specialization:
            spec = (
                str(agent.specialization.value)
                if hasattr(agent.specialization, "value")
                else str(agent.specialization)
            )
            if spec in triage_result.suggested_agent_skills:
                score += 30

        # Boost for high satisfaction scores
        if agent.satisfaction_score:
            score += agent.satisfaction_score * 5

        # Boost for fast resolution times
        if agent.avg_resolution_minutes:
            if agent.avg_resolution_minutes < 30:
                score += 20
            elif agent.avg_resolution_minutes < 60:
                score += 10

        # Critical tickets should go to senior agents
        if triage_result.priority == "critical":
            if hasattr(agent, "role") and agent.role in ["senior", "supervisor"]:
                score += 25

        return max(0, score)


# =============================================================================
# Background Triage Tasks
# =============================================================================


async def run_escalation_check(db: Session) -> List[Dict[str, Any]]:
    """
    Run escalation check on all open tickets.

    Should be called periodically (e.g., every 5 minutes).
    """
    from database.models import Ticket

    manager = EscalationManager()
    results = []

    # Get all non-resolved tickets
    open_tickets = (
        db.query(Ticket)
        .filter(Ticket.status.in_(["open", "in_progress", "pending"]))
        .all()
    )

    for ticket in open_tickets:
        escalation = manager.check_escalation(str(ticket.id), db)

        if escalation.should_escalate:
            result = await manager.process_escalation(str(ticket.id), escalation, db)
            results.append(result)

    logger.info(f"Escalation check complete: {len(results)} tickets escalated")
    return results


# =============================================================================
# Global Instances
# =============================================================================

triage_engine = TriageEngine()
escalation_manager = EscalationManager()
triage_router = TriageRouter()


def get_triage_engine() -> TriageEngine:
    """Get global triage engine instance."""
    return triage_engine


def get_escalation_manager() -> EscalationManager:
    """Get global escalation manager instance."""
    return escalation_manager


def get_triage_router() -> TriageRouter:
    """Get global triage router instance."""
    return triage_router
