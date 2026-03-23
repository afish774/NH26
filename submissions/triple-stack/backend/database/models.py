"""
==============================================================================
NexDesk Database Models
==============================================================================

SQLAlchemy ORM models for:
- Users, Agents, Tickets
- Chat messages and sessions
- AI audit logs and feedback
- Network monitoring
- Knowledge base management
- Precision-Recall calibration

==============================================================================
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    DateTime,
    Enum,
    ForeignKey,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import uuid
import enum

Base = declarative_base()


def gen_uuid():
    """Generate a UUID string for primary keys."""
    return str(uuid.uuid4())


# =============================================================================
# ENUMS
# =============================================================================


class TicketStatus(str, enum.Enum):
    """Ticket lifecycle statuses."""

    open = "open"
    in_progress = "in_progress"
    pending = "pending"
    resolved = "resolved"
    escalated = "escalated"
    auto_resolved = "auto_resolved"
    pending_feedback = "pending_feedback"


class Priority(str, enum.Enum):
    """Ticket priority levels with SLA implications."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Category(str, enum.Enum):
    """Ticket categories for routing and classification."""

    network = "network"
    hardware = "hardware"
    software = "software"
    access = "access"
    security = "security"
    billing = "billing"
    other = "other"


class FeedbackType(str, enum.Enum):
    """Types of human feedback on AI decisions."""

    routing_accuracy = "routing_accuracy"
    response_quality = "response_quality"
    classification_accuracy = "classification_accuracy"
    deflection_appropriateness = "deflection_appropriateness"


class NetworkStatus(str, enum.Enum):
    """Network service status levels."""

    healthy = "healthy"
    degraded = "degraded"
    down = "down"
    unknown = "unknown"


class CalibrationMode(str, enum.Enum):
    """Precision-Recall calibration modes for different tags."""

    high_precision = "high_precision"  # Avoid false alarms (Billing Error)
    high_recall = "high_recall"  # Catch all cases (Churn Risk)
    balanced = "balanced"  # Default F1 optimization


# =============================================================================
# CORE MODELS
# =============================================================================


class User(Base):
    """
    End users who submit tickets and interact with chat.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    department = Column(String(100), default="General")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    tickets = relationship("Ticket", back_populates="user")


class Agent(Base):
    """
    Support agents who handle tickets.
    Includes workload and specialization for smart routing.
    """

    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    specialization = Column(Enum(Category), default=Category.other)
    is_available = Column(Boolean, default=True)
    queue_depth = Column(Integer, default=0)
    avg_resolution_minutes = Column(Integer, default=60)

    # Performance metrics for routing
    satisfaction_score = Column(Float, default=0.0)
    total_resolved = Column(Integer, default=0)

    # Relationships
    tickets = relationship("Ticket", back_populates="agent")
    feedback_received = relationship("AgentFeedback", back_populates="agent")


class Ticket(Base):
    """
    Support tickets with AI classification and routing.
    Supports manual creation, voice, and screenshot inputs.
    """

    __tablename__ = "tickets"

    id = Column(String, primary_key=True, default=gen_uuid)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.open)
    priority = Column(Enum(Priority), default=Priority.medium)
    category = Column(Enum(Category), default=Category.other)

    # Manual vs AI creation tracking
    is_manual = Column(Boolean, default=False)  # True if created without AI
    created_by = Column(String(50), default="ai")  # 'ai', 'agent', 'user', 'api'

    # AI classification fields
    ai_confidence = Column(Float, default=0.0)
    ai_deflected = Column(Boolean, default=False)
    ai_summary = Column(Text, nullable=True)
    ai_suggested_reply = Column(Text, nullable=True)
    ai_action_taken = Column(String(255), nullable=True)

    # Tags with precision-recall calibration
    tags = Column(JSON, nullable=True)  # ["billing_error", "churn_risk", ...]
    tag_confidence = Column(JSON, nullable=True)  # {"billing_error": 0.85, ...}

    # Sentiment analysis
    sentiment = Column(String(20), nullable=True)
    sentiment_score = Column(Float, nullable=True)

    # SLA management
    sla_deadline = Column(DateTime(timezone=True), nullable=True)
    sla_breached = Column(Boolean, default=False)
    sla_hours = Column(Integer, default=8)

    # Multimodal inputs
    screenshot_key = Column(String(500), nullable=True)
    voice_transcript = Column(Text, nullable=True)

    # Knowledge base scope (restrict AI to specific sources)
    kb_scope = Column(JSON, nullable=True)  # ["confluence", "google_docs", ...]

    # Relations
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    first_response_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="tickets")
    agent = relationship("Agent", back_populates="tickets")
    feedback = relationship("AgentFeedback", back_populates="ticket")

    # Indexes for common queries
    __table_args__ = (
        Index("idx_ticket_status", "status"),
        Index("idx_ticket_category", "category"),
        Index("idx_ticket_created", "created_at"),
        Index("idx_ticket_sla", "sla_deadline", "status"),
    )


class ChatMessage(Base):
    """
    Chat messages for AI deflection conversations.
    """

    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String(255), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    was_deflected = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    knowledge_sources = Column(JSON, nullable=True)
    kb_scope = Column(JSON, nullable=True)  # Which KB sources were used
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiAuditLog(Base):
    """
    Audit log for all AI decisions.
    Required for compliance and debugging.
    """

    __tablename__ = "ai_audit_log"

    id = Column(String, primary_key=True, default=gen_uuid)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)
    action_type = Column(String(50), nullable=False)  # classify, deflect, route, etc.
    input_text = Column(Text, nullable=True)
    ai_output = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    model_used = Column(String(100), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    aws_used = Column(Boolean, default=False)

    # For simulation mode tracking
    is_simulation = Column(Boolean, default=False)
    simulation_batch_id = Column(String, nullable=True)

    # Feedback tracking
    feedback_received = Column(Boolean, default=False)
    feedback_positive = Column(Boolean, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_audit_action", "action_type"),
        Index("idx_audit_simulation", "is_simulation", "simulation_batch_id"),
    )


# =============================================================================
# FEEDBACK & RETRAINING MODELS
# =============================================================================


class AgentFeedback(Base):
    """
    Human-in-the-loop feedback on AI decisions.
    Used for continuous model improvement.
    """

    __tablename__ = "agent_feedback"

    id = Column(String, primary_key=True, default=gen_uuid)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    audit_log_id = Column(String, ForeignKey("ai_audit_log.id"), nullable=True)

    feedback_type = Column(Enum(FeedbackType), nullable=False)
    is_positive = Column(Boolean, nullable=False)  # thumbs up/down
    rating = Column(Integer, nullable=True)  # 1-5 scale (optional)
    comment = Column(Text, nullable=True)

    # What the correct value should have been
    suggested_category = Column(Enum(Category), nullable=True)
    suggested_priority = Column(Enum(Priority), nullable=True)
    suggested_response = Column(Text, nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    ticket = relationship("Ticket", back_populates="feedback")
    agent = relationship("Agent", back_populates="feedback_received")


class RetrainingJob(Base):
    """
    Tracks model retraining jobs for continuous improvement.
    """

    __tablename__ = "retraining_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    job_type = Column(String(50), nullable=False)  # classifier, rag, router
    status = Column(
        String(20), default="pending"
    )  # pending, running, completed, failed

    # Training data
    training_samples = Column(Integer, default=0)
    feedback_included = Column(Integer, default=0)
    date_range_start = Column(DateTime(timezone=True), nullable=True)
    date_range_end = Column(DateTime(timezone=True), nullable=True)

    # Results
    metrics_before = Column(JSON, nullable=True)  # {"accuracy": 0.85, "f1": 0.82}
    metrics_after = Column(JSON, nullable=True)
    improvement_pct = Column(Float, nullable=True)

    # Deployment
    deployed = Column(Boolean, default=False)
    deployed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


# =============================================================================
# PRECISION-RECALL CALIBRATION
# =============================================================================


class TagCalibration(Base):
    """
    Per-tag precision-recall calibration settings.
    Allows different optimization goals per tag type.
    """

    __tablename__ = "tag_calibrations"

    id = Column(String, primary_key=True, default=gen_uuid)
    tag_name = Column(String(100), unique=True, nullable=False)

    # Calibration mode
    mode = Column(Enum(CalibrationMode), default=CalibrationMode.balanced)

    # Custom thresholds
    confidence_threshold = Column(Float, default=0.5)  # Higher = more precision
    priority_boost = Column(Float, default=0.0)  # Add to priority score

    # Current metrics (updated by evaluation)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1_score = Column(Float, nullable=True)
    sample_count = Column(Integer, default=0)

    # Target metrics
    target_precision = Column(Float, nullable=True)  # For high_precision mode
    target_recall = Column(Float, nullable=True)  # For high_recall mode

    description = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SimulationRun(Base):
    """
    Tracks simulation runs for testing AI on historical data.
    """

    __tablename__ = "simulation_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Configuration
    config = Column(JSON, nullable=True)  # Model settings, thresholds, etc.
    date_range_start = Column(DateTime(timezone=True), nullable=True)
    date_range_end = Column(DateTime(timezone=True), nullable=True)
    sample_size = Column(Integer, default=0)

    # Results
    status = Column(
        String(20), default="pending"
    )  # pending, running, completed, failed
    total_processed = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)

    # Detailed metrics
    metrics = Column(JSON, nullable=True)  # Per-category precision/recall
    confusion_matrix = Column(JSON, nullable=True)

    # Comparison
    baseline_accuracy = Column(Float, nullable=True)  # Current production accuracy
    simulation_accuracy = Column(Float, nullable=True)
    improvement_pct = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


# =============================================================================
# KNOWLEDGE BASE MANAGEMENT
# =============================================================================


class KnowledgeSource(Base):
    """
    External knowledge sources (Confluence, Google Docs, etc.)
    """

    __tablename__ = "knowledge_sources"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    source_type = Column(
        String(50), nullable=False
    )  # confluence, gdocs, internal, ticket_history

    # Connection details
    config = Column(JSON, nullable=True)  # API keys, URLs (encrypted in prod)

    # Sync status
    is_active = Column(Boolean, default=True)
    last_synced = Column(DateTime(timezone=True), nullable=True)
    document_count = Column(Integer, default=0)

    # Scope control - which categories this source applies to
    category_scope = Column(JSON, nullable=True)  # ["network", "security"]

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class KnowledgeGap(Base):
    """
    Detected gaps in knowledge base coverage.
    AI spots questions that couldn't be answered.
    """

    __tablename__ = "knowledge_gaps"

    id = Column(String, primary_key=True, default=gen_uuid)
    query = Column(Text, nullable=False)  # The unanswered question
    category = Column(Enum(Category), nullable=True)

    # Detection
    occurrence_count = Column(Integer, default=1)
    first_detected = Column(DateTime(timezone=True), server_default=func.now())
    last_detected = Column(DateTime(timezone=True), server_default=func.now())

    # Resolution
    is_resolved = Column(Boolean, default=False)
    resolution_notes = Column(Text, nullable=True)
    kb_article_id = Column(String, nullable=True)  # Link to created KB article

    # Related tickets
    sample_ticket_ids = Column(JSON, nullable=True)


class KnowledgeConflict(Base):
    """
    Detected conflicts between knowledge sources.
    Different sources give contradictory information.
    """

    __tablename__ = "knowledge_conflicts"

    id = Column(String, primary_key=True, default=gen_uuid)
    topic = Column(String(500), nullable=False)

    # Conflicting sources
    source_a_id = Column(String, ForeignKey("knowledge_sources.id"), nullable=True)
    source_a_content = Column(Text, nullable=True)
    source_b_id = Column(String, ForeignKey("knowledge_sources.id"), nullable=True)
    source_b_content = Column(Text, nullable=True)

    # Conflict details
    conflict_type = Column(String(50), nullable=True)  # factual, procedural, outdated
    severity = Column(String(20), default="medium")  # low, medium, high

    # Resolution
    is_resolved = Column(Boolean, default=False)
    resolution_notes = Column(Text, nullable=True)
    correct_source_id = Column(String, nullable=True)

    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)


# =============================================================================
# NETWORK MONITORING
# =============================================================================


class NetworkService(Base):
    """
    Monitored network services and their status.
    """

    __tablename__ = "network_services"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    service_type = Column(String(50), nullable=False)  # http, tcp, ping, dns

    # Monitoring config
    endpoint = Column(String(500), nullable=False)  # URL or IP:port
    check_interval_seconds = Column(Integer, default=60)
    timeout_seconds = Column(Integer, default=10)
    expected_status = Column(Integer, default=200)  # For HTTP

    # Current status
    status = Column(Enum(NetworkStatus), default=NetworkStatus.unknown)
    last_check = Column(DateTime(timezone=True), nullable=True)
    last_success = Column(DateTime(timezone=True), nullable=True)
    last_failure = Column(DateTime(timezone=True), nullable=True)

    # Metrics
    response_time_ms = Column(Integer, nullable=True)
    avg_response_time_ms = Column(Float, nullable=True)
    uptime_pct = Column(Float, default=100.0)
    consecutive_failures = Column(Integer, default=0)

    # Alerting
    alert_threshold = Column(Integer, default=3)  # Failures before alert
    is_critical = Column(Boolean, default=False)

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class NetworkCheck(Base):
    """
    Individual network health check results.
    """

    __tablename__ = "network_checks"

    id = Column(String, primary_key=True, default=gen_uuid)
    service_id = Column(String, ForeignKey("network_services.id"), nullable=False)

    # Check result
    status = Column(Enum(NetworkStatus), nullable=False)
    response_time_ms = Column(Integer, nullable=True)
    status_code = Column(Integer, nullable=True)  # HTTP status
    error_message = Column(Text, nullable=True)

    # Additional details
    details = Column(JSON, nullable=True)  # Headers, response body snippet, etc.

    checked_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_network_check_service", "service_id", "checked_at"),)


class NetworkIncident(Base):
    """
    Network incidents (outages, degraded performance).
    Auto-created when services fail checks.
    """

    __tablename__ = "network_incidents"

    id = Column(String, primary_key=True, default=gen_uuid)
    service_id = Column(String, ForeignKey("network_services.id"), nullable=False)

    # Incident details
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String(20), default="medium")  # low, medium, high, critical

    # Timeline
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Impact
    affected_users = Column(Integer, nullable=True)
    related_ticket_count = Column(Integer, default=0)

    # Status
    status = Column(String(20), default="active")  # active, acknowledged, resolved
    resolution_notes = Column(Text, nullable=True)

    # Auto-link to tickets
    auto_created_ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)


class TicketCluster(Base):
    """
    Clusters of similar tickets (for trend detection).
    """

    __tablename__ = "ticket_clusters"

    id = Column(String, primary_key=True, default=gen_uuid)
    category = Column(Enum(Category), nullable=False)
    ticket_count = Column(Integer, nullable=False)
    p0_raised = Column(Boolean, default=False)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
