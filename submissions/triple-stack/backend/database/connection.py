"""
Database connection module - PostgreSQL only (production-ready).

This module provides:
- Async and sync database sessions
- Connection pooling for PostgreSQL
- Health check utilities
- Automatic table creation

Environment Variables:
- DATABASE_URL: PostgreSQL connection string (required)
  Format: postgresql://user:password@host:port/database

Note: SQLite support has been removed for production readiness.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from .models import Base
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# PostgreSQL connection - required for production
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL environment variable is required. "
        "Example: postgresql://user:password@localhost:5432/nexdesk"
    )

is_sqlite = DATABASE_URL.startswith("sqlite")
POOL_SIZE = 0

if is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=os.getenv("DB_ECHO", "false").lower() == "true",
    )
else:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
    MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))

    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT,
        pool_recycle=POOL_RECYCLE,
        pool_pre_ping=True,
        echo=os.getenv("DB_ECHO", "false").lower() == "true",
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables():
    """Create all database tables if they don't exist."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise


def get_db():
    """
    Dependency that provides a database session.

    Usage:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_health() -> dict:
    """
    Check database connection health.

    Returns:
        dict with status, latency_ms, and pool_info
    """
    import time

    try:
        start = time.time()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.commit()
        latency_ms = int((time.time() - start) * 1000)

        pool = engine.pool
        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "database_type": "postgresql",
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "database_type": "postgresql"}


def get_pool_status() -> dict:
    """Get current connection pool status."""
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "max_overflow": MAX_OVERFLOW,
        "pool_timeout": POOL_TIMEOUT,
        "pool_recycle": POOL_RECYCLE,
    }


# Log connection info on module load (without sensitive data)
_db_host = (
    DATABASE_URL.split("@")[-1].split("/")[0] if "@" in DATABASE_URL else "unknown"
)
logger.info(f"Database configured: {'SQLite' if is_sqlite else 'PostgreSQL'} @ {_db_host} (pool_size={POOL_SIZE})")
