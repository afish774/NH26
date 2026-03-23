"""
Network Monitoring Router.

Provides endpoints for:
- Managing monitored services (CRUD)
- Viewing service health status
- Viewing network incidents
- Dashboard overview
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.connection import get_db
from database.models import NetworkService, NetworkCheck, NetworkIncident
from schemas.models import (
    NetworkServiceCreate,
    NetworkServiceResponse,
    NetworkCheckResponse,
    NetworkIncidentResponse,
    NetworkDashboardResponse,
)
from utils.exceptions import ServiceNotFoundError, ValidationError, DatabaseError
from utils.websocket_manager import manager as ws_manager
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# Service Management
# =============================================================================


@router.post("/services", response_model=NetworkServiceResponse)
async def create_service(req: NetworkServiceCreate, db: Session = Depends(get_db)):
    """
    Add a new service to monitor.

    The service will be checked at the specified interval.
    """
    # Validate URL format
    if not req.url.startswith(("http://", "https://", "tcp://", "icmp://")):
        raise ValidationError(
            "url", "Must start with http://, https://, tcp://, or icmp://"
        )

    # Check for duplicate
    existing = (
        db.query(NetworkService)
        .filter(NetworkService.url == req.url, NetworkService.is_active == True)
        .first()
    )
    if existing:
        raise ValidationError("url", f"Service with URL {req.url} already exists")

    service = NetworkService(
        id=str(uuid.uuid4()),
        name=req.name,
        url=req.url,
        check_type=req.check_type,
        interval_seconds=req.interval_seconds,
        timeout_seconds=req.timeout_seconds,
        expected_status=req.expected_status,
        headers=req.headers,
        alert_threshold=req.alert_threshold,
        is_active=True,
        current_status="unknown",
        consecutive_failures=0,
    )

    try:
        db.add(service)
        db.commit()
        db.refresh(service)
        logger.info(f"Network service created: {service.name} ({service.url})")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create network service: {e}")
        raise DatabaseError(f"Failed to create service: {e}")

    return _service_to_response(service, db)


@router.get("/services", response_model=List[NetworkServiceResponse])
async def list_services(
    db: Session = Depends(get_db),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    status: Optional[str] = Query(None, description="Filter by current status"),
):
    """Get all monitored services."""
    query = db.query(NetworkService)

    if is_active is not None:
        query = query.filter(NetworkService.is_active == is_active)
    if status:
        query = query.filter(NetworkService.current_status == status)

    services = query.order_by(NetworkService.name).all()
    return [_service_to_response(s, db) for s in services]


@router.get("/services/{service_id}", response_model=NetworkServiceResponse)
async def get_service(service_id: str, db: Session = Depends(get_db)):
    """Get details for a specific service."""
    service = db.query(NetworkService).filter(NetworkService.id == service_id).first()
    if not service:
        raise ServiceNotFoundError(service_id)
    return _service_to_response(service, db)


@router.patch("/services/{service_id}")
async def update_service(
    service_id: str,
    name: Optional[str] = None,
    interval_seconds: Optional[int] = None,
    timeout_seconds: Optional[int] = None,
    alert_threshold: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """Update a service configuration."""
    service = db.query(NetworkService).filter(NetworkService.id == service_id).first()
    if not service:
        raise ServiceNotFoundError(service_id)

    if name is not None:
        service.name = name
    if interval_seconds is not None:
        service.interval_seconds = interval_seconds
    if timeout_seconds is not None:
        service.timeout_seconds = timeout_seconds
    if alert_threshold is not None:
        service.alert_threshold = alert_threshold
    if is_active is not None:
        service.is_active = is_active

    try:
        db.commit()
        logger.info(f"Network service updated: {service_id}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to update service: {e}")

    return {"success": True, "service_id": service_id}


@router.delete("/services/{service_id}")
async def delete_service(service_id: str, db: Session = Depends(get_db)):
    """
    Delete a service (soft delete - marks as inactive).

    Historical checks and incidents are preserved.
    """
    service = db.query(NetworkService).filter(NetworkService.id == service_id).first()
    if not service:
        raise ServiceNotFoundError(service_id)

    service.is_active = False

    try:
        db.commit()
        logger.info(f"Network service deleted (deactivated): {service_id}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to delete service: {e}")

    return {"success": True, "service_id": service_id, "action": "deactivated"}


# =============================================================================
# Check Results
# =============================================================================


@router.get("/services/{service_id}/checks", response_model=List[NetworkCheckResponse])
async def get_service_checks(
    service_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    hours: int = Query(24, ge=1, le=168, description="Hours of history"),
):
    """Get recent check results for a service."""
    service = db.query(NetworkService).filter(NetworkService.id == service_id).first()
    if not service:
        raise ServiceNotFoundError(service_id)

    since = datetime.utcnow() - timedelta(hours=hours)

    checks = (
        db.query(NetworkCheck)
        .filter(NetworkCheck.service_id == service_id, NetworkCheck.checked_at >= since)
        .order_by(NetworkCheck.checked_at.desc())
        .limit(limit)
        .all()
    )

    return [
        NetworkCheckResponse(
            id=str(c.id),
            service_id=str(c.service_id),
            status=c.status,
            response_time_ms=c.response_time_ms or 0,
            status_code=c.status_code,
            error_message=c.error_message,
            checked_at=str(c.checked_at),
        )
        for c in checks
    ]


@router.post("/services/{service_id}/check")
async def trigger_check(
    service_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger an immediate health check for a service.

    The check runs in the background and results are stored.
    """
    service = db.query(NetworkService).filter(NetworkService.id == service_id).first()
    if not service:
        raise ServiceNotFoundError(service_id)

    # Import here to avoid circular imports
    from utils.network_monitor import check_service

    background_tasks.add_task(check_service, service_id)

    return {
        "success": True,
        "service_id": service_id,
        "message": "Check triggered in background",
    }


# =============================================================================
# Incidents
# =============================================================================


@router.get("/incidents", response_model=List[NetworkIncidentResponse])
async def list_incidents(
    db: Session = Depends(get_db),
    is_resolved: Optional[bool] = Query(
        None, description="Filter by resolution status"
    ),
    service_id: Optional[str] = Query(None, description="Filter by service"),
    limit: int = Query(50, ge=1, le=500),
):
    """Get network incidents."""
    query = db.query(NetworkIncident).join(NetworkService)

    if is_resolved is not None:
        query = query.filter(NetworkIncident.is_resolved == is_resolved)
    if service_id:
        query = query.filter(NetworkIncident.service_id == service_id)

    incidents = query.order_by(NetworkIncident.started_at.desc()).limit(limit).all()

    return [_incident_to_response(i) for i in incidents]


@router.get("/incidents/active", response_model=List[NetworkIncidentResponse])
async def get_active_incidents(db: Session = Depends(get_db)):
    """Get all currently active (unresolved) incidents."""
    incidents = (
        db.query(NetworkIncident)
        .join(NetworkService)
        .filter(NetworkIncident.is_resolved == False)
        .order_by(NetworkIncident.started_at.desc())
        .all()
    )

    return [_incident_to_response(i) for i in incidents]


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Manually resolve an incident."""
    incident = (
        db.query(NetworkIncident).filter(NetworkIncident.id == incident_id).first()
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.is_resolved:
        raise ValidationError("incident", "Incident is already resolved")

    incident.is_resolved = True
    incident.resolved_at = datetime.utcnow()
    if notes:
        incident.resolution_notes = notes

    # Calculate duration
    duration = (incident.resolved_at - incident.started_at).total_seconds() / 60
    incident.duration_minutes = int(duration)

    try:
        db.commit()

        # Notify via WebSocket
        await ws_manager.broadcast(
            {
                "type": "incident_resolved",
                "incident_id": incident_id,
                "service_id": str(incident.service_id),
                "duration_minutes": incident.duration_minutes,
            }
        )

        logger.info(f"Incident resolved: {incident_id}")
    except Exception as e:
        db.rollback()
        raise DatabaseError(f"Failed to resolve incident: {e}")

    return {
        "success": True,
        "incident_id": incident_id,
        "duration_minutes": incident.duration_minutes,
    }


# =============================================================================
# Dashboard
# =============================================================================


@router.get("/dashboard", response_model=NetworkDashboardResponse)
async def get_dashboard(db: Session = Depends(get_db)):
    """
    Get network monitoring dashboard overview.

    Includes:
    - Service counts by status
    - Active incidents
    - Overall uptime
    - Recent incidents
    """
    # Get all active services
    services = db.query(NetworkService).filter(NetworkService.is_active == True).all()

    healthy = sum(1 for s in services if s.current_status == "healthy")
    degraded = sum(1 for s in services if s.current_status == "degraded")
    down = sum(1 for s in services if s.current_status == "down")

    # Active incidents
    active_incidents = (
        db.query(NetworkIncident).filter(NetworkIncident.is_resolved == False).count()
    )

    # Calculate overall uptime (last 24 hours)
    since = datetime.utcnow() - timedelta(hours=24)
    total_checks = (
        db.query(NetworkCheck).filter(NetworkCheck.checked_at >= since).count()
    )
    healthy_checks = (
        db.query(NetworkCheck)
        .filter(NetworkCheck.checked_at >= since, NetworkCheck.status == "healthy")
        .count()
    )

    overall_uptime = (
        (healthy_checks / total_checks * 100) if total_checks > 0 else 100.0
    )

    # Recent incidents
    recent_incidents = (
        db.query(NetworkIncident)
        .join(NetworkService)
        .order_by(NetworkIncident.started_at.desc())
        .limit(10)
        .all()
    )

    return NetworkDashboardResponse(
        total_services=len(services),
        healthy_services=healthy,
        degraded_services=degraded,
        down_services=down,
        active_incidents=active_incidents,
        overall_uptime=round(overall_uptime, 2),
        services=[_service_to_response(s, db) for s in services],
        recent_incidents=[_incident_to_response(i) for i in recent_incidents],
    )


# =============================================================================
# Helpers
# =============================================================================


def _service_to_response(
    service: NetworkService, db: Session
) -> NetworkServiceResponse:
    """Convert a NetworkService model to response."""
    # Calculate uptime percentage (last 24 hours)
    since = datetime.utcnow() - timedelta(hours=24)
    total_checks = (
        db.query(NetworkCheck)
        .filter(NetworkCheck.service_id == service.id, NetworkCheck.checked_at >= since)
        .count()
    )
    healthy_checks = (
        db.query(NetworkCheck)
        .filter(
            NetworkCheck.service_id == service.id,
            NetworkCheck.checked_at >= since,
            NetworkCheck.status == "healthy",
        )
        .count()
    )

    uptime = (healthy_checks / total_checks * 100) if total_checks > 0 else 100.0

    return NetworkServiceResponse(
        id=str(service.id),
        name=service.name,
        url=service.url,
        check_type=service.check_type,
        interval_seconds=service.interval_seconds,
        is_active=service.is_active,
        current_status=service.current_status or "unknown",
        last_check=str(service.last_check) if service.last_check else None,
        uptime_percentage=round(uptime, 2),
        consecutive_failures=service.consecutive_failures or 0,
    )


def _incident_to_response(incident: NetworkIncident) -> NetworkIncidentResponse:
    """Convert a NetworkIncident model to response."""
    duration = None
    if incident.is_resolved and incident.resolved_at:
        duration = int(
            (incident.resolved_at - incident.started_at).total_seconds() / 60
        )

    return NetworkIncidentResponse(
        id=str(incident.id),
        service_id=str(incident.service_id),
        service_name=incident.service.name if incident.service else "Unknown",
        started_at=str(incident.started_at),
        resolved_at=str(incident.resolved_at) if incident.resolved_at else None,
        duration_minutes=duration,
        error_message=incident.error_message or "Service unavailable",
        is_resolved=incident.is_resolved,
    )
