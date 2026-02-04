"""
API Response Models
Generic response models for consistent API responses
"""
from typing import TypeVar, Generic, Optional
from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Generic API response wrapper"""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    message: Optional[str] = None
    validation_run_id: Optional[int] = None  # For validation endpoints
    correlation_id: Optional[str] = None  # For tracing
    validation_status: Optional[str] = None  # For validation endpoints: Validation Complete, Validation Failed, etc.
    is_passed: Optional[bool] = None  # For validation endpoints: True if validation passed
    validated_by: Optional[str] = None  # User who performed validation


class PaginationParams(BaseModel):
    """Pagination parameters"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)
    sort_by: Optional[str] = None
    sort_order: str = Field(default="asc", pattern="^(asc|desc)$")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = "ok"
    version: str = "1.0.0"
    details: Optional[dict] = None


class PendingActionsResponse(BaseModel):
    """Pending actions count for navbar badges"""
    model_config = ConfigDict(populate_by_name=True)

    support_tickets_pending: int = Field(default=0, serialization_alias="supportTicketsPending")
    p2p_calls_new: int = Field(default=0, serialization_alias="p2pCallsNew")
