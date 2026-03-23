"""
Pydantic models for request/response validation.

This module contains all schema models for:
- Chat and voice interactions
- Ticket management
- Agent feedback
- Network monitoring
- Simulation and calibration
- Knowledge base management
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# =============================================================================
# Enums
# =============================================================================


class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class FeedbackType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    CORRECTION = "correction"


class NetworkCheckStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class CalibrationGoal(str, Enum):
    HIGH_PRECISION = "high_precision"
    HIGH_RECALL = "high_recall"
    BALANCED = "balanced"


# =============================================================================
# Chat Models
# =============================================================================


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: List[dict] = []


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    deflected: bool
    confidence: float
    category: str
    create_ticket: bool
    knowledge_sources: List[str] = []
    latency_ms: int = 0
    # Advanced RAG fields
    intent: Optional[str] = None
    hyde_used: bool = False
    rerank_used: bool = False
    advanced_rag: bool = False


# =============================================================================
# Voice Models
# =============================================================================


class VoiceChatRequest(BaseModel):
    """Request for voice chat via base64 audio."""

    audio_base64: str
    filename: str = "audio.wav"
    session_id: Optional[str] = None
    language: str = "en"


class VoiceChatResponse(BaseModel):
    """Response for voice chat."""

    session_id: str
    transcript: str
    transcript_confidence: float
    transcript_language: str
    transcript_duration: float
    transcript_source: str
    reply: str
    deflected: bool
    confidence: float
    category: str
    create_ticket: bool
    knowledge_sources: List[str] = []
    intent: Optional[str] = None
    latency_ms: int = 0
    transcription_latency_ms: int = 0
    rag_latency_ms: int = 0


class TranscriptionResponse(BaseModel):
    """Response for audio transcription."""

    transcript: str
    confidence: float
    language: str
    duration_seconds: float
    source: str
    latency_ms: int


class VoiceTicketRequest(BaseModel):
    """Request for creating ticket from base64 audio."""

    audio_base64: str
    filename: str = "audio.wav"
    user_id: str = "voice_user"
    language: str = "en"


# =============================================================================
# Ticket Models
# =============================================================================


class CreateTicketRequest(BaseModel):
    """Request to create a ticket with AI classification."""

    title: str
    description: str
    user_id: Optional[str] = "demo_user"
    voice_transcript: Optional[str] = None
    screenshot_key: Optional[str] = None


class ManualTicketRequest(BaseModel):
    """Request to create a ticket manually without AI classification."""

    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    category: str = Field(
        ..., description="Ticket category (e.g., 'Technical', 'Billing')"
    )
    priority: str = Field(..., description="Priority: low, medium, high, critical")
    user_id: str = Field(default="manual_user", description="Customer user ID")
    created_by: str = Field(..., description="Agent ID who created the ticket")
    assign_to: Optional[str] = Field(None, description="Agent ID to assign to")
    tags: Optional[List[str]] = Field(default=[], description="Optional tags")


class UpdateStatusRequest(BaseModel):
    """Request to update ticket status."""

    status: str


class TicketAssignRequest(BaseModel):
    """Request to assign a ticket to an agent."""

    agent_id: Optional[str] = Field(
        None, description="Agent ID to assign, or None to unassign"
    )
    use_smart_routing: bool = Field(
        False, description="Use smart routing to auto-select agent"
    )


class TicketListResponse(BaseModel):
    """Summary response for ticket list."""

    id: str
    title: str
    status: str
    priority: str
    category: str
    ai_confidence: float = 0.0
    sentiment: Optional[str] = None
    sla_deadline: Optional[str] = None
    sla_breached: bool = False
    agent_id: Optional[str] = None
    is_manual: bool = False
    created_at: str


class TicketDetailResponse(BaseModel):
    """Detailed response for a single ticket."""

    id: str
    title: str
    description: str
    status: str
    priority: str
    category: str
    ai_summary: Optional[str] = None
    ai_suggested_reply: Optional[str] = None
    ai_confidence: float = 0.0
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    sla_deadline: Optional[str] = None
    sla_hours: Optional[int] = None
    sla_breached: bool = False
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    is_manual: bool = False
    created_by: Optional[str] = None
    voice_transcript: Optional[str] = None
    screenshot_key: Optional[str] = None
    tags: List[str] = []
    created_at: str
    resolved_at: Optional[str] = None


class TicketResponse(BaseModel):
    """Legacy response for ticket creation."""

    id: str
    title: str
    description: str
    status: str
    priority: str
    category: str
    ai_summary: Optional[str] = None
    ai_suggested_reply: Optional[str] = None
    ai_confidence: float = 0.0
    sentiment: Optional[str] = None
    sla_deadline: Optional[str] = None
    created_at: str
    voice_transcript: Optional[str] = None
    transcript_confidence: Optional[float] = None


# =============================================================================
# Screenshot Models
# =============================================================================


class ScreenshotRequest(BaseModel):
    """Request to analyze a screenshot."""

    image_base64: str
    media_type: Optional[str] = "image/png"
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None


# =============================================================================
# Feedback Models (Human-in-the-Loop)
# =============================================================================


class FeedbackCreateRequest(BaseModel):
    """Request to submit feedback on AI response."""

    ticket_id: Optional[str] = Field(None, description="Associated ticket ID")
    session_id: Optional[str] = Field(None, description="Chat session ID")
    feedback_type: FeedbackType = Field(..., description="Type of feedback")
    ai_response: str = Field(..., description="The AI response being evaluated")
    agent_correction: Optional[str] = Field(
        None, description="Corrected response if type is 'correction'"
    )
    rating: Optional[int] = Field(None, ge=1, le=5, description="Rating 1-5")
    comments: Optional[str] = Field(None, description="Additional comments")
    tags: List[str] = Field(default=[], description="Feedback tags for categorization")


class FeedbackResponse(BaseModel):
    """Response for feedback submission."""

    id: str
    feedback_type: str
    ticket_id: Optional[str]
    session_id: Optional[str]
    rating: Optional[int]
    created_at: str
    acknowledged: bool


class FeedbackStatsResponse(BaseModel):
    """Aggregated feedback statistics."""

    total_feedback: int
    positive_count: int
    negative_count: int
    correction_count: int
    average_rating: float
    feedback_by_category: Dict[str, int]
    recent_corrections: List[dict]


# =============================================================================
# Network Monitoring Models
# =============================================================================


class NetworkServiceCreate(BaseModel):
    """Request to add a service for monitoring."""

    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., description="URL or endpoint to monitor")
    check_type: str = Field(default="http", description="Type: http, tcp, ping")
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    expected_status: Optional[int] = Field(
        default=200, description="Expected HTTP status"
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None, description="Custom headers for HTTP checks"
    )
    alert_threshold: int = Field(default=3, description="Failures before alerting")


class NetworkServiceResponse(BaseModel):
    """Response for network service."""

    id: str
    name: str
    url: str
    check_type: str
    interval_seconds: int
    is_active: bool
    current_status: str
    last_check: Optional[str]
    uptime_percentage: float
    consecutive_failures: int


class NetworkCheckResponse(BaseModel):
    """Response for a network check result."""

    id: str
    service_id: str
    status: str
    response_time_ms: int
    status_code: Optional[int]
    error_message: Optional[str]
    checked_at: str


class NetworkIncidentResponse(BaseModel):
    """Response for network incident."""

    id: str
    service_id: str
    service_name: str
    started_at: str
    resolved_at: Optional[str]
    duration_minutes: Optional[int]
    error_message: str
    is_resolved: bool


class NetworkDashboardResponse(BaseModel):
    """Dashboard summary for network monitoring."""

    total_services: int
    healthy_services: int
    degraded_services: int
    down_services: int
    active_incidents: int
    overall_uptime: float
    services: List[NetworkServiceResponse]
    recent_incidents: List[NetworkIncidentResponse]


# =============================================================================
# Simulation & Calibration Models
# =============================================================================


class SimulationRunRequest(BaseModel):
    """Request to run AI simulation on historical data."""

    name: str = Field(..., description="Name for this simulation run")
    ticket_filter: Optional[Dict[str, Any]] = Field(
        None, description="Filter criteria: {category, priority, date_range, etc.}"
    )
    sample_size: int = Field(default=100, ge=10, le=10000)
    include_deflected: bool = Field(default=True)
    test_new_threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Test a different deflection threshold"
    )


class SimulationRunResponse(BaseModel):
    """Response for simulation run."""

    id: str
    name: str
    status: str  # pending, running, completed, failed
    started_at: str
    completed_at: Optional[str]
    total_tickets: int
    correct_predictions: int
    incorrect_predictions: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: Dict[str, int]


class TagCalibrationRequest(BaseModel):
    """Request to set calibration goals for a tag."""

    tag: str = Field(
        ..., description="Tag to calibrate (e.g., 'Billing Error', 'Churn Risk')"
    )
    goal: CalibrationGoal = Field(..., description="Calibration goal")
    target_precision: Optional[float] = Field(None, ge=0.0, le=1.0)
    target_recall: Optional[float] = Field(None, ge=0.0, le=1.0)
    custom_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


class TagCalibrationResponse(BaseModel):
    """Response for tag calibration."""

    id: str
    tag: str
    goal: str
    current_precision: float
    current_recall: float
    current_threshold: float
    recommended_threshold: float
    sample_size: int
    last_calibrated: str


class CalibrationDashboardResponse(BaseModel):
    """Dashboard for precision-recall calibration."""

    default_threshold: float
    tag_calibrations: List[TagCalibrationResponse]
    overall_precision: float
    overall_recall: float
    recent_simulations: List[SimulationRunResponse]


# =============================================================================
# Knowledge Base Management Models
# =============================================================================


class KnowledgeSourceCreate(BaseModel):
    """Request to add a knowledge source."""

    name: str = Field(..., min_length=1, max_length=200)
    source_type: str = Field(
        ..., description="Type: faq, document, api, confluence, etc."
    )
    content: Optional[str] = Field(None, description="Raw content if available")
    url: Optional[str] = Field(None, description="URL if external source")
    scope: List[str] = Field(
        default=["all"], description="Scope tags: ['billing', 'technical', 'all']"
    )
    priority: int = Field(default=1, ge=1, le=10, description="Priority for conflicts")
    is_active: bool = Field(default=True)


class KnowledgeSourceResponse(BaseModel):
    """Response for knowledge source."""

    id: str
    name: str
    source_type: str
    scope: List[str]
    priority: int
    is_active: bool
    entry_count: int
    last_synced: Optional[str]
    created_at: str


class KnowledgeGapResponse(BaseModel):
    """Response for detected knowledge gap."""

    id: str
    query: str
    frequency: int
    first_seen: str
    last_seen: str
    suggested_topics: List[str]
    status: str  # open, addressed, ignored


class KnowledgeConflictResponse(BaseModel):
    """Response for detected knowledge conflict."""

    id: str
    topic: str
    source_a_id: str
    source_a_name: str
    source_a_content: str
    source_b_id: str
    source_b_name: str
    source_b_content: str
    detected_at: str
    resolution: Optional[str]
    status: str  # pending, resolved, ignored


class KnowledgeConflictResolveRequest(BaseModel):
    """Request to resolve a knowledge conflict."""

    resolution: str = Field(
        ..., description="How to resolve: 'prefer_a', 'prefer_b', 'merge', 'ignore'"
    )
    merged_content: Optional[str] = Field(
        None, description="Merged content if resolution is 'merge'"
    )
    notes: Optional[str] = Field(None, description="Resolution notes")


class KnowledgeDashboardResponse(BaseModel):
    """Dashboard for knowledge base management."""

    total_sources: int
    active_sources: int
    total_entries: int
    coverage_score: float  # 0-100
    open_gaps: int
    pending_conflicts: int
    sources: List[KnowledgeSourceResponse]
    recent_gaps: List[KnowledgeGapResponse]
    pending_conflicts_list: List[KnowledgeConflictResponse]


class KnowledgeSyncRequest(BaseModel):
    """Request to sync a knowledge source."""

    source_id: str
    force: bool = Field(default=False, description="Force full re-sync")


class KnowledgeScopeUpdateRequest(BaseModel):
    """Request to update scope for a knowledge source."""

    scope: List[str] = Field(..., description="New scope tags")


# =============================================================================
# Agent Models
# =============================================================================


class AgentCreateRequest(BaseModel):
    """Request to create an agent."""

    name: str = Field(..., min_length=2, max_length=100)
    email: str
    specializations: List[str] = Field(default=[])
    max_concurrent_tickets: int = Field(default=10, ge=1, le=50)


class AgentResponse(BaseModel):
    """Response for agent."""

    id: str
    name: str
    email: str
    is_active: bool
    is_online: bool
    specializations: List[str]
    current_tickets: int
    max_concurrent_tickets: int
    created_at: str


class AgentWorkloadResponse(BaseModel):
    """Response for agent workload stats."""

    agent_id: str
    agent_name: str
    open_tickets: int
    in_progress_tickets: int
    resolved_today: int
    average_resolution_time_hours: float
    capacity_percentage: float


# =============================================================================
# Health & Metrics Models
# =============================================================================


class HealthResponse(BaseModel):
    """System health check response."""

    status: str
    version: str
    uptime_seconds: int
    database: Dict[str, Any]
    redis: Dict[str, Any]
    ai_services: Dict[str, Any]


class MetricsResponse(BaseModel):
    """System metrics response."""

    requests_total: int
    requests_per_minute: float
    average_latency_ms: float
    error_rate: float
    active_connections: int
    cache_hit_rate: float


# =============================================================================
# Triage Models
# =============================================================================


class TriageLevel(str, Enum):
    """Triage severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EscalationReason(str, Enum):
    """Reasons for ticket escalation."""

    SLA_BREACH = "sla_breach"
    SLA_WARNING = "sla_warning"
    KEYWORD_TRIGGER = "keyword_trigger"
    VIP_USER = "vip_user"
    SENTIMENT_NEGATIVE = "sentiment_negative"
    REPEATED_CONTACT = "repeated_contact"
    MANUAL_ESCALATION = "manual_escalation"
    IDLE_TIMEOUT = "idle_timeout"
    COMPLEXITY_HIGH = "complexity_high"


class TriageAnalyzeRequest(BaseModel):
    """Request to analyze a ticket for triage."""

    title: str = Field(..., min_length=5, description="Ticket title")
    description: str = Field(..., min_length=10, description="Ticket description")
    user_id: str = Field(default="unknown", description="User ID")
    department: Optional[str] = Field(None, description="User's department")
    category: Optional[str] = Field(None, description="Ticket category")
    sentiment_score: Optional[float] = Field(
        None, ge=-1.0, le=1.0, description="Sentiment score (-1 to 1)"
    )


class TriageResultResponse(BaseModel):
    """Response for triage analysis."""

    priority: str
    triage_level: str
    score: float = Field(..., ge=0, le=100, description="Triage score 0-100")
    sla_hours: int
    requires_manual_intervention: bool
    escalation_reasons: List[str]
    suggested_agent_skills: List[str]
    routing_notes: str
    confidence: float


class EscalationCheckRequest(BaseModel):
    """Request to check if a ticket should be escalated."""

    ticket_id: str = Field(..., description="Ticket ID to check")


class EscalationResultResponse(BaseModel):
    """Response for escalation check."""

    ticket_id: str
    should_escalate: bool
    new_priority: Optional[str]
    reasons: List[str]
    notification_targets: List[str]
    message: str


class ManualEscalationRequest(BaseModel):
    """Request for manual escalation."""

    ticket_id: str = Field(..., description="Ticket ID to escalate")
    reason: str = Field(..., description="Reason for manual escalation")
    new_priority: Optional[str] = Field(None, description="New priority level")
    notify_agents: List[str] = Field(default=[], description="Agent IDs to notify")


class TriageRouteRequest(BaseModel):
    """Request to route a ticket to an agent."""

    ticket_id: str = Field(..., description="Ticket ID to route")
    force_skills: Optional[List[str]] = Field(
        None, description="Force specific skills requirement"
    )


class TriageRouteResponse(BaseModel):
    """Response for ticket routing."""

    ticket_id: str
    assigned_agent_id: Optional[str]
    assigned_agent_name: Optional[str]
    routing_score: float
    routing_reason: str


class TriageBulkAnalyzeRequest(BaseModel):
    """Request to analyze multiple tickets for triage."""

    tickets: List[TriageAnalyzeRequest]


class TriageBulkAnalyzeResponse(BaseModel):
    """Response for bulk triage analysis."""

    results: List[TriageResultResponse]
    total_analyzed: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int


class SLAConfigRequest(BaseModel):
    """Request to update SLA configuration."""

    critical_hours: int = Field(default=1, ge=1, le=24)
    high_hours: int = Field(default=4, ge=1, le=72)
    medium_hours: int = Field(default=24, ge=1, le=168)
    low_hours: int = Field(default=72, ge=1, le=336)


class SLAConfigResponse(BaseModel):
    """Response for SLA configuration."""

    critical_hours: int
    high_hours: int
    medium_hours: int
    low_hours: int
    updated_at: str


class EscalationConfigRequest(BaseModel):
    """Request to update escalation configuration."""

    sla_warning_threshold: float = Field(default=0.75, ge=0.5, le=1.0)
    sla_critical_threshold: float = Field(default=0.90, ge=0.7, le=1.0)
    max_reassignments: int = Field(default=3, ge=1, le=10)
    idle_hours_escalate: int = Field(default=4, ge=1, le=48)


class EscalationConfigResponse(BaseModel):
    """Response for escalation configuration."""

    sla_warning_threshold: float
    sla_critical_threshold: float
    max_reassignments: int
    idle_hours_escalate: int
    updated_at: str


class TriageDashboardResponse(BaseModel):
    """Dashboard summary for triage system."""

    total_tickets: int
    pending_triage: int
    critical_tickets: int
    high_tickets: int
    breached_sla_count: int
    approaching_sla_count: int
    escalations_today: int
    avg_triage_time_ms: float
    sla_config: SLAConfigResponse
    escalation_config: EscalationConfigResponse


# =============================================================================
# Email Integration Models
# =============================================================================


class EmailTicketCreateRequest(BaseModel):
    """Request representing an incoming email to create a ticket."""

    from_address: str = Field(..., description="Sender email address")
    to_address: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject")
    body_text: str = Field(..., description="Plain text body")
    body_html: Optional[str] = Field(None, description="HTML body")
    attachments: List[Dict[str, Any]] = Field(
        default=[], description="List of attachments"
    )
    headers: Dict[str, str] = Field(default={}, description="Email headers")
    received_at: Optional[str] = Field(None, description="When the email was received")


class EmailTicketResponse(BaseModel):
    """Response for email-to-ticket creation."""

    ticket_id: str
    title: str
    category: str
    priority: str
    from_address: str
    auto_reply_sent: bool
    confidence: float


class EmailReplyRequest(BaseModel):
    """Request to send an email reply for a ticket."""

    ticket_id: str = Field(..., description="Ticket ID")
    to_address: str = Field(..., description="Recipient email")
    subject: Optional[str] = Field(
        None, description="Subject (auto-generated if not provided)"
    )
    body: str = Field(..., description="Email body")
    include_ticket_history: bool = Field(
        default=False, description="Include ticket history"
    )


class EmailReplyResponse(BaseModel):
    """Response for email reply."""

    success: bool
    message_id: Optional[str]
    ticket_id: str
    sent_at: str


class EmailConfigRequest(BaseModel):
    """Request to configure email settings."""

    smtp_host: str
    smtp_port: int = Field(default=587)
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool = Field(default=True)
    imap_host: Optional[str] = None
    imap_port: int = Field(default=993)
    imap_username: Optional[str] = None
    imap_password: Optional[str] = None
    from_address: str
    from_name: str = Field(default="NexDesk Support")
    auto_reply_enabled: bool = Field(default=True)
    auto_reply_template: Optional[str] = None


class EmailConfigResponse(BaseModel):
    """Response for email configuration."""

    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_use_tls: bool
    from_address: str
    from_name: str
    auto_reply_enabled: bool
    imap_configured: bool
    last_sync: Optional[str]


# =============================================================================
# Slack/Teams Integration Models
# =============================================================================


class SlackWebhookEvent(BaseModel):
    """Incoming Slack webhook event."""

    type: str = Field(..., description="Event type")
    token: str = Field(..., description="Verification token")
    team_id: Optional[str] = None
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    text: Optional[str] = None
    ts: Optional[str] = None
    event: Optional[Dict[str, Any]] = None
    challenge: Optional[str] = Field(None, description="URL verification challenge")


class SlackCommandRequest(BaseModel):
    """Incoming Slack slash command."""

    command: str = Field(..., description="Command name (e.g., /ticket)")
    text: str = Field(default="", description="Command arguments")
    user_id: str
    user_name: str
    channel_id: str
    channel_name: str
    team_id: str
    response_url: str


class SlackTicketCreateRequest(BaseModel):
    """Request to create ticket from Slack."""

    title: str
    description: str
    channel_id: str
    user_id: str
    user_name: str
    priority: Optional[str] = Field(default="medium")
    thread_ts: Optional[str] = None


class SlackMessageResponse(BaseModel):
    """Response format for Slack messages."""

    response_type: str = Field(
        default="in_channel", description="in_channel or ephemeral"
    )
    text: str
    blocks: Optional[List[Dict[str, Any]]] = None
    attachments: Optional[List[Dict[str, Any]]] = None


class TeamsWebhookEvent(BaseModel):
    """Incoming Microsoft Teams webhook event."""

    type: str
    id: str
    timestamp: str
    serviceUrl: str
    channelId: str
    from_user: Dict[str, Any] = Field(alias="from")
    conversation: Dict[str, Any]
    recipient: Dict[str, Any]
    text: Optional[str] = None
    value: Optional[Dict[str, Any]] = None


class TeamsCardResponse(BaseModel):
    """Adaptive Card response for Teams."""

    type: str = Field(default="message")
    attachments: List[Dict[str, Any]]


class IntegrationConfigRequest(BaseModel):
    """Request to configure Slack/Teams integration."""

    platform: str = Field(..., description="slack or teams")
    webhook_url: Optional[str] = None
    bot_token: Optional[str] = None
    signing_secret: Optional[str] = None
    app_id: Optional[str] = None
    default_channel: Optional[str] = None
    notifications_enabled: bool = Field(default=True)
    ticket_updates_enabled: bool = Field(default=True)
    escalation_alerts_enabled: bool = Field(default=True)


class IntegrationConfigResponse(BaseModel):
    """Response for integration configuration."""

    platform: str
    is_configured: bool
    notifications_enabled: bool
    ticket_updates_enabled: bool
    escalation_alerts_enabled: bool
    default_channel: Optional[str]
    last_event: Optional[str]


# =============================================================================
# Self-Service Portal Models
# =============================================================================


class PortalTicketStatusRequest(BaseModel):
    """Request to check ticket status via portal."""

    ticket_id: str = Field(..., description="Ticket ID")
    email: Optional[str] = Field(None, description="Email for verification")
    verification_code: Optional[str] = Field(None, description="Verification code")


class PortalTicketStatusResponse(BaseModel):
    """Response for portal ticket status."""

    ticket_id: str
    title: str
    status: str
    priority: str
    created_at: str
    updated_at: str
    estimated_resolution: Optional[str]
    last_update_message: Optional[str]
    can_add_comment: bool


class PortalFAQResponse(BaseModel):
    """Response for FAQ item."""

    id: str
    question: str
    answer: str
    category: str
    helpful_count: int
    views: int


class PortalFAQListResponse(BaseModel):
    """Response for FAQ list."""

    categories: List[str]
    faqs: List[PortalFAQResponse]
    total: int


class PortalSearchRequest(BaseModel):
    """Request to search knowledge base via portal."""

    query: str = Field(..., min_length=3, description="Search query")
    category: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=50)


class PortalSearchResponse(BaseModel):
    """Response for portal search."""

    query: str
    results: List[Dict[str, Any]]
    total_results: int
    suggested_queries: List[str]


class PortalSubmitRequest(BaseModel):
    """Request to submit a new ticket via portal."""

    name: str = Field(..., min_length=2, description="Customer name")
    email: str = Field(..., description="Customer email")
    subject: str = Field(..., min_length=5, description="Issue subject")
    description: str = Field(..., min_length=20, description="Issue description")
    category: Optional[str] = None
    attachments: List[str] = Field(default=[], description="Attachment URLs or keys")
    preferred_contact: str = Field(default="email", description="email or phone")
    phone: Optional[str] = None


class PortalSubmitResponse(BaseModel):
    """Response for portal ticket submission."""

    ticket_id: str
    tracking_code: str
    estimated_response_hours: int
    auto_reply_sent: bool
    similar_faqs: List[PortalFAQResponse]


class PortalCommentRequest(BaseModel):
    """Request to add a comment via portal."""

    ticket_id: str
    email: str
    verification_code: str
    comment: str = Field(..., min_length=10)
    attachments: List[str] = Field(default=[])


class PortalCommentResponse(BaseModel):
    """Response for adding portal comment."""

    success: bool
    comment_id: str
    ticket_id: str
    added_at: str
