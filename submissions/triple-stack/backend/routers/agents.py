"""
Agents router - manage IT support agents.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database.connection import get_db
from database.models import Agent, Category
from utils.routing import set_agent_availability, get_agent_workload, check_escalations
from utils.redis_client import get_all_agent_statuses, get_queue_stats

router = APIRouter()


class CreateAgentRequest(BaseModel):
    name: str
    email: str
    specialization: Optional[str] = "other"


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    specialization: Optional[str] = None
    is_available: Optional[bool] = None


@router.post("/")
async def create_agent(req: CreateAgentRequest, db: Session = Depends(get_db)):
    """Create a new agent."""
    # Check if email exists
    existing = db.query(Agent).filter(Agent.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    agent = Agent(
        id=str(uuid.uuid4()),
        name=req.name,
        email=req.email,
        specialization=req.specialization,
        is_available=True,
        queue_depth=0,
        avg_resolution_minutes=60,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    return {
        "id": agent.id,
        "name": agent.name,
        "email": agent.email,
        "specialization": str(agent.specialization.value)
        if agent.specialization
        else "other",
        "is_available": agent.is_available,
    }


@router.get("/")
async def list_agents(db: Session = Depends(get_db)):
    """List all agents."""
    agents = db.query(Agent).all()

    return [
        {
            "id": a.id,
            "name": a.name,
            "email": a.email,
            "specialization": str(a.specialization.value)
            if a.specialization
            else "other",
            "is_available": a.is_available,
            "queue_depth": a.queue_depth or 0,
            "avg_resolution_minutes": a.avg_resolution_minutes or 60,
        }
        for a in agents
    ]


@router.get("/status")
async def get_agents_status():
    """Get real-time agent statuses from Redis."""
    statuses = await get_all_agent_statuses()
    queue_stats = await get_queue_stats()

    return {"agents": statuses, "queue": queue_stats}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, db: Session = Depends(get_db)):
    """Get agent details."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "id": agent.id,
        "name": agent.name,
        "email": agent.email,
        "specialization": str(agent.specialization.value)
        if agent.specialization
        else "other",
        "is_available": agent.is_available,
        "queue_depth": agent.queue_depth or 0,
        "avg_resolution_minutes": agent.avg_resolution_minutes or 60,
    }


@router.get("/{agent_id}/workload")
async def get_workload(agent_id: str, db: Session = Depends(get_db)):
    """Get agent workload statistics."""
    return await get_agent_workload(db, agent_id)


@router.patch("/{agent_id}")
async def update_agent(
    agent_id: str, req: UpdateAgentRequest, db: Session = Depends(get_db)
):
    """Update agent details."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if req.name is not None:
        agent.name = req.name
    if req.email is not None:
        agent.email = req.email
    if req.specialization is not None:
        agent.specialization = req.specialization
    if req.is_available is not None:
        await set_agent_availability(db, agent_id, req.is_available)

    db.commit()

    return {
        "id": agent.id,
        "name": agent.name,
        "email": agent.email,
        "specialization": str(agent.specialization.value)
        if agent.specialization
        else "other",
        "is_available": agent.is_available,
    }


@router.post("/{agent_id}/availability")
async def set_availability(
    agent_id: str, available: bool, db: Session = Depends(get_db)
):
    """Set agent availability."""
    success = await set_agent_availability(db, agent_id, available)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {"success": True, "agent_id": agent_id, "is_available": available}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    """Delete an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if agent has assigned tickets
    if agent.queue_depth and agent.queue_depth > 0:
        raise HTTPException(
            status_code=400, detail="Cannot delete agent with assigned tickets"
        )

    db.delete(agent)
    db.commit()

    return {"success": True, "deleted": agent_id}


@router.post("/check-escalations")
async def run_escalation_check(db: Session = Depends(get_db)):
    """Manually run escalation check for SLA breaches."""
    escalations = await check_escalations(db)
    return {"escalations": escalations, "count": len(escalations)}
