"""
Request Priority Middleware
Industry-standard request prioritization for FastAPI applications.

This middleware ensures authentication/login requests are processed with higher priority
and have aggressive timeouts to prevent gateway timeouts.

For Gunicorn with multiple workers, this middleware:
- Tracks request priorities for monitoring
- Enforces timeouts per priority level
- Logs slow requests for debugging
- Does NOT queue (Gunicorn workers handle distribution)

Priority Levels:
- CRITICAL: /api/auth/* (login, token validation) - 5s timeout
- HIGH: /api/packets/*, /api/decisions/* (user-facing API) - 30s timeout
- NORMAL: Other API endpoints - 180s timeout
- LOW: Background jobs, long-running operations - 300s timeout
"""
import asyncio
import time
import logging
from typing import Callable
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Priority levels
PRIORITY_CRITICAL = 1  # Auth/login - highest priority
PRIORITY_HIGH = 2      # User-facing API
PRIORITY_NORMAL = 3    # Standard operations
PRIORITY_LOW = 4       # Background jobs

# Request timeout per priority (aggressive for auth, but account for cold JWKS fetch)
TIMEOUT_CRITICAL = 10.0  # Auth must complete in 10 seconds (allows for JWKS fetch on first request)
TIMEOUT_HIGH = 30.0      # User API in 30 seconds
TIMEOUT_NORMAL = 180.0   # Standard in 3 minutes
TIMEOUT_LOW = 300.0      # Background in 5 minutes

# Slow request threshold (log warnings for requests taking longer)
SLOW_REQUEST_THRESHOLD_CRITICAL = 3.0  # Log if auth takes > 3s (allows for JWKS fetch)
SLOW_REQUEST_THRESHOLD_HIGH = 10.0      # Log if API takes > 10s
SLOW_REQUEST_THRESHOLD_NORMAL = 60.0   # Log if normal takes > 60s


def get_request_priority(path: str, method: str) -> tuple[int, float, float]:
    """
    Determine request priority based on path and method.
    
    Args:
        path: Request path
        method: HTTP method
        
    Returns:
        Tuple of (priority_level, timeout_seconds, slow_threshold_seconds)
    """
    path_lower = path.lower()
    
    # CRITICAL: Authentication endpoints - must be fastest
    if path_lower.startswith('/api/auth') or path_lower.startswith('/auth'):
        return (PRIORITY_CRITICAL, TIMEOUT_CRITICAL, SLOW_REQUEST_THRESHOLD_CRITICAL)
    
    # CRITICAL: Health check - needed for load balancer
    if path_lower in ['/health', '/healthz', '/ready', '/live']:
        return (PRIORITY_CRITICAL, TIMEOUT_CRITICAL, SLOW_REQUEST_THRESHOLD_CRITICAL)
    
    # HIGH: User-facing API endpoints
    if path_lower.startswith('/api/packets') or path_lower.startswith('/api/decisions'):
        return (PRIORITY_HIGH, TIMEOUT_HIGH, SLOW_REQUEST_THRESHOLD_HIGH)
    
    # HIGH: Document previews, quick operations
    if path_lower.startswith('/api/documents') and method == 'GET':
        return (PRIORITY_HIGH, TIMEOUT_HIGH, SLOW_REQUEST_THRESHOLD_HIGH)
    
    # NORMAL: Standard API operations
    if path_lower.startswith('/api/'):
        return (PRIORITY_NORMAL, TIMEOUT_NORMAL, SLOW_REQUEST_THRESHOLD_NORMAL)
    
    # LOW: Everything else (background jobs, long operations)
    return (PRIORITY_LOW, TIMEOUT_LOW, 120.0)


class RequestPriorityMiddleware(BaseHTTPMiddleware):
    """
    Middleware that tracks request priorities and enforces timeouts.
    
    For Gunicorn workers, this provides:
    - Priority-based timeout enforcement
    - Slow request detection and logging
    - Request timing statistics
    
    Note: Actual request distribution is handled by Gunicorn workers.
    This middleware ensures auth requests complete quickly and don't timeout.
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        # Statistics for monitoring
        self.stats = {
            'critical_requests': 0,
            'high_requests': 0,
            'normal_requests': 0,
            'low_requests': 0,
            'timeouts': 0,
            'slow_requests': 0,
        }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with priority-based timeout enforcement.
        
        Critical requests (auth) have aggressive 5s timeout.
        Other requests have appropriate timeouts for their operation type.
        """
        path = request.url.path
        method = request.method
        priority, timeout, slow_threshold = get_request_priority(path, method)
        
        # Track request start time
        start_time = time.time()
        
        # Update statistics
        if priority == PRIORITY_CRITICAL:
            self.stats['critical_requests'] += 1
            logger.debug(f"CRITICAL priority request: {method} {path}")
        elif priority == PRIORITY_HIGH:
            self.stats['high_requests'] += 1
        elif priority == PRIORITY_NORMAL:
            self.stats['normal_requests'] += 1
        else:
            self.stats['low_requests'] += 1
        
        try:
            # Process request with priority-based timeout
            response = await asyncio.wait_for(
                call_next(request),
                timeout=timeout
            )
            
            # Calculate request duration
            duration = time.time() - start_time
            
            # Log slow requests (for monitoring)
            if duration > slow_threshold:
                self.stats['slow_requests'] += 1
                logger.warning(
                    f"Slow {['CRITICAL', 'HIGH', 'NORMAL', 'LOW'][priority-1]} request: "
                    f"{method} {path} took {duration:.2f}s (threshold: {slow_threshold}s)"
                )
            elif priority == PRIORITY_CRITICAL and duration > 1.0:
                # Log any auth request taking > 1s (should be < 1s normally)
                logger.info(
                    f"Auth request took {duration:.2f}s: {method} {path}"
                )
            
            return response
            
        except asyncio.TimeoutError:
            self.stats['timeouts'] += 1
            duration = time.time() - start_time
            logger.error(
                f"Request timeout ({timeout}s): {method} {path} "
                f"(priority={['CRITICAL', 'HIGH', 'NORMAL', 'LOW'][priority-1]}, "
                f"duration={duration:.2f}s)"
            )
            raise HTTPException(
                status_code=504,
                detail=f"Request timeout after {timeout} seconds"
            )
        except HTTPException:
            # Re-raise HTTP exceptions (they're intentional)
            raise
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Error processing {['CRITICAL', 'HIGH', 'NORMAL', 'LOW'][priority-1]} "
                f"request ({duration:.2f}s): {method} {path} - {e}",
                exc_info=True
            )
            raise
