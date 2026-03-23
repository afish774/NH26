"""
==============================================================================
NexDesk Centralized Exception Handling System
==============================================================================

This module provides:
1. Custom exception classes for different error types
2. Standardized error response format
3. Global exception handlers for FastAPI
4. Error logging with context

Usage:
    from utils.exceptions import (
        NexDeskException,
        ValidationError,
        NotFoundError,
        AIServiceError,
        DatabaseError,
        error_response
    )

    # Raise custom exceptions
    raise NotFoundError("Ticket", ticket_id)
    raise AIServiceError("Groq", "Rate limit exceeded")
    raise ValidationError("email", "Invalid email format")

==============================================================================
"""

import os
import sys
import logging
import traceback
from datetime import datetime
from typing import Optional, Dict, Any, List
from functools import wraps
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

# Configure logging based on environment
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("nexdesk")


# =============================================================================
# STANDARDIZED ERROR RESPONSE MODEL
# =============================================================================


class ErrorDetail(BaseModel):
    """
    Standardized error response format for all NexDesk API errors.

    Attributes:
        error: Human-readable error message
        error_code: Machine-readable error code (e.g., "TICKET_NOT_FOUND")
        details: Additional error context (optional)
        timestamp: ISO format timestamp of when error occurred
        request_id: Unique request identifier for tracing (optional)
        path: API path that generated the error (optional)
    """

    error: str
    error_code: str
    details: Optional[Dict[str, Any]] = None
    timestamp: str
    request_id: Optional[str] = None
    path: Optional[str] = None


def error_response(
    status_code: int,
    error_code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> JSONResponse:
    """
    Create a standardized JSON error response.

    Args:
        status_code: HTTP status code (400, 404, 500, etc.)
        error_code: Machine-readable code (e.g., "VALIDATION_ERROR")
        message: Human-readable error message
        details: Additional context dictionary
        request: FastAPI request object for path/request_id extraction

    Returns:
        JSONResponse with standardized error format

    Example:
        return error_response(
            404,
            "TICKET_NOT_FOUND",
            f"Ticket {ticket_id} not found",
            {"ticket_id": ticket_id}
        )
    """
    content = ErrorDetail(
        error=message,
        error_code=error_code,
        details=details,
        timestamp=datetime.utcnow().isoformat() + "Z",
        request_id=getattr(request.state, "request_id", None) if request else None,
        path=str(request.url.path) if request else None,
    ).model_dump(exclude_none=True)

    return JSONResponse(status_code=status_code, content=content)


# =============================================================================
# CUSTOM EXCEPTION CLASSES
# =============================================================================


class NexDeskException(Exception):
    """
    Base exception class for all NexDesk errors.

    All custom exceptions inherit from this class to enable
    centralized exception handling in FastAPI.

    Attributes:
        message: Human-readable error message
        error_code: Machine-readable error code
        status_code: HTTP status code to return
        details: Additional error context
    """

    def __init__(
        self,
        message: str,
        error_code: str = "NEXDESK_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_response(self, request: Optional[Request] = None) -> JSONResponse:
        """Convert exception to standardized JSON response."""
        return error_response(
            self.status_code, self.error_code, self.message, self.details, request
        )


class ValidationError(NexDeskException):
    """
    Raised when request validation fails.

    Usage:
        raise ValidationError("email", "Invalid email format")
        raise ValidationError("audio_file", "File too large", {"max_size_mb": 25})
    """

    def __init__(self, field: str, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"Validation error on '{field}': {message}",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"field": field, **(details or {})},
        )


class NotFoundError(NexDeskException):
    """
    Raised when a requested resource is not found.

    Usage:
        raise NotFoundError("Ticket", ticket_id)
        raise NotFoundError("Agent", agent_id)
    """

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} not found: {resource_id}",
            error_code=f"{resource_type.upper()}_NOT_FOUND",
            status_code=404,
            details={"resource_type": resource_type, "resource_id": resource_id},
        )


class AIServiceError(NexDeskException):
    """
    Raised when an AI service (Groq, Gemini, Bedrock) fails.

    Usage:
        raise AIServiceError("Groq", "Rate limit exceeded")
        raise AIServiceError("ChromaDB", "Collection not found")
    """

    def __init__(self, service: str, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"AI service error ({service}): {message}",
            error_code="AI_SERVICE_ERROR",
            status_code=503,
            details={"service": service, **(details or {})},
        )


class DatabaseError(NexDeskException):
    """
    Raised when a database operation fails.

    Usage:
        raise DatabaseError("Failed to create ticket", {"operation": "insert"})
    """

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"Database error: {message}",
            error_code="DATABASE_ERROR",
            status_code=500,
            details=details,
        )


class ConfigurationError(NexDeskException):
    """
    Raised when configuration is missing or invalid.

    Usage:
        raise ConfigurationError("GROQ_API_KEY", "API key is required")
    """

    def __init__(self, config_key: str, message: str):
        super().__init__(
            message=f"Configuration error ({config_key}): {message}",
            error_code="CONFIGURATION_ERROR",
            status_code=500,
            details={"config_key": config_key},
        )


class RateLimitError(NexDeskException):
    """
    Raised when rate limit is exceeded.

    Usage:
        raise RateLimitError("chat", 60, 100)  # 100 requests per 60 seconds
    """

    def __init__(self, resource: str, window_seconds: int, limit: int):
        super().__init__(
            message=f"Rate limit exceeded for {resource}. Limit: {limit} requests per {window_seconds} seconds",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details={
                "resource": resource,
                "window_seconds": window_seconds,
                "limit": limit,
            },
        )


class ExternalServiceError(NexDeskException):
    """
    Raised when an external service (AWS, Redis) fails.

    Usage:
        raise ExternalServiceError("AWS Transcribe", "Bucket not found")
    """

    def __init__(self, service: str, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"External service error ({service}): {message}",
            error_code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
            details={"service": service, **(details or {})},
        )


class TranscriptionError(NexDeskException):
    """
    Raised when audio transcription fails.

    Usage:
        raise TranscriptionError("Audio format not supported", {"format": "aac"})
    """

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"Transcription error: {message}",
            error_code="TRANSCRIPTION_ERROR",
            status_code=422,
            details=details,
        )


class TicketNotFoundError(NexDeskException):
    """
    Raised when a ticket is not found.

    Usage:
        raise TicketNotFoundError(ticket_id)
    """

    def __init__(self, ticket_id: str):
        super().__init__(
            message=f"Ticket not found: {ticket_id}",
            error_code="TICKET_NOT_FOUND",
            status_code=404,
            details={"ticket_id": ticket_id},
        )


class AgentNotFoundError(NexDeskException):
    """
    Raised when an agent is not found.

    Usage:
        raise AgentNotFoundError(agent_id)
    """

    def __init__(self, agent_id: str):
        super().__init__(
            message=f"Agent not found: {agent_id}",
            error_code="AGENT_NOT_FOUND",
            status_code=404,
            details={"agent_id": agent_id},
        )


class ServiceNotFoundError(NexDeskException):
    """
    Raised when a network service is not found.

    Usage:
        raise ServiceNotFoundError(service_id)
    """

    def __init__(self, service_id: str):
        super().__init__(
            message=f"Network service not found: {service_id}",
            error_code="SERVICE_NOT_FOUND",
            status_code=404,
            details={"service_id": service_id},
        )


class KnowledgeSourceNotFoundError(NexDeskException):
    """
    Raised when a knowledge source is not found.

    Usage:
        raise KnowledgeSourceNotFoundError(source_id)
    """

    def __init__(self, source_id: str):
        super().__init__(
            message=f"Knowledge source not found: {source_id}",
            error_code="KNOWLEDGE_SOURCE_NOT_FOUND",
            status_code=404,
            details={"source_id": source_id},
        )


class RAGError(NexDeskException):
    """
    Raised when RAG pipeline fails.

    Usage:
        raise RAGError("Knowledge base empty", {"kb_size": 0})
    """

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"RAG error: {message}",
            error_code="RAG_ERROR",
            status_code=500,
            details=details,
        )


# =============================================================================
# GLOBAL EXCEPTION HANDLERS FOR FASTAPI
# =============================================================================


async def nexdesk_exception_handler(
    request: Request, exc: NexDeskException
) -> JSONResponse:
    """
    Handle all NexDeskException subclasses.

    Logs the error and returns standardized response.
    """
    logger.error(
        f"NexDeskException: {exc.error_code} | {exc.message}",
        extra={"details": exc.details, "path": request.url.path},
    )
    return exc.to_response(request)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Handle FastAPI HTTPException with standardized format.

    Converts HTTPException to our standard error format.
    """
    error_code = "HTTP_ERROR"
    if exc.status_code == 404:
        error_code = "NOT_FOUND"
    elif exc.status_code == 400:
        error_code = "BAD_REQUEST"
    elif exc.status_code == 401:
        error_code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        error_code = "FORBIDDEN"
    elif exc.status_code == 422:
        error_code = "UNPROCESSABLE_ENTITY"

    logger.warning(
        f"HTTPException: {exc.status_code} | {exc.detail}",
        extra={"path": request.url.path},
    )

    return error_response(exc.status_code, error_code, str(exc.detail), request=request)


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Handle Pydantic validation errors.

    Converts Pydantic ValidationError to our standard format.
    """
    from pydantic import ValidationError as PydanticValidationError

    if isinstance(exc, PydanticValidationError):
        errors = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            errors.append(
                {"field": field, "message": error["msg"], "type": error["type"]}
            )

        logger.warning(
            f"Validation error: {len(errors)} field(s) invalid",
            extra={"errors": errors, "path": request.url.path},
        )

        return error_response(
            422,
            "VALIDATION_ERROR",
            f"Request validation failed: {len(errors)} error(s)",
            {"errors": errors},
            request,
        )

    # Fallback for other validation-like errors
    return error_response(422, "VALIDATION_ERROR", str(exc), request=request)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unhandled exceptions.

    Logs full traceback and returns generic error to client.
    IMPORTANT: Does not expose internal details to client for security.
    """
    # Log full traceback for debugging
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "traceback": traceback.format_exc(),
        },
    )

    # Return generic error to client (no internal details)
    return error_response(
        500,
        "INTERNAL_ERROR",
        "An unexpected error occurred. Please try again later.",
        # Only include request_id for support reference
        {"support_hint": "If this persists, contact support with the timestamp."},
        request,
    )


def register_exception_handlers(app):
    """
    Register all exception handlers with FastAPI app.

    Call this in main.py after creating the app:
        from utils.exceptions import register_exception_handlers
        register_exception_handlers(app)

    Args:
        app: FastAPI application instance
    """
    from pydantic import ValidationError as PydanticValidationError
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(NexDeskException, nexdesk_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(PydanticValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    logger.info("Exception handlers registered")


# =============================================================================
# ERROR HANDLING DECORATORS
# =============================================================================


def handle_errors(
    error_message: str = "Operation failed",
    error_code: str = "OPERATION_ERROR",
    reraise: bool = True,
):
    """
    Decorator to add error handling to any function.

    Usage:
        @handle_errors("Failed to process ticket", "TICKET_PROCESSING_ERROR")
        async def process_ticket(ticket_id: str):
            ...

    Args:
        error_message: Message to include in error
        error_code: Error code for the error response
        reraise: Whether to re-raise as NexDeskException or return None
    """

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except NexDeskException:
                raise  # Already our exception, re-raise
            except Exception as e:
                logger.error(f"{error_message}: {str(e)}", exc_info=True)
                if reraise:
                    raise NexDeskException(
                        message=f"{error_message}: {str(e)}", error_code=error_code
                    )
                return None

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except NexDeskException:
                raise
            except Exception as e:
                logger.error(f"{error_message}: {str(e)}", exc_info=True)
                if reraise:
                    raise NexDeskException(
                        message=f"{error_message}: {str(e)}", error_code=error_code
                    )
                return None

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def safe_execute(func, default=None, log_error: bool = True):
    """
    Execute a function safely, returning default on any error.

    Usage:
        result = safe_execute(lambda: risky_operation(), default={})
        result = safe_execute(get_user, default=None, log_error=False)

    Args:
        func: Callable to execute
        default: Value to return on error
        log_error: Whether to log the error

    Returns:
        Function result or default value
    """
    try:
        return func()
    except Exception as e:
        if log_error:
            logger.warning(f"safe_execute caught error: {str(e)}")
        return default


# =============================================================================
# ERROR AGGREGATION FOR BATCH OPERATIONS
# =============================================================================


class ErrorCollector:
    """
    Collect errors during batch operations without stopping execution.

    Usage:
        collector = ErrorCollector()

        for item in items:
            try:
                process(item)
            except Exception as e:
                collector.add(f"Failed to process {item}", e)

        if collector.has_errors():
            raise collector.to_exception()
    """

    def __init__(self):
        self.errors: List[Dict[str, Any]] = []

    def add(self, message: str, exception: Optional[Exception] = None):
        """Add an error to the collection."""
        self.errors.append(
            {
                "message": message,
                "exception": str(exception) if exception else None,
                "type": type(exception).__name__ if exception else None,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        logger.warning(f"ErrorCollector: {message} - {exception}")

    def has_errors(self) -> bool:
        """Check if any errors were collected."""
        return len(self.errors) > 0

    def count(self) -> int:
        """Get number of collected errors."""
        return len(self.errors)

    def to_exception(self) -> NexDeskException:
        """Convert collected errors to a single exception."""
        return NexDeskException(
            message=f"Batch operation completed with {len(self.errors)} error(s)",
            error_code="BATCH_OPERATION_ERRORS",
            status_code=207,  # Multi-Status
            details={"errors": self.errors},
        )

    def clear(self):
        """Clear all collected errors."""
        self.errors = []
