"""
Health Check Routes
Endpoints for monitoring application health
"""
from fastapi import APIRouter, HTTPException
from app.models.api import HealthResponse
from app.config import settings
from app.services.db import health_check as db_health_check, SessionLocal
from app.services.message_poller import get_message_poller
from sqlalchemy import text
from datetime import datetime

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for monitoring.
    Returns status and version information including database health.
    
    NOTE: This endpoint is intentionally unauthenticated to allow monitoring tools
    (e.g., load balancers, health check services) to verify service availability.
    No sensitive data is returned.
    """
    # Check database health
    db_health = db_health_check()
    
    # Determine overall status
    overall_status = "ok"
    if db_health.get("status") != "healthy":
        overall_status = "degraded"
    
    return HealthResponse(
        status=overall_status, 
        version="1.0.0",
        details={
            "authentication": "Azure AD SSO",
            "frontend_integration": "Direct Azure AD token validation",
            "auth_mode": "Stateless token validation",
            "database": db_health
        }
    )


@router.get("/health/poller")
async def poller_health():
    """
    Health check endpoint for message poller.
    Returns poller status and configuration.
    
    NOTE: This endpoint is intentionally unauthenticated to allow monitoring tools
    to check poller health without authentication.
    """
    poller = get_message_poller()
    
    return {
        "status": "healthy" if poller.is_running else "stopped",
        "poller_running": poller.is_running,
        "poller_enabled": settings.message_poller_enabled,
        "is_leader": poller.leader.is_leader if poller else False,
        "worker_id": poller.worker_id if poller else None
    }


@router.get("/api/pending-actions")
async def get_pending_actions():
    """
    Get pending action counts for navbar badges.
    Returns counts for support tickets and P2P calls.
    
    NOTE: This endpoint is intentionally unauthenticated to allow the frontend
    to display badge counts in the navbar without requiring full authentication
    context. The endpoint returns only aggregate counts (numbers), no sensitive data.
    """
    # Import here to avoid circular imports
    from app.routes.operations import get_operations_pending_counts
    return get_operations_pending_counts()



## Removed /api/dev/reset-mock-data endpoint: All data is now managed via the database. Use DB seeding or test fixtures for resets.
