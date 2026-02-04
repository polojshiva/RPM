"""
SQLAlchemy session and engine setup for PostgreSQL (service_ops schema)
Production-ready with connection pooling, pre-ping, and proper error handling
"""
import logging
import os
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import DisconnectionError, OperationalError
from dotenv import load_dotenv

from app.config import settings

# Load .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Get DATABASE_URL from environment or settings
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/wiser_ops")

# Production-ready engine configuration
# Log pool configuration on startup
logger.info(
    f"Database connection pool configuration: "
    f"pool_size={settings.db_pool_size}, "
    f"max_overflow={settings.db_max_overflow}, "
    f"total_max={settings.db_pool_size + settings.db_max_overflow} connections"
)

engine = create_engine(
    DATABASE_URL,
    # Connection Pool Settings
    pool_size=settings.db_pool_size,  # Number of connections to maintain
    max_overflow=settings.db_max_overflow,  # Max connections beyond pool_size
    pool_timeout=settings.db_pool_timeout,  # Seconds to wait for connection
    pool_recycle=settings.db_pool_recycle,  # Recycle connections after this many seconds
    pool_pre_ping=settings.db_pool_pre_ping,  # Verify connections before using
    
    # Connection Settings
    connect_args={
        "connect_timeout": settings.db_connect_args_connect_timeout,
        "options": "-c statement_timeout=30000"  # 30 second statement timeout
    },
    
    # Performance Settings
    echo=settings.db_echo,  # Log SQL (disable in production)
    echo_pool=settings.db_echo,  # Log pool events
    
    # Connection Pool Class
    poolclass=pool.QueuePool,  # Use QueuePool for better connection management
    
    # Additional safety settings
    future=True,  # Use SQLAlchemy 2.0 style
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # Prevent lazy loading issues after commit
)


@event.listens_for(Engine, "connect")
def set_postgresql_settings(dbapi_conn, connection_record):
    """
    Set connection-level settings for PostgreSQL when a new connection is established.
    This ensures all connections have proper timeouts configured.
    """
    try:
        with dbapi_conn.cursor() as cursor:
            cursor.execute("SET statement_timeout = '30s'")
            cursor.execute("SET idle_in_transaction_session_timeout = '60s'")
        logger.debug("PostgreSQL connection settings configured")
    except Exception as e:
        # Log but don't fail - connection might still be usable
        logger.warning(f"Failed to set PostgreSQL connection settings: {e}")


@event.listens_for(Engine, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """
    Handle connection checkout from pool.
    pool_pre_ping=True ensures connection is alive before checkout.
    """
    logger.debug("Connection checked out from pool")


@event.listens_for(Engine, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    """
    Handle connection checkin to pool.
    
    When returning a connection, SQLAlchemy tries to reset it (rollback).
    If the connection was closed by the database server, this will fail.
    pool_pre_ping=True will catch dead connections on next checkout, so we
    can safely ignore reset errors here.
    """
    try:
        logger.debug("Connection returned to pool")
    except Exception as e:
        # Ignore errors during checkin - these are expected when DB closes connections
        # pool_pre_ping will verify and replace dead connections on next checkout
        error_msg = str(e).lower()
        if "server closed" in error_msg or "connection unexpectedly" in error_msg:
            logger.debug(f"Connection reset failed (expected): {type(e).__name__}")
        else:
            logger.debug(f"Connection checkin error (will be handled by pool_pre_ping): {type(e).__name__}")


@event.listens_for(Engine, "invalidate")
def receive_invalidate(dbapi_conn, connection_record, exception):
    """
    Handle connection invalidation.
    
    This is called when a connection is detected as dead/invalid.
    Common causes:
    - Database server closed idle connection (expected behavior)
    - Network timeout
    - Database server restart
    
    With pool_pre_ping=True, SQLAlchemy will catch dead connections
    before use, so these warnings are mostly informational.
    """
    error_msg = str(exception).lower()
    
    # Don't log as error for expected cases (server closed connection)
    # These are normal when database closes idle connections
    if "server closed the connection" in error_msg or "connection unexpectedly" in error_msg:
        logger.debug(
            f"Connection closed by database server (expected): {type(exception).__name__}"
        )
    elif "ssl connection has been closed" in error_msg:
        logger.debug(
            f"SSL connection closed (expected): {type(exception).__name__}"
        )
    else:
        # Log as warning for unexpected errors
        logger.warning(
            f"Connection invalidated: {exception}",
            exc_info=exception
        )


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI routes to get database session.
    Properly handles session lifecycle, cleanup, and connection errors.
    
    Features:
    - Automatic rollback on exceptions
    - Graceful handling of connection errors
    - Proper session cleanup
    
    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db: Session = None
    try:
        db = SessionLocal()
        yield db
    except (OperationalError, DisconnectionError) as e:
        # Handle connection errors gracefully
        error_msg = str(e).lower()
        if db:
            try:
                db.rollback()
            except Exception:
                # Ignore rollback errors on dead connections
                pass
        
        # Check if it's a transient connection error
        if "server closed" in error_msg or "connection unexpectedly" in error_msg:
            logger.warning(
                f"Database connection error (transient): {type(e).__name__}. "
                "Connection pool will replace dead connection."
            )
        else:
            logger.error(f"Database connection error: {e}", exc_info=True)
        
        # Re-raise to let FastAPI handle it (will return 500)
        raise
    except Exception as e:
        # Don't rollback on HTTPException - FastAPI will handle it
        from fastapi import HTTPException
        if isinstance(e, HTTPException):
            # HTTPException should propagate without rollback
            raise
        
        # Rollback on any other exception
        if db:
            try:
                db.rollback()
            except Exception as rollback_error:
                logger.warning(
                    f"Failed to rollback session: {rollback_error}. "
                    "Connection may be dead."
                )
        
        logger.error(f"Database session error: {e}", exc_info=True)
        raise
    finally:
        # Always close the session
        if db:
            try:
                db.close()
            except Exception as close_error:
                # Log but don't raise - session cleanup errors shouldn't break the app
                logger.debug(f"Error closing session (non-critical): {close_error}")


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions (for use outside FastAPI routes).
    Handles connection errors gracefully with automatic retry for transient errors.
    
    Features:
    - Automatic commit on success
    - Automatic rollback on error
    - Graceful handling of connection errors
    - Proper session cleanup
    
    Usage:
        with get_db_session() as db:
            items = db.query(Item).all()
    """
    db: Session = None
    try:
        db = SessionLocal()
        yield db
        # Commit on successful completion
        try:
            db.commit()
        except (OperationalError, DisconnectionError) as commit_error:
            # If commit fails due to connection error, rollback and re-raise
            error_msg = str(commit_error).lower()
            if "server closed" in error_msg or "connection unexpectedly" in error_msg:
                logger.warning(
                    f"Connection error during commit (transient): {type(commit_error).__name__}"
                )
            try:
                db.rollback()
            except Exception:
                pass
            raise
    except (OperationalError, DisconnectionError) as e:
        # Handle connection errors gracefully
        error_msg = str(e).lower()
        if db:
            try:
                db.rollback()
            except Exception:
                # Ignore rollback errors on dead connections
                pass
        
        if "server closed" in error_msg or "connection unexpectedly" in error_msg:
            logger.warning(
                f"Database connection error (transient): {type(e).__name__}. "
                "Connection pool will replace dead connection."
            )
        else:
            logger.error(f"Database connection error: {e}", exc_info=True)
        raise
    except Exception as e:
        # Rollback on any other exception
        if db:
            try:
                db.rollback()
            except Exception as rollback_error:
                logger.warning(
                    f"Failed to rollback session: {rollback_error}. "
                    "Connection may be dead."
                )
        logger.error(f"Database session error: {e}", exc_info=True)
        raise
    finally:
        # Always close the session
        if db:
            try:
                db.close()
            except Exception as close_error:
                # Log but don't raise - session cleanup errors shouldn't break the app
                logger.debug(f"Error closing session (non-critical): {close_error}")


def test_connection() -> bool:
    """
    Test database connection health with retry logic for transient errors.
    
    Returns:
        True if connection is healthy, False otherwise
    """
    max_retries = 2
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                # Execute simple query to test connection
                result = conn.execute(text("SELECT 1"))
                result.fetchone()  # Consume result
                # Connection context manager handles commit/rollback automatically
            logger.info("Database connection test: SUCCESS")
            return True
        except (OperationalError, DisconnectionError) as e:
            error_msg = str(e).lower()
            is_transient = (
                "server closed" in error_msg or
                "connection unexpectedly" in error_msg or
                "ssl connection has been closed" in error_msg
            )
            
            if is_transient and attempt < max_retries - 1:
                # Retry transient connection errors
                logger.debug(
                    f"Database connection test failed (transient, attempt {attempt + 1}/{max_retries}): {e}"
                )
                continue
            else:
                logger.error(f"Database connection test: FAILED - {e}", exc_info=True)
                return False
        except Exception as e:
            logger.error(f"Database connection test: FAILED - {e}", exc_info=True)
            return False
    
    return False


def get_pool_status() -> dict:
    """
    Get connection pool status for monitoring.
    
    Returns:
        Dict with pool statistics
    """
    pool_obj = engine.pool
    try:
        # Get pool statistics using available methods
        status = {
            "pool_size": pool_obj.size(),
            "checked_in": pool_obj.checkedin(),
            "checked_out": pool_obj.checkedout(),
            "overflow": pool_obj.overflow(),
        }
        # Try to get max_overflow if available
        if hasattr(pool_obj, '_max_overflow'):
            status["max_overflow"] = pool_obj._max_overflow
        return status
    except (AttributeError, TypeError) as e:
        # Fallback for pools that don't support all methods
        logger.warning(f"Could not get full pool status: {e}")
        return {
            "pool_size": getattr(pool_obj, '_pool_size', None),
            "checked_in": getattr(pool_obj, 'checkedin', lambda: 0)(),
            "checked_out": getattr(pool_obj, 'checkedout', lambda: 0)(),
            "overflow": getattr(pool_obj, 'overflow', lambda: 0)(),
        }


def close_all_connections():
    """
    Close all connections in the pool.
    Use this during application shutdown.
    """
    logger.info("Closing all database connections")
    engine.dispose()


# Health check function for monitoring
def health_check() -> dict:
    """
    Comprehensive database health check.
    
    Returns:
        Dict with health status and pool information
    """
    try:
        is_healthy = test_connection()
        pool_status = get_pool_status()
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "connection_test": is_healthy,
            "pool": pool_status,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }
