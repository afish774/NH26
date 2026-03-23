"""
Agent Assignment & Routing System.

This module provides:
- Agent assignment strategies (round_robin, specialization, load_balanced, smart)
- Ticket routing and escalation
- Agent workload management
"""

import os
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import Agent, Ticket, Category, TicketStatus, Priority


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_STRATEGY = os.getenv("ROUTING_STRATEGY", "smart")


class AgentRouter:
    """
    Agent router class for ticket assignment.

    Provides a cleaner interface for routing tickets to agents.
    """

    def __init__(self, default_strategy: str = None):
        self.default_strategy = default_strategy or DEFAULT_STRATEGY

    async def route_ticket(
        self, ticket: Ticket, db: Session, strategy: str = None
    ) -> Optional[str]:
        """
        Route a ticket to the best available agent.

        Args:
            ticket: The ticket to route
            db: Database session
            strategy: Routing strategy (overrides default)

        Returns:
            Agent ID if assigned, None otherwise
        """
        agent = await assign_ticket_to_agent(
            db, ticket, strategy or self.default_strategy
        )
        return str(agent.id) if agent else None

    async def get_best_agent(
        self, category: str, priority: str, db: Session, strategy: str = None
    ) -> Optional[Agent]:
        """
        Find the best agent for a given category and priority.

        Args:
            category: Ticket category
            priority: Ticket priority
            db: Database session
            strategy: Routing strategy

        Returns:
            Best matching Agent or None
        """
        available_agents = get_available_agents(db, category)
        if not available_agents:
            return None

        strategy_name = strategy or self.default_strategy

        if strategy_name == "specialization":
            specialists = [
                a
                for a in available_agents
                if a.specialization and str(a.specialization.value) == category
            ]
            if specialists:
                specialists.sort(key=lambda a: a.queue_depth or 0)
                return specialists[0]

        # Default: return agent with lowest queue depth
        available_agents.sort(key=lambda a: a.queue_depth or 0)
        return available_agents[0]


# Global agent router instance
_agent_router: Optional[AgentRouter] = None


def get_agent_router() -> AgentRouter:
    """
    Get the global agent router instance.

    Returns:
        AgentRouter instance
    """
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter()
    return _agent_router


def get_available_agents(db: Session, category: str = None) -> List[Agent]:
    """Get all available agents."""
    query = db.query(Agent).filter(Agent.is_available == True)
    return query.all()


async def assign_ticket_to_agent(
    db: Session, ticket: Ticket, strategy: str = None
) -> Optional[Agent]:
    """Assign a ticket to the best available agent."""
    from utils.redis_client import (
        increment_agent_queue,
        get_agent_queue_depth,
        publish_event,
        enqueue_job,
    )

    strategy_name = strategy or DEFAULT_STRATEGY
    available_agents = get_available_agents(db)

    if not available_agents:
        # Queue for later
        await enqueue_job(
            "assign_ticket",
            {
                "ticket_id": str(ticket.id),
                "category": str(ticket.category.value) if ticket.category else "other",
                "priority": str(ticket.priority.value) if ticket.priority else "medium",
            },
            priority=1,
        )
        return None

    # Select agent based on strategy
    agent = None
    ticket_category = str(ticket.category.value) if ticket.category else "other"
    ticket_priority = str(ticket.priority.value) if ticket.priority else "medium"

    if strategy_name == "specialization":
        # Find specialists first
        specialists = [
            a
            for a in available_agents
            if a.specialization and str(a.specialization.value) == ticket_category
        ]
        if specialists:
            specialists.sort(key=lambda a: a.queue_depth or 0)
            agent = specialists[0]
        else:
            available_agents.sort(key=lambda a: a.queue_depth or 0)
            agent = available_agents[0]

    elif strategy_name == "load_balanced":
        # Lowest queue depth
        for a in available_agents:
            redis_depth = await get_agent_queue_depth(str(a.id))
            a._current_depth = redis_depth if redis_depth > 0 else (a.queue_depth or 0)
        available_agents.sort(key=lambda a: getattr(a, "_current_depth", 0))
        agent = available_agents[0]

    elif strategy_name == "smart":
        # Weighted scoring
        scores = []
        for a in available_agents:
            score = 0.0

            # Specialization (40 pts)
            if a.specialization and str(a.specialization.value) == ticket_category:
                score += 40

            # Load (30 pts)
            redis_depth = await get_agent_queue_depth(str(a.id))
            depth = redis_depth if redis_depth > 0 else (a.queue_depth or 0)
            score += max(0, 30 - (depth * 5))

            # Performance (30 pts)
            avg_res = a.avg_resolution_minutes or 60
            if avg_res <= 15:
                score += 30
            elif avg_res <= 30:
                score += 25
            elif avg_res <= 60:
                score += 20
            else:
                score += 10

            scores.append((a, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        agent = scores[0][0]

    else:
        # Round robin / fallback
        available_agents.sort(key=lambda a: a.queue_depth or 0)
        agent = available_agents[0]

    if agent:
        # Update ticket
        ticket.agent_id = agent.id
        ticket.status = TicketStatus.in_progress

        # Update agent queue
        agent.queue_depth = (agent.queue_depth or 0) + 1
        await increment_agent_queue(str(agent.id), 1)

        db.commit()

        # Publish event
        await publish_event(
            "tickets",
            "assigned",
            {
                "ticket_id": str(ticket.id),
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "category": ticket_category,
                "priority": ticket_priority,
            },
        )

        return agent

    return None


async def unassign_ticket(db: Session, ticket: Ticket) -> bool:
    """Unassign a ticket from its agent."""
    from utils.redis_client import increment_agent_queue, publish_event

    if not ticket.agent_id:
        return False

    agent = db.query(Agent).filter(Agent.id == ticket.agent_id).first()
    if agent:
        agent.queue_depth = max(0, (agent.queue_depth or 1) - 1)
        await increment_agent_queue(str(agent.id), -1)

    old_agent_id = str(ticket.agent_id)
    ticket.agent_id = None
    ticket.status = TicketStatus.open
    db.commit()

    await publish_event(
        "tickets",
        "unassigned",
        {"ticket_id": str(ticket.id), "old_agent_id": old_agent_id},
    )

    return True


async def resolve_ticket(
    db: Session, ticket: Ticket, resolution_minutes: int = None
) -> bool:
    """Mark ticket as resolved."""
    from utils.redis_client import (
        increment_agent_queue,
        publish_event,
        cache_invalidate_pattern,
    )

    if ticket.agent_id:
        agent = db.query(Agent).filter(Agent.id == ticket.agent_id).first()
        if agent:
            agent.queue_depth = max(0, (agent.queue_depth or 1) - 1)
            await increment_agent_queue(str(agent.id), -1)

            if resolution_minutes:
                current_avg = agent.avg_resolution_minutes or 60
                agent.avg_resolution_minutes = int(
                    (current_avg + resolution_minutes) / 2
                )

    ticket.status = TicketStatus.resolved
    ticket.resolved_at = datetime.utcnow()
    db.commit()

    await publish_event(
        "tickets",
        "resolved",
        {
            "ticket_id": str(ticket.id),
            "agent_id": str(ticket.agent_id) if ticket.agent_id else None,
            "resolution_minutes": resolution_minutes,
        },
    )

    await cache_invalidate_pattern("nexdesk:analytics:*")

    return True


async def set_agent_availability(db: Session, agent_id: str, available: bool) -> bool:
    """Set agent availability."""
    from utils.redis_client import update_agent_status, enqueue_job

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return False

    agent.is_available = available
    db.commit()

    await update_agent_status(
        agent_id,
        {
            "available": available,
            "queue_depth": agent.queue_depth or 0,
            "specialization": str(agent.specialization.value)
            if agent.specialization
            else "other",
        },
    )

    if not available:
        await enqueue_job("reassign_agent_tickets", {"agent_id": agent_id}, priority=3)

    return True


async def get_agent_workload(db: Session, agent_id: str) -> dict:
    """Get agent workload stats."""
    from utils.redis_client import get_agent_status

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return {"error": "Agent not found"}

    open_tickets = (
        db.query(Ticket)
        .filter(Ticket.agent_id == agent_id, Ticket.status == TicketStatus.open)
        .count()
    )

    in_progress = (
        db.query(Ticket)
        .filter(Ticket.agent_id == agent_id, Ticket.status == TicketStatus.in_progress)
        .count()
    )

    resolved_today = (
        db.query(Ticket)
        .filter(
            Ticket.agent_id == agent_id,
            Ticket.status == TicketStatus.resolved,
            func.date(Ticket.resolved_at) == datetime.utcnow().date(),
        )
        .count()
    )

    redis_status = await get_agent_status(agent_id)

    return {
        "agent_id": agent_id,
        "name": agent.name,
        "specialization": str(agent.specialization.value)
        if agent.specialization
        else "other",
        "is_available": agent.is_available,
        "queue_depth": agent.queue_depth or 0,
        "redis_queue_depth": redis_status.get("queue_depth", 0) if redis_status else 0,
        "open_tickets": open_tickets,
        "in_progress_tickets": in_progress,
        "resolved_today": resolved_today,
        "avg_resolution_minutes": agent.avg_resolution_minutes or 60,
    }


async def check_escalations(db: Session) -> List[dict]:
    """Check for SLA breaches."""
    from utils.redis_client import publish_event

    now = datetime.utcnow()

    breached = (
        db.query(Ticket)
        .filter(
            Ticket.sla_deadline < now,
            Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress]),
            Ticket.sla_breached == False,
        )
        .all()
    )

    escalations = []
    for ticket in breached:
        ticket.sla_breached = True

        old_priority = str(ticket.priority.value) if ticket.priority else "medium"

        if ticket.priority == Priority.low:
            ticket.priority = Priority.medium
        elif ticket.priority == Priority.medium:
            ticket.priority = Priority.high
        elif ticket.priority == Priority.high:
            ticket.priority = Priority.critical

        new_priority = str(ticket.priority.value) if ticket.priority else "medium"

        escalations.append(
            {
                "ticket_id": str(ticket.id),
                "reason": "SLA breach",
                "old_priority": old_priority,
                "new_priority": new_priority,
            }
        )

        await publish_event(
            "tickets",
            "escalated",
            {
                "ticket_id": str(ticket.id),
                "reason": "SLA breach",
                "new_priority": new_priority,
            },
        )

    db.commit()
    return escalations
