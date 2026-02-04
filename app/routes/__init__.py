"""Routes module"""
from .auth import router as auth_router
from .packets import router as packets_router
from .health import router as health_router
from .operations import router as operations_router

__all__ = ["auth_router", "packets_router", "health_router", "operations_router"]
