from datetime import datetime, timedelta


SLA_HOURS = {
    "critical": 2,
    "high": 4,
    "medium": 8,
    "low": 24,
}


def calculate_sla_deadline(priority: str) -> datetime:
    """Calculate the SLA deadline based on ticket priority."""
    hours = SLA_HOURS.get(priority, 8)
    return datetime.utcnow() + timedelta(hours=hours)


def is_sla_breached(deadline: datetime) -> bool:
    """Check if the SLA deadline has been breached."""
    if deadline is None:
        return False
    return datetime.utcnow() > deadline
