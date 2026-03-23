"""
==============================================================================
NexDesk API - Main Application Entry Point
==============================================================================

FastAPI application with:
- AI-powered chat deflection (RAG + LangGraph)
- Smart ticket classification and routing
- Voice transcription and processing
- Real-time WebSocket updates
- Comprehensive error handling and monitoring
- Network monitoring system
- Human-in-the-loop feedback
- Precision-recall calibration
- Knowledge base management

Version: 2.4.0
Features: Docker, PostgreSQL, Redis, WebSockets, Voice, Network Monitoring,
          Feedback, Simulation, Knowledge Management

==============================================================================
"""

import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("nexdesk.main")

# =============================================================================
# IMPORTS (after logging configured)
# =============================================================================

from database.connection import create_tables, check_database_health
from ai.rag import seed_knowledge_base
from routers import (
    chat,
    tickets,
    analytics,
    screenshot,
    agents,
    websocket,
    voice,
    network,
    feedback,
    simulation,
    knowledge,
    triage,
    email,
    integrations,
    portal,
)
from utils.redis_client import redis_client
from utils.websocket_manager import manager as ws_manager
from utils.exceptions import register_exception_handlers, NexDeskException
from utils.performance import PerformanceMonitor, PerformanceMiddleware
from utils.config_validator import (
    validate_configuration,
    verify_rag_system,
    SystemHealth,
)
from utils.network_monitor import run_monitoring_loop, stop_monitoring


# =============================================================================
# APPLICATION LIFESPAN
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown events.

    Startup:
        1. Validate configuration
        2. Create database tables
        3. Seed knowledge base
        4. Connect to Redis
        5. Verify RAG system

    Shutdown:
        1. Disconnect Redis
        2. Close WebSocket connections
    """
    startup_time = datetime.utcnow()

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIGURATION VALIDATION
    # ─────────────────────────────────────────────────────────────────────────

    logger.info("=" * 60)
    logger.info("NexDesk API Starting...")
    logger.info("=" * 60)

    # Validate configuration
    config_health = validate_configuration()

    if not config_health.is_ready:
        logger.error("Configuration validation failed!")
        for error in config_health.errors:
            logger.error(f"  ✗ {error}")
        logger.error("See API_KEYS.md and CONFIGURATION.md for setup instructions")
        # Don't exit - allow startup with warnings for development
        if os.getenv("STRICT_STARTUP", "false").lower() == "true":
            sys.exit(1)
    else:
        logger.info("✓ Configuration validated")

    # Log warnings
    for warning in config_health.warnings:
        logger.warning(f"  ⚠ {warning}")

    # ─────────────────────────────────────────────────────────────────────────
    # DATABASE INITIALIZATION
    # ─────────────────────────────────────────────────────────────────────────

    try:
        create_tables()
        logger.info("✓ Database tables created/verified")
    except Exception as e:
        logger.error(f"✗ Database initialization failed: {e}")
        if os.getenv("STRICT_STARTUP", "false").lower() == "true":
            sys.exit(1)

    # ─────────────────────────────────────────────────────────────────────────
    # KNOWLEDGE BASE SEEDING
    # ─────────────────────────────────────────────────────────────────────────

    try:
        seed_knowledge_base()
        logger.info("✓ Knowledge base seeded")
    except Exception as e:
        logger.error(f"✗ Knowledge base seeding failed: {e}")
        # Non-fatal - continue startup

    # ─────────────────────────────────────────────────────────────────────────
    # REDIS CONNECTION
    # ─────────────────────────────────────────────────────────────────────────

    redis_available = await redis_client.connect()
    if redis_available:
        logger.info("✓ Redis connected")
    else:
        logger.warning("⚠ Redis unavailable — running without caching/queuing")

    # ─────────────────────────────────────────────────────────────────────────
    # RAG SYSTEM VERIFICATION
    # ─────────────────────────────────────────────────────────────────────────

    try:
        rag_check = verify_rag_system()
        if rag_check.status.value == "ok":
            doc_count = rag_check.details.get("knowledge_base_documents", 0)
            logger.info(f"✓ RAG system ready ({doc_count} documents)")
        elif rag_check.status.value == "warning":
            logger.warning(f"⚠ RAG system: {rag_check.message}")
        else:
            logger.error(f"✗ RAG system: {rag_check.message}")
    except Exception as e:
        logger.warning(f"⚠ RAG verification skipped: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # NETWORK MONITORING
    # ─────────────────────────────────────────────────────────────────────────

    network_monitoring_task = None
    if os.getenv("ENABLE_NETWORK_MONITORING", "true").lower() == "true":
        try:
            network_monitoring_task = asyncio.create_task(run_monitoring_loop())
            logger.info("✓ Network monitoring started")
        except Exception as e:
            logger.warning(f"⚠ Network monitoring failed to start: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # STARTUP COMPLETE
    # ─────────────────────────────────────────────────────────────────────────

    startup_duration = (datetime.utcnow() - startup_time).total_seconds()

    logger.info("=" * 60)
    logger.info(f"🚀 NexDesk API ready — v2.4.0")
    logger.info(f"   Startup time: {startup_duration:.2f}s")
    logger.info(
        f"   Mode: {'Production (AWS)' if os.getenv('USE_AWS') == 'true' else 'Development (Groq)'}"
    )
    logger.info(
        f"   Advanced RAG: {'Enabled' if os.getenv('USE_ADVANCED_RAG', 'true').lower() == 'true' else 'Disabled'}"
    )
    logger.info(
        f"   Network Monitoring: {'Enabled' if os.getenv('ENABLE_NETWORK_MONITORING', 'true').lower() == 'true' else 'Disabled'}"
    )
    logger.info("=" * 60)

    yield

    # ─────────────────────────────────────────────────────────────────────────
    # SHUTDOWN
    # ─────────────────────────────────────────────────────────────────────────

    logger.info("Shutting down NexDesk API...")

    # Stop network monitoring
    stop_monitoring()
    if network_monitoring_task:
        network_monitoring_task.cancel()
        try:
            await network_monitoring_task
        except asyncio.CancelledError:
            pass

    await redis_client.disconnect()
    await ws_manager.disconnect_all()

    logger.info("👋 NexDesk API shutdown complete")


# =============================================================================
# APPLICATION FACTORY
# =============================================================================

app = FastAPI(
    title="NexDesk API",
    description="AI-powered IT helpdesk with smart ticket deflection",
    version="2.4.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# =============================================================================
# MIDDLEWARE
# =============================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.amplifyapp.com",
        os.getenv("FRONTEND_URL", "http://localhost:3000"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Performance Monitoring (optional - disable in production for performance)
if os.getenv("ENABLE_PERFORMANCE_MONITORING", "true").lower() == "true":
    app.add_middleware(PerformanceMiddleware)

# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================

register_exception_handlers(app)

# =============================================================================
# ROUTERS
# =============================================================================

# Core API routes
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["Tickets"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(
    screenshot.router, prefix="/api/tickets/screenshot", tags=["Screenshot"]
)
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"])
app.include_router(voice.router, prefix="/api/voice", tags=["Voice"])

# New v2.4.0 routes
app.include_router(network.router, prefix="/api/network", tags=["Network Monitoring"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(
    simulation.router, prefix="/api/simulation", tags=["Simulation & Calibration"]
)
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge Base"])
app.include_router(triage.router, prefix="/api/triage", tags=["Triage"])
app.include_router(email.router, prefix="/api", tags=["Email"])
app.include_router(integrations.router, prefix="/api", tags=["Integrations"])
app.include_router(portal.router, prefix="/api", tags=["Portal"])

# WebSocket Router (no prefix - uses /ws path directly)
app.include_router(websocket.router, tags=["WebSocket"])


# =============================================================================
# HEALTH & DIAGNOSTICS ENDPOINTS
# =============================================================================


@app.get("/health", tags=["Health"])
async def health():
    """
    Health check endpoint with system status.

    Returns basic system health for load balancers and monitoring.
    For detailed diagnostics, use /health/detailed.
    """
    redis_status = await redis_client.health_check()
    db_health = check_database_health()

    return {
        "status": "ok",
        "version": "2.4.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "components": {
            "api": "healthy",
            "database": db_health.get("status", "unknown"),
            "redis": "connected" if redis_status else "unavailable",
            "websockets": "enabled",
        },
    }


@app.get("/health/detailed", tags=["Health"])
async def health_detailed():
    """
    Detailed health check with all component statuses.

    Includes:
    - Configuration status
    - Database connectivity
    - Redis status
    - RAG system status
    - Performance metrics
    """
    from utils.config_validator import run_health_checks
    from utils.network_monitor import is_monitoring_active

    health = await run_health_checks(include_llm_test=False)

    return {
        "status": "healthy" if health.is_ready else "degraded",
        "version": "2.4.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "configuration": {
            "aws_mode": os.getenv("USE_AWS", "false"),
            "model": "bedrock-claude-3-5"
            if os.getenv("USE_AWS") == "true"
            else "groq-llama-3.3-70b",
            "advanced_rag": os.getenv("USE_ADVANCED_RAG", "true").lower() == "true",
            "hyde_enabled": os.getenv("HYDE_ENABLED", "true").lower() == "true",
            "cross_encoder_enabled": os.getenv("CROSS_ENCODER_ENABLED", "true").lower()
            == "true",
            "deflect_threshold": float(os.getenv("DEFLECT_THRESHOLD", "0.72")),
            "network_monitoring": is_monitoring_active(),
        },
        "checks": [c.to_dict() for c in health.checks],
        "errors": health.errors,
        "warnings": health.warnings,
    }


@app.get("/health/performance", tags=["Health"])
async def health_performance():
    """
    Get performance metrics and timing statistics.

    Returns aggregated timing data for all tracked operations.
    """
    from utils.performance import get_metrics, generate_performance_report

    return get_metrics()


@app.get("/", tags=["Health"])
async def root():
    """
    Root endpoint - API information.
    """
    return {
        "name": "NexDesk API",
        "version": "2.4.0",
        "description": "AI-powered IT helpdesk with smart ticket deflection",
        "docs": "/docs",
        "health": "/health",
        "features": [
            "AI Chat with RAG",
            "Ticket Classification",
            "Voice Transcription",
            "Network Monitoring",
            "Feedback & Calibration",
            "Knowledge Management",
        ],
    }


# =============================================================================
# AWS LAMBDA HANDLER
# =============================================================================

# Works both locally and on AWS Lambda
try:
    from mangum import Mangum

    handler = Mangum(app)
    logger.info("AWS Lambda handler (Mangum) loaded")
except ImportError:
    handler = None  # Not running on Lambda
