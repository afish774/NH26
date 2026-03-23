"""
Network Monitoring Background Service.

This module provides:
- Background health checks for monitored services
- Automatic incident creation and resolution
- Alert notifications via WebSocket
- Uptime tracking
"""

import os
import asyncio
import aiohttp
import socket
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

from sqlalchemy.orm import Session
from database.connection import SessionLocal
from database.models import NetworkService, NetworkCheck, NetworkIncident

logger = logging.getLogger(__name__)

# Configuration
CHECK_INTERVAL = int(os.getenv("NETWORK_CHECK_INTERVAL", "30"))  # seconds
MAX_CONCURRENT_CHECKS = int(os.getenv("NETWORK_MAX_CONCURRENT_CHECKS", "10"))

# Global flag to control the monitoring loop
_monitoring_active = False


async def check_service(service_id: str) -> Dict[str, Any]:
    """
    Perform a health check on a single service.

    Args:
        service_id: The service ID to check

    Returns:
        Dict with check results
    """
    db = SessionLocal()
    try:
        service = (
            db.query(NetworkService).filter(NetworkService.id == service_id).first()
        )
        if not service or not service.is_active:
            return {"error": "Service not found or inactive"}

        result = await _perform_check(service)
        await _record_check_result(db, service, result)

        return result
    finally:
        db.close()


async def _perform_check(service: NetworkService) -> Dict[str, Any]:
    """
    Perform the actual health check based on check type.

    Args:
        service: NetworkService to check

    Returns:
        Dict with status, response_time_ms, status_code, error_message
    """
    start_time = datetime.utcnow()

    try:
        if service.check_type == "http":
            return await _check_http(service, start_time)
        elif service.check_type == "tcp":
            return await _check_tcp(service, start_time)
        elif service.check_type == "ping":
            return await _check_ping(service, start_time)
        else:
            return {
                "status": "error",
                "response_time_ms": 0,
                "status_code": None,
                "error_message": f"Unknown check type: {service.check_type}",
            }
    except Exception as e:
        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.error(f"Check failed for {service.name}: {e}")
        return {
            "status": "down",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": str(e),
        }


async def _check_http(service: NetworkService, start_time: datetime) -> Dict[str, Any]:
    """Perform HTTP health check."""
    timeout = aiohttp.ClientTimeout(total=service.timeout_seconds)
    headers = service.headers or {}

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(service.url, headers=headers, ssl=False) as response:
                elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000

                # Check if status matches expected
                expected = service.expected_status or 200
                if response.status == expected:
                    status = "healthy"
                elif response.status >= 500:
                    status = "down"
                else:
                    status = "degraded"

                return {
                    "status": status,
                    "response_time_ms": int(elapsed),
                    "status_code": response.status,
                    "error_message": None
                    if status == "healthy"
                    else f"Unexpected status: {response.status}",
                }
    except asyncio.TimeoutError:
        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "status": "down",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": f"Timeout after {service.timeout_seconds}s",
        }
    except aiohttp.ClientError as e:
        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "status": "down",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": str(e),
        }


async def _check_tcp(service: NetworkService, start_time: datetime) -> Dict[str, Any]:
    """Perform TCP port check."""
    # Parse host and port from URL (tcp://host:port)
    url = service.url.replace("tcp://", "")
    if ":" in url:
        host, port_str = url.split(":", 1)
        port = int(port_str)
    else:
        host = url
        port = 80

    try:
        # Use asyncio to make socket connection
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=service.timeout_seconds
        )
        writer.close()
        await writer.wait_closed()

        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "status": "healthy",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": None,
        }
    except asyncio.TimeoutError:
        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "status": "down",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": f"TCP connection timeout after {service.timeout_seconds}s",
        }
    except Exception as e:
        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "status": "down",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": str(e),
        }


async def _check_ping(service: NetworkService, start_time: datetime) -> Dict[str, Any]:
    """
    Perform ping check (ICMP).

    Note: This uses a simple TCP connect to port 80 as a fallback
    since true ICMP requires root privileges.
    """
    # Parse host from URL (icmp://host or just host)
    host = (
        service.url.replace("icmp://", "")
        .replace("http://", "")
        .replace("https://", "")
    )
    host = host.split("/")[0].split(":")[0]

    try:
        # Try to resolve and connect (simulated ping)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 80), timeout=service.timeout_seconds
        )
        writer.close()
        await writer.wait_closed()

        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "status": "healthy",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": None,
        }
    except Exception as e:
        elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "status": "down",
            "response_time_ms": int(elapsed),
            "status_code": None,
            "error_message": f"Host unreachable: {e}",
        }


async def _record_check_result(
    db: Session, service: NetworkService, result: Dict[str, Any]
) -> None:
    """
    Record check result and update service status.

    Also handles incident creation/resolution.
    """
    from utils.websocket_manager import manager as ws_manager

    # Create check record
    check = NetworkCheck(
        id=str(uuid.uuid4()),
        service_id=service.id,
        status=result["status"],
        response_time_ms=result["response_time_ms"],
        status_code=result.get("status_code"),
        error_message=result.get("error_message"),
        checked_at=datetime.utcnow(),
    )
    db.add(check)

    # Update service status
    old_status = service.current_status
    service.current_status = result["status"]
    service.last_check = datetime.utcnow()
    service.last_response_time_ms = result["response_time_ms"]

    # Track consecutive failures
    if result["status"] == "down":
        service.consecutive_failures = (service.consecutive_failures or 0) + 1
    else:
        service.consecutive_failures = 0

    # Handle incident creation/resolution
    if (
        result["status"] == "down"
        and service.consecutive_failures >= service.alert_threshold
    ):
        # Check if there's already an active incident
        active_incident = (
            db.query(NetworkIncident)
            .filter(
                NetworkIncident.service_id == service.id,
                NetworkIncident.is_resolved == False,
            )
            .first()
        )

        if not active_incident:
            # Create new incident
            incident = NetworkIncident(
                id=str(uuid.uuid4()),
                service_id=service.id,
                started_at=datetime.utcnow(),
                error_message=result.get("error_message", "Service down"),
                is_resolved=False,
            )
            db.add(incident)

            # Notify via WebSocket
            try:
                await ws_manager.broadcast(
                    {
                        "type": "incident_created",
                        "service_id": str(service.id),
                        "service_name": service.name,
                        "error_message": result.get("error_message"),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send WebSocket notification: {e}")

            logger.warning(
                f"Incident created for {service.name}: {result.get('error_message')}"
            )

    elif result["status"] == "healthy" and old_status in ["down", "degraded"]:
        # Auto-resolve active incidents
        active_incident = (
            db.query(NetworkIncident)
            .filter(
                NetworkIncident.service_id == service.id,
                NetworkIncident.is_resolved == False,
            )
            .first()
        )

        if active_incident:
            active_incident.is_resolved = True
            active_incident.resolved_at = datetime.utcnow()
            duration = (
                active_incident.resolved_at - active_incident.started_at
            ).total_seconds() / 60
            active_incident.duration_minutes = int(duration)

            # Notify via WebSocket
            try:
                await ws_manager.broadcast(
                    {
                        "type": "incident_resolved",
                        "incident_id": str(active_incident.id),
                        "service_id": str(service.id),
                        "service_name": service.name,
                        "duration_minutes": active_incident.duration_minutes,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send WebSocket notification: {e}")

            logger.info(
                f"Incident auto-resolved for {service.name} after {active_incident.duration_minutes}m"
            )

    db.commit()


async def run_monitoring_loop():
    """
    Main monitoring loop that checks all active services.

    This should be started as a background task when the app starts.
    """
    global _monitoring_active
    _monitoring_active = True

    logger.info(f"Network monitoring started (interval: {CHECK_INTERVAL}s)")

    while _monitoring_active:
        try:
            db = SessionLocal()
            try:
                # Get all active services that need checking
                now = datetime.utcnow()
                services = (
                    db.query(NetworkService)
                    .filter(NetworkService.is_active == True)
                    .all()
                )

                services_to_check = []
                for service in services:
                    # Check if it's time to check this service
                    if service.last_check is None:
                        services_to_check.append(service)
                    else:
                        next_check = service.last_check + timedelta(
                            seconds=service.interval_seconds
                        )
                        if now >= next_check:
                            services_to_check.append(service)

                if services_to_check:
                    logger.debug(f"Checking {len(services_to_check)} services...")

                    # Check services concurrently with semaphore limit
                    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

                    async def check_with_semaphore(service):
                        async with semaphore:
                            result = await _perform_check(service)
                            await _record_check_result(db, service, result)

                    await asyncio.gather(
                        *[check_with_semaphore(s) for s in services_to_check],
                        return_exceptions=True,
                    )

            finally:
                db.close()

            # Wait before next iteration
            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

    logger.info("Network monitoring stopped")


def stop_monitoring():
    """Stop the monitoring loop."""
    global _monitoring_active
    _monitoring_active = False
    logger.info("Network monitoring stop requested")


def is_monitoring_active() -> bool:
    """Check if monitoring is currently active."""
    return _monitoring_active


async def get_service_uptime(service_id: str, hours: int = 24) -> float:
    """
    Calculate service uptime percentage for the given time period.

    Args:
        service_id: Service to check
        hours: Number of hours to look back

    Returns:
        Uptime percentage (0-100)
    """
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        total = (
            db.query(NetworkCheck)
            .filter(
                NetworkCheck.service_id == service_id, NetworkCheck.checked_at >= since
            )
            .count()
        )

        healthy = (
            db.query(NetworkCheck)
            .filter(
                NetworkCheck.service_id == service_id,
                NetworkCheck.checked_at >= since,
                NetworkCheck.status == "healthy",
            )
            .count()
        )

        return (healthy / total * 100) if total > 0 else 100.0
    finally:
        db.close()


async def get_average_response_time(service_id: str, hours: int = 24) -> float:
    """
    Calculate average response time for a service.

    Args:
        service_id: Service to check
        hours: Number of hours to look back

    Returns:
        Average response time in milliseconds
    """
    from sqlalchemy import func

    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        result = (
            db.query(func.avg(NetworkCheck.response_time_ms))
            .filter(
                NetworkCheck.service_id == service_id,
                NetworkCheck.checked_at >= since,
                NetworkCheck.status == "healthy",
            )
            .scalar()
        )

        return float(result) if result else 0.0
    finally:
        db.close()
