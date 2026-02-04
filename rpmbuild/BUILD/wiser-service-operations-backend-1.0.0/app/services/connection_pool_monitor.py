"""
Connection Pool Monitor
Monitors database connection pool usage and provides backpressure signals
to background processes when pool is exhausted.
"""
import logging
from sqlalchemy import inspect
from app.services.db import engine

logger = logging.getLogger(__name__)

# Thresholds for connection pool health
POOL_WARNING_THRESHOLD = 0.7  # Warn when 70% of pool is in use
POOL_CRITICAL_THRESHOLD = 0.95  # Critical when 95% of pool is in use (less aggressive - was 90%)
POOL_RESERVED_FOR_AUTH = 20  # Reserve 20 connections for auth requests


def get_pool_usage() -> dict:
    """
    Get current connection pool usage statistics.
    
    Returns:
        Dictionary with pool_size, checked_in, checked_out, usage_percent, status
    """
    pool = engine.pool
    pool_size = pool.size()
    checked_in = pool.checkedin()
    checked_out = pool.checkedout()
    total_connections = pool_size + (checked_out - checked_in)  # Includes overflow
    
    usage_percent = (checked_out / total_connections) if total_connections > 0 else 0.0
    
    # Determine status
    if usage_percent >= POOL_CRITICAL_THRESHOLD:
        status = "CRITICAL"
    elif usage_percent >= POOL_WARNING_THRESHOLD:
        status = "WARNING"
    else:
        status = "HEALTHY"
    
    return {
        "pool_size": pool_size,
        "checked_in": checked_in,
        "checked_out": checked_out,
        "total_connections": total_connections,
        "usage_percent": usage_percent,
        "status": status,
        "available_for_background": max(0, total_connections - POOL_RESERVED_FOR_AUTH - checked_out)
    }


def should_throttle_background() -> bool:
    """
    Check if background processes should be throttled.
    
    Returns:
        True if pool usage is above critical threshold (should throttle)
    """
    usage = get_pool_usage()
    return usage["status"] == "CRITICAL" or usage["available_for_background"] <= 0


def log_pool_status():
    """Log current pool status for monitoring"""
    usage = get_pool_usage()
    if usage["status"] == "CRITICAL":
        logger.warning(
            f"Connection pool CRITICAL: {usage['checked_out']}/{usage['total_connections']} "
            f"({usage['usage_percent']:.1%}) in use. Background processes should throttle."
        )
    elif usage["status"] == "WARNING":
        logger.info(
            f"Connection pool WARNING: {usage['checked_out']}/{usage['total_connections']} "
            f"({usage['usage_percent']:.1%}) in use."
        )
