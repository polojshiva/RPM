"""
WISeR Packet Dashboard Backend - FastAPI Application
Main entry point for the application
"""
import uuid
import sys
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from app.config import settings
from app.routes import auth_router, packets_router, health_router, operations_router
from app.routes.letters import router as letters_router
from app.routes.clinical import router as clinical_router
from app.routes.outbound import router as outbound_router
from app.routes.pending_actions import router as pending_actions_router
from app.routes.documents import router as documents_router
from app.routes.validations import router as validations_router
from app.routes.decisions import router as decisions_router
from app.routes.diagnostics import router as diagnostics_router
from app.utils.phi_masking import mask_error_message
from app.services.message_poller import get_message_poller
from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor
from app.services.db import test_connection, close_all_connections, get_pool_status


# Configure logging
# Explicitly write to stdout so Azure App Service can capture logs in log stream
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup - DB seeding or migrations should be handled externally. No mock data initialization.
    logger.info(f"Starting WISeR Service Operations Backend on port {settings.port}")
    logger.info(f"Environment: {settings.env}")
    logger.info(f"CORS Origins: {settings.cors_origins_list}")
    logger.info("Azure AD SSO Integration: ENABLED")
    logger.info("Frontend Integration: Direct Azure AD token validation")
    logger.info("No login/refresh/logout endpoints - MSAL handles authentication")
    
    # CRITICAL: Validate Azure AD configuration on startup (fail fast)
    from app.auth.azure_jwt import AZURE_TENANT_ID, AZURE_CLIENT_ID, _fetch_jwks
    if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
        logger.error(
            "CRITICAL: Azure AD configuration missing! "
            "AZURE_TENANT_ID and AZURE_CLIENT_ID must be set in environment variables. "
            "Authentication will fail. Please set these in Azure App Service Configuration."
        )
        # Don't fail startup - let it run but log error clearly
        # This allows health checks to work even if auth is misconfigured
    else:
        logger.info(
            f"Azure AD configuration validated: "
            f"Tenant={AZURE_TENANT_ID[:8]}..., "
            f"Client={AZURE_CLIENT_ID[:8]}..."
        )
        
        # PRE-WARM JWKS cache on startup to avoid first-request delay
        # This ensures JWKS keys are cached before first auth request
        try:
            logger.info("Pre-warming JWKS cache for faster authentication...")
            # In lifespan context, we can await directly
            await _fetch_jwks()
            logger.info("JWKS pre-warm completed (keys cached for 24 hours)")
        except Exception as e:
            logger.warning(f"Failed to pre-warm JWKS cache: {e}. First auth request may be slower.")
    
    # Test database connection on startup
    logger.info("Testing database connection...")
    if test_connection():
        pool_status = get_pool_status()
        logger.info(
            f"Database connection pool initialized: "
            f"pool_size={pool_status['pool_size']}, "
            f"checked_in={pool_status['checked_in']}"
        )
    else:
        logger.error("Database connection test failed - application may not function correctly")
    
    # Start message poller
    message_poller = None
    if settings.message_poller_enabled:
        message_poller = get_message_poller()
        try:
            await message_poller.start()
            
            if message_poller.is_running:
                logger.info("✅ Message poller started successfully")
            else:
                logger.warning("⚠️ Message poller did not start")
        except Exception as e:
            logger.error(f"CRITICAL: Failed to start message poller: {e}", exc_info=True)
            # Don't fail startup, but log clearly
    else:
        logger.info("Message poller is disabled")
    
    # Start ClinicalOps inbox processor
    clinical_ops_processor = None
    if getattr(settings, 'clinical_ops_poller_enabled', True):
        clinical_ops_processor = ClinicalOpsInboxProcessor()
        try:
            await clinical_ops_processor.start()
            
            if clinical_ops_processor.is_running:
                logger.info("✅ ClinicalOps inbox processor started successfully")
            else:
                logger.warning("⚠️ ClinicalOps inbox processor did not start")
        except Exception as e:
            logger.error(f"CRITICAL: Failed to start ClinicalOps inbox processor: {e}", exc_info=True)
            # Don't fail startup, but log clearly
            clinical_ops_processor = None  # Reset to None so shutdown doesn't try to stop it
    else:
        logger.info("ClinicalOps inbox processor is disabled")
    
    yield
    
    # Graceful shutdown
    logger.info("Application shutting down - releasing leadership...")
    
    shutdown_tasks = []
    
    if message_poller:
        shutdown_tasks.append(message_poller.stop())
    
    if clinical_ops_processor:
        shutdown_tasks.append(clinical_ops_processor.stop())
    
    # Wait for all shutdown tasks with timeout
    if shutdown_tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*shutdown_tasks, return_exceptions=True),
                timeout=10.0  # 10 second timeout for graceful shutdown
            )
            logger.info("✅ Graceful shutdown completed")
        except asyncio.TimeoutError:
            logger.warning("⚠️ Shutdown timeout - some services may not have released leadership gracefully")
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}", exc_info=True)
    
    # Close all database connections
    close_all_connections()
    logger.info("Shutting down WISeR Packet Dashboard Backend")


app = FastAPI(
    title="WISeR Packet Dashboard API",
    description="Backend API for WISeR Packet Dashboard - Healthcare packet management system",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# Proxy Headers Middleware - Must be added BEFORE other middleware
# This ensures request.url.scheme respects X-Forwarded-Proto header
# Safe on Azure App Service because it sits behind a trusted proxy
class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to handle X-Forwarded-Proto header for correct URL scheme"""
    async def dispatch(self, request: StarletteRequest, call_next):
        # Check X-Forwarded-Proto header
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        if forwarded_proto == "https":
            # Override the scheme in the request URL
            request.scope["scheme"] = "https"
        
        # Also handle X-Forwarded-Host if present
        forwarded_host = request.headers.get("X-Forwarded-Host")
        if forwarded_host:
            request.scope["server"] = (forwarded_host.split(":")[0], 
                                      int(forwarded_host.split(":")[1]) if ":" in forwarded_host else 
                                      (443 if forwarded_proto == "https" else 80))
        
        response = await call_next(request)
        return response

app.add_middleware(ProxyHeadersMiddleware)

# Request Priority Middleware - MUST be added early to prioritize auth requests
# This ensures login/auth requests are always processed first, even under heavy load
from app.middleware.request_priority import RequestPriorityMiddleware
app.add_middleware(RequestPriorityMiddleware)
logger.info("Request priority middleware enabled - auth requests will be prioritized")


# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "ETag"],
)


# Request ID Middleware
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to all requests for tracing"""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id

    return response


# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    # HSTS in production
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


# Pydantic validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors with user-friendly messages"""
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
    
    # Extract error messages from validation errors
    errors = exc.errors()
    error_messages = []
    for error in errors:
        field = " -> ".join(str(loc) for loc in error.get("loc", []))
        msg = error.get("msg", "Validation error")
        error_messages.append(f"{field}: {msg}")
    
    error_detail = "; ".join(error_messages) if error_messages else "Validation error"
    
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": error_detail,
            "correlation_id": correlation_id,
        },
    )


# HTTP exception handler for standardized responses
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with standardized format"""
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
    
    # Ensure error detail is a string, not an object
    error_detail = str(exc.detail) if exc.detail else "An error occurred"
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": error_detail,
            "correlation_id": correlation_id,
        },
    )


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions with PHI masking"""
    error_message = mask_error_message(str(exc))
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": error_message,
            "correlation_id": correlation_id,
        },
    )


# Include routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(packets_router)
app.include_router(operations_router)
app.include_router(letters_router)
app.include_router(clinical_router)
app.include_router(outbound_router)
app.include_router(pending_actions_router)
app.include_router(documents_router)
app.include_router(validations_router)
app.include_router(decisions_router)
app.include_router(diagnostics_router)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "WISeR Packet Dashboard API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env == "development",
    )
