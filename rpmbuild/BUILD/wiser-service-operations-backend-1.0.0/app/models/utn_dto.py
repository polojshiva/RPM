"""
UTN DTOs for API responses
"""
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class UtnFailDetailsDTO(BaseModel):
    """UTN_FAIL details for a packet"""
    packet_id: str = Field(..., description="Packet external ID")
    decision_tracking_id: str = Field(..., description="Decision tracking ID")
    requires_utn_fix: bool = Field(..., description="Flag indicating UTN_FAIL requires remediation")
    utn_status: Optional[str] = Field(None, description="UTN status: NONE, SUCCESS, FAILED")
    utn_received_at: Optional[datetime] = Field(None, description="When UTN_FAIL was received")
    error_code: Optional[str] = Field(None, description="Error code from UTN_FAIL payload")
    error_description: Optional[str] = Field(None, description="Error description from UTN_FAIL payload")
    action_required: Optional[str] = Field(None, description="Action required message from UTN_FAIL payload")
    utn_fail_payload: Optional[Dict[str, Any]] = Field(None, description="Full UTN_FAIL payload for debugging")
    esmd_request_status: Optional[str] = Field(None, description="ESMD request status")
    esmd_attempt_count: Optional[int] = Field(None, description="Number of ESMD send attempts")
    esmd_last_error: Optional[str] = Field(None, description="Last ESMD error message")


class ResendToEsmdRequest(BaseModel):
    """Request to resend ESMD payload after fixes"""
    notes: Optional[str] = Field(None, description="Optional notes about the fix")


class ResendToEsmdResponse(BaseModel):
    """Response from resend to ESMD action"""
    success: bool
    message: str
    response_id: Optional[int] = Field(None, description="Integration outbox response_id")
    esmd_attempt_count: Optional[int] = Field(None, description="New attempt count after resend")

