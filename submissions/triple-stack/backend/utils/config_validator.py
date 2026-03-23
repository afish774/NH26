"""
==============================================================================
NexDesk Configuration Validation & RAG Verification System
==============================================================================

This module provides:
1. Startup configuration validation
2. RAG system health checks
3. API key validation
4. Service connectivity tests
5. System readiness verification

Usage:
    from utils.config_validator import (
        validate_configuration,
        verify_rag_system,
        run_health_checks,
        SystemHealth
    )

    # On startup
    health = validate_configuration()
    if not health.is_ready:
        print(health.get_error_report())

    # RAG verification
    rag_status = verify_rag_system()

==============================================================================
"""

import os
import sys
import time
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("nexdesk.config")


# =============================================================================
# HEALTH STATUS ENUMS
# =============================================================================


class HealthStatus(str, Enum):
    """Health check status values."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class ComponentType(str, Enum):
    """System component types."""

    CONFIG = "configuration"
    DATABASE = "database"
    REDIS = "redis"
    LLM = "llm_provider"
    RAG = "rag_system"
    EMBEDDING = "embedding_model"
    RERANKER = "reranker"
    TRANSCRIPTION = "transcription"
    AWS = "aws_services"


# =============================================================================
# HEALTH CHECK RESULT STRUCTURES
# =============================================================================


@dataclass
class CheckResult:
    """
    Result of a single health check.

    Attributes:
        component: Which component was checked
        status: OK, WARNING, ERROR, or UNKNOWN
        message: Human-readable status message
        details: Additional context
        latency_ms: How long the check took
        timestamp: When the check was performed
    """

    component: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp.isoformat() + "Z",
        }


@dataclass
class SystemHealth:
    """
    Overall system health status.

    Attributes:
        is_ready: Whether the system is ready to serve requests
        checks: List of individual check results
        errors: List of critical errors that prevent startup
        warnings: List of non-critical issues
    """

    is_ready: bool = True
    checks: List[CheckResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_check(self, result: CheckResult):
        """Add a check result and update overall status."""
        self.checks.append(result)

        if result.status == HealthStatus.ERROR:
            self.errors.append(f"[{result.component}] {result.message}")
            self.is_ready = False
        elif result.status == HealthStatus.WARNING:
            self.warnings.append(f"[{result.component}] {result.message}")

    def get_error_report(self) -> str:
        """Generate a human-readable error report."""
        lines = [
            "=" * 60,
            "NexDesk System Health Report",
            f"Generated: {datetime.utcnow().isoformat()}Z",
            f"Status: {'READY' if self.is_ready else 'NOT READY'}",
            "=" * 60,
        ]

        if self.errors:
            lines.extend(
                [
                    "",
                    "CRITICAL ERRORS (must fix before startup):",
                    "-" * 40,
                ]
            )
            for err in self.errors:
                lines.append(f"  ✗ {err}")

        if self.warnings:
            lines.extend(
                [
                    "",
                    "WARNINGS (non-critical):",
                    "-" * 40,
                ]
            )
            for warn in self.warnings:
                lines.append(f"  ⚠ {warn}")

        if not self.errors and not self.warnings:
            lines.extend(
                [
                    "",
                    "All systems operational. No issues detected.",
                ]
            )

        lines.extend(
            [
                "",
                "COMPONENT STATUS:",
                "-" * 40,
            ]
        )

        for check in self.checks:
            icon = (
                "✓"
                if check.status == HealthStatus.OK
                else "⚠"
                if check.status == HealthStatus.WARNING
                else "✗"
            )
            lines.append(
                f"  {icon} {check.component}: {check.status.value} ({check.latency_ms:.0f}ms)"
            )

        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_ready": self.is_ready,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


# =============================================================================
# CONFIGURATION REQUIREMENTS
# =============================================================================

# Required environment variables (app won't start without these)
REQUIRED_CONFIG = {
    "GROQ_API_KEY": {
        "description": "Groq API key for LLM inference",
        "validation": lambda v: v and len(v) > 10 and v.startswith("gsk_"),
        "help": "Get your API key at https://console.groq.com/keys",
    },
}

# Optional but recommended environment variables
OPTIONAL_CONFIG = {
    "GEMINI_API_KEY": {
        "description": "Google Gemini API key (fallback LLM)",
        "validation": lambda v: v and len(v) > 10,
        "help": "Get your API key at https://aistudio.google.com/app/apikey",
    },
    "SECRET_KEY": {
        "description": "JWT secret key for authentication",
        "validation": lambda v: (
            v and len(v) >= 32 and v != "nexdesk_secret_change_me_in_production"
        ),
        "help": 'Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
    },
    "REDIS_URL": {
        "description": "Redis connection URL for caching",
        "validation": lambda v: v and v.startswith("redis://"),
        "help": "Format: redis://localhost:6379/0",
    },
}

# Feature flags with their defaults and descriptions
FEATURE_FLAGS = {
    "USE_ADVANCED_RAG": {
        "default": "true",
        "description": "Enable LangGraph orchestrator with HyDE and reranking",
    },
    "HYDE_ENABLED": {
        "default": "true",
        "description": "Enable Hypothetical Document Embeddings query expansion",
    },
    "CROSS_ENCODER_ENABLED": {
        "default": "true",
        "description": "Enable cross-encoder reranking for better accuracy",
    },
    "USE_AWS": {
        "default": "false",
        "description": "Enable AWS services (Bedrock, Transcribe, Textract)",
    },
}

# Numeric configuration with validation
NUMERIC_CONFIG = {
    "DEFLECT_THRESHOLD": {
        "default": 0.72,
        "min": 0.0,
        "max": 1.0,
        "description": "AI confidence threshold for KB deflection",
    },
    "HYBRID_ALPHA": {
        "default": 0.7,
        "min": 0.0,
        "max": 1.0,
        "description": "Weight for vector vs BM25 search (0=BM25, 1=vector)",
    },
}


# =============================================================================
# CONFIGURATION VALIDATION
# =============================================================================


def validate_configuration() -> SystemHealth:
    """
    Validate all configuration on startup.

    Checks:
    1. Required environment variables are set and valid
    2. Optional variables are configured correctly if present
    3. Feature flags have valid values
    4. Numeric config is within bounds

    Returns:
        SystemHealth object with validation results
    """
    health = SystemHealth()
    start_time = time.perf_counter()

    logger.info("Starting configuration validation...")

    # Check required config
    for key, spec in REQUIRED_CONFIG.items():
        check_start = time.perf_counter()
        value = os.getenv(key, "")

        if not value:
            health.add_check(
                CheckResult(
                    component=f"config.{key}",
                    status=HealthStatus.ERROR,
                    message=f"Required configuration missing: {key}",
                    details={"description": spec["description"], "help": spec["help"]},
                    latency_ms=(time.perf_counter() - check_start) * 1000,
                )
            )
        elif not spec["validation"](value):
            health.add_check(
                CheckResult(
                    component=f"config.{key}",
                    status=HealthStatus.ERROR,
                    message=f"Invalid configuration value for {key}",
                    details={
                        "description": spec["description"],
                        "help": spec["help"],
                        "hint": "Value does not match expected format",
                    },
                    latency_ms=(time.perf_counter() - check_start) * 1000,
                )
            )
        else:
            health.add_check(
                CheckResult(
                    component=f"config.{key}",
                    status=HealthStatus.OK,
                    message=f"{key} configured correctly",
                    latency_ms=(time.perf_counter() - check_start) * 1000,
                )
            )

    # Check optional config
    for key, spec in OPTIONAL_CONFIG.items():
        check_start = time.perf_counter()
        value = os.getenv(key, "")

        if not value:
            health.add_check(
                CheckResult(
                    component=f"config.{key}",
                    status=HealthStatus.WARNING,
                    message=f"Optional configuration not set: {key}",
                    details={"description": spec["description"], "help": spec["help"]},
                    latency_ms=(time.perf_counter() - check_start) * 1000,
                )
            )
        elif not spec["validation"](value):
            health.add_check(
                CheckResult(
                    component=f"config.{key}",
                    status=HealthStatus.WARNING,
                    message=f"Configuration may be invalid: {key}",
                    details={"description": spec["description"], "help": spec["help"]},
                    latency_ms=(time.perf_counter() - check_start) * 1000,
                )
            )
        else:
            health.add_check(
                CheckResult(
                    component=f"config.{key}",
                    status=HealthStatus.OK,
                    message=f"{key} configured correctly",
                    latency_ms=(time.perf_counter() - check_start) * 1000,
                )
            )

    # Check numeric config
    for key, spec in NUMERIC_CONFIG.items():
        check_start = time.perf_counter()
        value_str = os.getenv(key, str(spec["default"]))

        try:
            value = float(value_str)
            if value < spec["min"] or value > spec["max"]:
                health.add_check(
                    CheckResult(
                        component=f"config.{key}",
                        status=HealthStatus.WARNING,
                        message=f"{key} value {value} outside recommended range [{spec['min']}, {spec['max']}]",
                        details={
                            "value": value,
                            "min": spec["min"],
                            "max": spec["max"],
                        },
                        latency_ms=(time.perf_counter() - check_start) * 1000,
                    )
                )
            else:
                health.add_check(
                    CheckResult(
                        component=f"config.{key}",
                        status=HealthStatus.OK,
                        message=f"{key} = {value}",
                        details={"value": value},
                        latency_ms=(time.perf_counter() - check_start) * 1000,
                    )
                )
        except ValueError:
            health.add_check(
                CheckResult(
                    component=f"config.{key}",
                    status=HealthStatus.ERROR,
                    message=f"Invalid numeric value for {key}: {value_str}",
                    details={"value": value_str, "expected": "float"},
                    latency_ms=(time.perf_counter() - check_start) * 1000,
                )
            )

    total_time = (time.perf_counter() - start_time) * 1000
    logger.info(f"Configuration validation complete in {total_time:.0f}ms")

    return health


# =============================================================================
# RAG SYSTEM VERIFICATION
# =============================================================================


def verify_rag_system() -> CheckResult:
    """
    Verify the RAG system is operational.

    Checks:
    1. ChromaDB collection exists and has documents
    2. Embedding model can generate embeddings
    3. Test query returns results

    Returns:
        CheckResult with RAG system status
    """
    start_time = time.perf_counter()
    details = {}

    try:
        # Check ChromaDB
        import chromadb
        from chromadb.config import Settings

        chroma = chromadb.Client(Settings(anonymized_telemetry=False))

        try:
            collection = chroma.get_collection("nexdesk_kb")
            doc_count = collection.count()
            details["knowledge_base_documents"] = doc_count

            if doc_count == 0:
                return CheckResult(
                    component=ComponentType.RAG.value,
                    status=HealthStatus.WARNING,
                    message="Knowledge base is empty",
                    details=details,
                    latency_ms=(time.perf_counter() - start_time) * 1000,
                )

            # Test embedding generation
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer("all-MiniLM-L6-v2")
            test_embedding = model.encode("test query")
            details["embedding_dimension"] = len(test_embedding)

            # Test query
            test_results = collection.query(query_texts=["password reset"], n_results=1)
            details["test_query_results"] = len(test_results.get("documents", [[]])[0])

            # Check advanced RAG components if enabled
            if os.getenv("USE_ADVANCED_RAG", "true").lower() == "true":
                details["advanced_rag_enabled"] = True

                # Check HyDE
                if os.getenv("HYDE_ENABLED", "true").lower() == "true":
                    details["hyde_enabled"] = True

                # Check cross-encoder
                if os.getenv("CROSS_ENCODER_ENABLED", "true").lower() == "true":
                    try:
                        from sentence_transformers import CrossEncoder

                        # Don't actually load the model (slow), just check import
                        details["cross_encoder_available"] = True
                    except ImportError:
                        details["cross_encoder_available"] = False

            return CheckResult(
                component=ComponentType.RAG.value,
                status=HealthStatus.OK,
                message=f"RAG system operational with {doc_count} documents",
                details=details,
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )

        except Exception as e:
            if "does not exist" in str(e).lower():
                return CheckResult(
                    component=ComponentType.RAG.value,
                    status=HealthStatus.WARNING,
                    message="Knowledge base collection not found (will be created on first use)",
                    details={"error": str(e)},
                    latency_ms=(time.perf_counter() - start_time) * 1000,
                )
            raise

    except ImportError as e:
        return CheckResult(
            component=ComponentType.RAG.value,
            status=HealthStatus.ERROR,
            message=f"RAG dependencies not installed: {str(e)}",
            details={"missing_module": str(e)},
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )
    except Exception as e:
        return CheckResult(
            component=ComponentType.RAG.value,
            status=HealthStatus.ERROR,
            message=f"RAG system verification failed: {str(e)}",
            details={"error": str(e), "type": type(e).__name__},
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )


# =============================================================================
# LLM PROVIDER VERIFICATION
# =============================================================================


def verify_llm_provider() -> CheckResult:
    """
    Verify LLM provider connectivity.

    Checks Groq API (primary) and Gemini (fallback) if configured.

    Returns:
        CheckResult with LLM status
    """
    start_time = time.perf_counter()
    details = {}

    # Check Groq (primary)
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        try:
            from groq import Groq

            client = Groq(api_key=groq_key)

            # Make a minimal API call to verify connectivity
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            details["groq_status"] = "connected"
            details["groq_model"] = "llama-3.3-70b-versatile"

        except Exception as e:
            details["groq_status"] = "error"
            details["groq_error"] = str(e)[:100]
    else:
        details["groq_status"] = "not_configured"

    # Check Gemini (fallback)
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            import google.generativeai as genai

            genai.configure(api_key=gemini_key)
            # Just verify configuration, don't make API call
            details["gemini_status"] = "configured"
        except Exception as e:
            details["gemini_status"] = "error"
            details["gemini_error"] = str(e)[:100]
    else:
        details["gemini_status"] = "not_configured"

    # Determine overall status
    latency_ms = (time.perf_counter() - start_time) * 1000

    if details.get("groq_status") == "connected":
        return CheckResult(
            component=ComponentType.LLM.value,
            status=HealthStatus.OK,
            message="LLM provider connected (Groq)",
            details=details,
            latency_ms=latency_ms,
        )
    elif details.get("groq_status") == "error":
        if details.get("gemini_status") in ["configured", "connected"]:
            return CheckResult(
                component=ComponentType.LLM.value,
                status=HealthStatus.WARNING,
                message="Primary LLM (Groq) failed, fallback (Gemini) available",
                details=details,
                latency_ms=latency_ms,
            )
        return CheckResult(
            component=ComponentType.LLM.value,
            status=HealthStatus.ERROR,
            message="LLM provider connection failed",
            details=details,
            latency_ms=latency_ms,
        )
    else:
        return CheckResult(
            component=ComponentType.LLM.value,
            status=HealthStatus.ERROR,
            message="No LLM provider configured",
            details=details,
            latency_ms=latency_ms,
        )


# =============================================================================
# DATABASE VERIFICATION
# =============================================================================


def verify_database() -> CheckResult:
    """
    Verify database connectivity.

    Returns:
        CheckResult with database status
    """
    start_time = time.perf_counter()
    details = {}

    try:
        from database.connection import engine, SessionLocal
        from sqlalchemy import text

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()

        # Get database info
        db_url = str(engine.url)
        if "sqlite" in db_url:
            details["database_type"] = "SQLite"
            details["mode"] = "development"
        else:
            details["database_type"] = "PostgreSQL"
            details["mode"] = "production"

        # Check tables exist
        with SessionLocal() as db:
            from database.models import Ticket, Agent, ChatMessage

            ticket_count = db.query(Ticket).count()
            agent_count = db.query(Agent).count()
            details["ticket_count"] = ticket_count
            details["agent_count"] = agent_count

        return CheckResult(
            component=ComponentType.DATABASE.value,
            status=HealthStatus.OK,
            message=f"Database connected ({details['database_type']})",
            details=details,
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    except ImportError as e:
        return CheckResult(
            component=ComponentType.DATABASE.value,
            status=HealthStatus.ERROR,
            message=f"Database module not found: {str(e)}",
            details={"error": str(e)},
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )
    except Exception as e:
        return CheckResult(
            component=ComponentType.DATABASE.value,
            status=HealthStatus.ERROR,
            message=f"Database connection failed: {str(e)}",
            details={"error": str(e), "type": type(e).__name__},
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )


# =============================================================================
# REDIS VERIFICATION
# =============================================================================


async def verify_redis() -> CheckResult:
    """
    Verify Redis connectivity (async).

    Returns:
        CheckResult with Redis status
    """
    start_time = time.perf_counter()
    details = {}

    redis_url = os.getenv("REDIS_URL", "")

    if not redis_url:
        return CheckResult(
            component=ComponentType.REDIS.value,
            status=HealthStatus.WARNING,
            message="Redis not configured (caching disabled)",
            details={"configured": False},
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    try:
        import redis.asyncio as redis

        client = redis.from_url(redis_url)
        await client.ping()

        # Get Redis info
        info = await client.info("server")
        details["redis_version"] = info.get("redis_version", "unknown")
        details["connected"] = True

        await client.close()

        return CheckResult(
            component=ComponentType.REDIS.value,
            status=HealthStatus.OK,
            message=f"Redis connected (v{details['redis_version']})",
            details=details,
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    except ImportError:
        return CheckResult(
            component=ComponentType.REDIS.value,
            status=HealthStatus.WARNING,
            message="Redis module not installed",
            details={"installed": False},
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )
    except Exception as e:
        return CheckResult(
            component=ComponentType.REDIS.value,
            status=HealthStatus.WARNING,
            message=f"Redis connection failed: {str(e)}",
            details={"error": str(e)},
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )


# =============================================================================
# FULL HEALTH CHECK
# =============================================================================


async def run_health_checks(include_llm_test: bool = False) -> SystemHealth:
    """
    Run all health checks.

    Args:
        include_llm_test: Whether to make actual LLM API call (slower but thorough)

    Returns:
        SystemHealth with all check results
    """
    logger.info("Running comprehensive health checks...")
    start_time = time.perf_counter()

    # Start with configuration validation
    health = validate_configuration()

    # Run component checks
    health.add_check(verify_database())
    health.add_check(await verify_redis())
    health.add_check(verify_rag_system())

    if include_llm_test:
        health.add_check(verify_llm_provider())

    total_time = (time.perf_counter() - start_time) * 1000
    logger.info(
        f"Health checks complete in {total_time:.0f}ms - Ready: {health.is_ready}"
    )

    return health


def run_health_checks_sync(include_llm_test: bool = False) -> SystemHealth:
    """
    Synchronous wrapper for health checks (for startup use).

    Args:
        include_llm_test: Whether to make actual LLM API call

    Returns:
        SystemHealth with all check results
    """
    return asyncio.get_event_loop().run_until_complete(
        run_health_checks(include_llm_test)
    )


# =============================================================================
# STARTUP VALIDATION
# =============================================================================


def validate_on_startup(strict: bool = False) -> bool:
    """
    Validate configuration and system health on startup.

    Call this in main.py lifespan to ensure system is properly configured.

    Args:
        strict: If True, exit on any errors. If False, only exit on critical errors.

    Returns:
        True if system is ready, False otherwise

    Example:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            if not validate_on_startup():
                sys.exit(1)
            yield
    """
    print("\n" + "=" * 60)
    print("NexDesk Startup Validation")
    print("=" * 60)

    health = validate_configuration()

    # Add basic checks (not async ones for startup)
    health.add_check(verify_database())
    health.add_check(verify_rag_system())

    # Print report
    print(health.get_error_report())

    if not health.is_ready:
        print("\n⛔ STARTUP BLOCKED: Critical errors must be resolved")
        print("   See API_KEYS.md and CONFIGURATION.md for setup instructions")
        return False

    if health.warnings and strict:
        print("\n⚠️  STRICT MODE: Warnings treated as errors")
        return False

    print("\n✅ System ready to start")
    return True


# =============================================================================
# RAG PERFORMANCE TEST
# =============================================================================


def test_rag_performance(num_queries: int = 5) -> Dict[str, Any]:
    """
    Run performance tests on the RAG system.

    Tests retrieval speed and accuracy with sample queries.

    Args:
        num_queries: Number of test queries to run

    Returns:
        Dictionary with performance metrics
    """
    test_queries = [
        "How do I reset my password?",
        "VPN connection not working",
        "Printer not printing",
        "Install software on laptop",
        "Access denied error",
    ][:num_queries]

    results = {
        "queries_tested": len(test_queries),
        "timings": [],
        "errors": [],
    }

    try:
        from ai.rag import retrieve_context

        for query in test_queries:
            start = time.perf_counter()
            try:
                context = retrieve_context(query)
                duration = (time.perf_counter() - start) * 1000
                results["timings"].append(
                    {
                        "query": query,
                        "duration_ms": duration,
                        "results_count": len(context) if context else 0,
                    }
                )
            except Exception as e:
                results["errors"].append({"query": query, "error": str(e)})

        if results["timings"]:
            durations = [t["duration_ms"] for t in results["timings"]]
            results["avg_latency_ms"] = sum(durations) / len(durations)
            results["min_latency_ms"] = min(durations)
            results["max_latency_ms"] = max(durations)

        results["status"] = "ok" if not results["errors"] else "partial_failure"

    except ImportError as e:
        results["status"] = "error"
        results["error"] = f"RAG module not available: {str(e)}"

    return results
