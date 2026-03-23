"""
==============================================================================
NexDesk Performance Monitoring System
==============================================================================

This module provides:
1. Request/Response timing measurement
2. AI operation latency tracking
3. Database query timing
4. Performance metrics aggregation
5. Slow operation alerts

Usage:
    from utils.performance import (
        PerformanceMonitor,
        track_time,
        get_metrics,
        record_metric
    )

    # Use decorator for automatic timing
    @track_time("rag_retrieval")
    async def retrieve_documents(query: str):
        ...

    # Manual timing
    with PerformanceMonitor.timer("llm_inference"):
        response = await llm.generate(prompt)

    # Record custom metrics
    record_metric("chat_deflection_rate", 0.73)

==============================================================================
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from functools import wraps
from contextlib import contextmanager
from collections import defaultdict
import statistics

logger = logging.getLogger("nexdesk.performance")


# =============================================================================
# CONFIGURATION
# =============================================================================

# Thresholds for slow operation warnings (in milliseconds)
SLOW_THRESHOLDS = {
    "default": 1000,  # 1 second default
    "llm_inference": 5000,  # LLM calls can be slow
    "rag_retrieval": 2000,  # RAG retrieval
    "embedding": 500,  # Embedding generation
    "database_query": 100,  # DB queries should be fast
    "redis_operation": 50,  # Redis should be very fast
    "transcription": 10000,  # Audio transcription can be slow
    "reranking": 1000,  # Cross-encoder reranking
    "hyde_expansion": 3000,  # HyDE query expansion
}

# Maximum metrics history per operation (for memory management)
MAX_METRICS_HISTORY = 1000


# =============================================================================
# PERFORMANCE METRIC DATA STRUCTURES
# =============================================================================


@dataclass
class TimingMetric:
    """
    Single timing measurement.

    Attributes:
        operation: Name of the operation measured
        duration_ms: Duration in milliseconds
        timestamp: When the measurement was taken
        metadata: Additional context (optional)
        is_slow: Whether operation exceeded threshold
    """

    operation: str
    duration_ms: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_slow: bool = False


@dataclass
class OperationStats:
    """
    Aggregated statistics for an operation.

    Attributes:
        operation: Name of the operation
        count: Total number of measurements
        total_ms: Total time spent (ms)
        min_ms: Minimum duration (ms)
        max_ms: Maximum duration (ms)
        avg_ms: Average duration (ms)
        p50_ms: 50th percentile (median)
        p95_ms: 95th percentile
        p99_ms: 99th percentile
        slow_count: Number of operations that exceeded threshold
        last_measured: When the last measurement was taken
    """

    operation: str
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    slow_count: int = 0
    last_measured: Optional[datetime] = None


# =============================================================================
# PERFORMANCE MONITOR SINGLETON
# =============================================================================


class PerformanceMonitor:
    """
    Centralized performance monitoring for NexDesk.

    Singleton class that collects and aggregates performance metrics
    across the application.

    Usage:
        # Record a timing
        PerformanceMonitor.record("rag_retrieval", 150.5, {"query": "password reset"})

        # Use context manager
        with PerformanceMonitor.timer("database_query") as t:
            result = db.query(...)
        print(f"Query took {t.duration_ms}ms")

        # Get statistics
        stats = PerformanceMonitor.get_stats("rag_retrieval")
    """

    _instance = None
    _metrics: Dict[str, List[TimingMetric]] = defaultdict(list)
    _enabled: bool = True

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def enable(cls):
        """Enable performance monitoring."""
        cls._enabled = True
        logger.info("Performance monitoring enabled")

    @classmethod
    def disable(cls):
        """Disable performance monitoring (for production optimization)."""
        cls._enabled = False
        logger.info("Performance monitoring disabled")

    @classmethod
    def record(
        cls,
        operation: str,
        duration_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Record a timing measurement.

        Args:
            operation: Name of the operation (e.g., "rag_retrieval")
            duration_ms: Duration in milliseconds
            metadata: Additional context to store with the metric
        """
        if not cls._enabled:
            return

        # Check if slow
        threshold = SLOW_THRESHOLDS.get(operation, SLOW_THRESHOLDS["default"])
        is_slow = duration_ms > threshold

        metric = TimingMetric(
            operation=operation,
            duration_ms=duration_ms,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
            is_slow=is_slow,
        )

        # Store metric
        cls._metrics[operation].append(metric)

        # Trim history if needed
        if len(cls._metrics[operation]) > MAX_METRICS_HISTORY:
            cls._metrics[operation] = cls._metrics[operation][-MAX_METRICS_HISTORY:]

        # Log slow operations
        if is_slow:
            logger.warning(
                f"SLOW OPERATION: {operation} took {duration_ms:.2f}ms "
                f"(threshold: {threshold}ms)",
                extra={"metadata": metadata},
            )
        else:
            logger.debug(f"Timing: {operation} = {duration_ms:.2f}ms")

    @classmethod
    @contextmanager
    def timer(cls, operation: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Context manager for timing operations.

        Usage:
            with PerformanceMonitor.timer("rag_retrieval", {"query": q}) as t:
                result = retrieve(q)
            # t.duration_ms contains the timing

        Args:
            operation: Name of the operation
            metadata: Additional context

        Yields:
            TimingContext with duration_ms attribute
        """

        class TimingContext:
            def __init__(self):
                self.start_time = time.perf_counter()
                self.duration_ms = 0.0

        ctx = TimingContext()
        try:
            yield ctx
        finally:
            ctx.duration_ms = (time.perf_counter() - ctx.start_time) * 1000
            cls.record(operation, ctx.duration_ms, metadata)

    @classmethod
    def get_stats(cls, operation: str) -> OperationStats:
        """
        Get aggregated statistics for an operation.

        Args:
            operation: Name of the operation

        Returns:
            OperationStats with count, avg, p50, p95, p99, etc.
        """
        metrics = cls._metrics.get(operation, [])

        if not metrics:
            return OperationStats(operation=operation)

        durations = [m.duration_ms for m in metrics]
        sorted_durations = sorted(durations)

        def percentile(data, p):
            if not data:
                return 0.0
            k = (len(data) - 1) * (p / 100)
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            return data[f] + (k - f) * (data[c] - data[f]) if f != c else data[f]

        return OperationStats(
            operation=operation,
            count=len(metrics),
            total_ms=sum(durations),
            min_ms=min(durations),
            max_ms=max(durations),
            avg_ms=statistics.mean(durations),
            p50_ms=percentile(sorted_durations, 50),
            p95_ms=percentile(sorted_durations, 95),
            p99_ms=percentile(sorted_durations, 99),
            slow_count=sum(1 for m in metrics if m.is_slow),
            last_measured=metrics[-1].timestamp if metrics else None,
        )

    @classmethod
    def get_all_stats(cls) -> Dict[str, OperationStats]:
        """
        Get statistics for all tracked operations.

        Returns:
            Dictionary mapping operation names to their stats
        """
        return {op: cls.get_stats(op) for op in cls._metrics.keys()}

    @classmethod
    def get_recent_metrics(
        cls, operation: Optional[str] = None, minutes: int = 5
    ) -> List[TimingMetric]:
        """
        Get metrics from the last N minutes.

        Args:
            operation: Filter by operation (None = all)
            minutes: How far back to look

        Returns:
            List of TimingMetric objects
        """
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)

        if operation:
            metrics = cls._metrics.get(operation, [])
        else:
            metrics = [m for ops in cls._metrics.values() for m in ops]

        return [m for m in metrics if m.timestamp > cutoff]

    @classmethod
    def get_slow_operations(cls, minutes: int = 5) -> List[TimingMetric]:
        """
        Get all slow operations from the last N minutes.

        Args:
            minutes: How far back to look

        Returns:
            List of slow TimingMetric objects
        """
        return [m for m in cls.get_recent_metrics(minutes=minutes) if m.is_slow]

    @classmethod
    def clear(cls, operation: Optional[str] = None):
        """
        Clear stored metrics.

        Args:
            operation: Clear specific operation (None = clear all)
        """
        if operation:
            cls._metrics[operation] = []
        else:
            cls._metrics = defaultdict(list)
        logger.info(f"Cleared metrics: {operation or 'all'}")

    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        """
        Export all stats as a dictionary (for API responses).

        Returns:
            Dictionary with all statistics
        """
        all_stats = cls.get_all_stats()
        recent_slow = cls.get_slow_operations(minutes=5)

        return {
            "operations": {
                op: {
                    "count": stats.count,
                    "avg_ms": round(stats.avg_ms, 2),
                    "min_ms": round(stats.min_ms, 2),
                    "max_ms": round(stats.max_ms, 2),
                    "p50_ms": round(stats.p50_ms, 2),
                    "p95_ms": round(stats.p95_ms, 2),
                    "p99_ms": round(stats.p99_ms, 2),
                    "slow_count": stats.slow_count,
                    "last_measured": stats.last_measured.isoformat()
                    if stats.last_measured
                    else None,
                }
                for op, stats in all_stats.items()
            },
            "slow_operations_last_5min": len(recent_slow),
            "slow_operations_details": [
                {
                    "operation": m.operation,
                    "duration_ms": round(m.duration_ms, 2),
                    "timestamp": m.timestamp.isoformat(),
                    "metadata": m.metadata,
                }
                for m in recent_slow[:10]  # Limit to 10 most recent
            ],
            "generated_at": datetime.utcnow().isoformat(),
        }


# =============================================================================
# DECORATOR FOR AUTOMATIC TIMING
# =============================================================================


def track_time(
    operation: str, include_args: bool = False, arg_names: Optional[List[str]] = None
):
    """
    Decorator to automatically track function execution time.

    Usage:
        @track_time("rag_retrieval")
        def retrieve(query: str):
            ...

        @track_time("classify_ticket", include_args=True, arg_names=["title"])
        def classify(title: str, description: str):
            ...

    Args:
        operation: Name for this operation in metrics
        include_args: Whether to include function args in metadata
        arg_names: Specific argument names to include (None = all)
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            metadata = {}
            if include_args:
                # Get function parameter names
                import inspect

                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())

                # Build metadata from args
                for i, arg in enumerate(args):
                    if i < len(param_names):
                        name = param_names[i]
                        if arg_names is None or name in arg_names:
                            metadata[name] = str(arg)[:100]  # Truncate long values

                # Add kwargs
                for key, value in kwargs.items():
                    if arg_names is None or key in arg_names:
                        metadata[key] = str(value)[:100]

            with PerformanceMonitor.timer(operation, metadata):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            metadata = {}
            if include_args:
                import inspect

                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())

                for i, arg in enumerate(args):
                    if i < len(param_names):
                        name = param_names[i]
                        if arg_names is None or name in arg_names:
                            metadata[name] = str(arg)[:100]

                for key, value in kwargs.items():
                    if arg_names is None or key in arg_names:
                        metadata[key] = str(value)[:100]

            with PerformanceMonitor.timer(operation, metadata):
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def record_metric(operation: str, duration_ms: float, metadata: Optional[Dict] = None):
    """
    Record a timing metric (convenience function).

    Args:
        operation: Name of the operation
        duration_ms: Duration in milliseconds
        metadata: Additional context
    """
    PerformanceMonitor.record(operation, duration_ms, metadata)


def get_metrics() -> Dict[str, Any]:
    """
    Get all performance metrics (convenience function).

    Returns:
        Dictionary with all statistics
    """
    return PerformanceMonitor.to_dict()


def time_function(func: Callable) -> tuple:
    """
    Execute a function and return (result, duration_ms).

    Usage:
        result, duration = time_function(lambda: expensive_operation())

    Args:
        func: Callable to execute

    Returns:
        Tuple of (result, duration_ms)
    """
    start = time.perf_counter()
    result = func()
    duration = (time.perf_counter() - start) * 1000
    return result, duration


async def time_async_function(coro) -> tuple:
    """
    Execute a coroutine and return (result, duration_ms).

    Usage:
        result, duration = await time_async_function(async_operation())

    Args:
        coro: Coroutine to execute

    Returns:
        Tuple of (result, duration_ms)
    """
    start = time.perf_counter()
    result = await coro
    duration = (time.perf_counter() - start) * 1000
    return result, duration


# =============================================================================
# FASTAPI MIDDLEWARE FOR REQUEST TIMING
# =============================================================================


class PerformanceMiddleware:
    """
    FastAPI middleware to track request/response timing.

    Usage in main.py:
        from utils.performance import PerformanceMiddleware

        app.add_middleware(PerformanceMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()

        # Extract path for operation name
        path = scope.get("path", "/unknown")
        method = scope.get("method", "GET")
        operation = f"http_{method.lower()}_{path.replace('/', '_').strip('_')}"

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Record timing when response starts
                duration_ms = (time.perf_counter() - start_time) * 1000
                status = message.get("status", 0)

                PerformanceMonitor.record(
                    "http_request",
                    duration_ms,
                    {"path": path, "method": method, "status": status},
                )

                # Also record specific endpoint timing
                PerformanceMonitor.record(operation, duration_ms, {"status": status})

            await send(message)

        await self.app(scope, receive, send_wrapper)


# =============================================================================
# PERFORMANCE REPORT GENERATION
# =============================================================================


def generate_performance_report() -> str:
    """
    Generate a human-readable performance report.

    Returns:
        Formatted string with performance statistics
    """
    stats = PerformanceMonitor.get_all_stats()
    slow_ops = PerformanceMonitor.get_slow_operations(minutes=60)

    lines = [
        "=" * 60,
        "NexDesk Performance Report",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "=" * 60,
        "",
        "OPERATION STATISTICS",
        "-" * 60,
    ]

    if not stats:
        lines.append("No metrics recorded yet.")
    else:
        # Sort by total time (most time-consuming first)
        sorted_stats = sorted(stats.values(), key=lambda s: s.total_ms, reverse=True)

        for s in sorted_stats:
            lines.extend(
                [
                    f"\n{s.operation}:",
                    f"  Count:     {s.count}",
                    f"  Total:     {s.total_ms:.2f}ms",
                    f"  Average:   {s.avg_ms:.2f}ms",
                    f"  Min/Max:   {s.min_ms:.2f}ms / {s.max_ms:.2f}ms",
                    f"  P50/P95:   {s.p50_ms:.2f}ms / {s.p95_ms:.2f}ms",
                    f"  P99:       {s.p99_ms:.2f}ms",
                    f"  Slow:      {s.slow_count} ({(s.slow_count / s.count * 100):.1f}%)"
                    if s.count > 0
                    else "  Slow:      0",
                ]
            )

    lines.extend(
        [
            "",
            "SLOW OPERATIONS (Last 60 minutes)",
            "-" * 60,
        ]
    )

    if not slow_ops:
        lines.append("No slow operations detected.")
    else:
        for op in slow_ops[:20]:  # Show top 20
            lines.append(
                f"  [{op.timestamp.strftime('%H:%M:%S')}] {op.operation}: "
                f"{op.duration_ms:.2f}ms"
            )
        if len(slow_ops) > 20:
            lines.append(f"  ... and {len(slow_ops) - 20} more")

    lines.extend(["", "=" * 60])

    return "\n".join(lines)
