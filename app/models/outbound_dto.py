"""
Outbound DTO Models
Pydantic models matching the frontend OutboundDelivery interface
"""
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field


# ============================================
# Enums
# ============================================

class DeliveryChannelStatus(str, Enum):
    """Delivery channel status"""
    SUCCESS = "Success"
    FAILED = "Failed"
    IN_PROGRESS = "In Progress"
    N_A = "N/A"


class LetterType(str, Enum):
    """Letter type"""
    APPROVAL = "Approval"
    DENIAL = "Denial"
    PARTIAL_APPROVAL = "Partial Approval"
    NEED_MORE_INFO = "Need More Info"


class Priority(str, Enum):
    """Priority level"""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


# ============================================
# Channel Delivery Status
# ============================================

class ChannelDeliveryStatusDTO(BaseModel):
    """Status for a single delivery channel"""
    status: DeliveryChannelStatus
    completedAt: Optional[str] = None
    confirmationId: Optional[str] = None
    attempts: Optional[int] = None
    lastAttempt: Optional[str] = None
    error: Optional[str] = None
    nextRetry: Optional[str] = None
    trackingNumber: Optional[str] = None
    reason: Optional[str] = None


# ============================================
# Delivery Status Object
# ============================================

class DeliveryStatusDTO(BaseModel):
    """All delivery channel statuses for a delivery"""
    providerFax: ChannelDeliveryStatusDTO
    providerPortal: ChannelDeliveryStatusDTO
    esMD: ChannelDeliveryStatusDTO
    memberMail: ChannelDeliveryStatusDTO


# ============================================
# Outbound Delivery DTO
# ============================================

class OutboundDeliveryDTO(BaseModel):
    """Outbound delivery record matching frontend structure"""
    caseId: str
    packetId: str
    patient: str
    provider: str
    letterType: LetterType
    submittedAt: str
    providerFax: str
    faxVerified: bool
    faxVerifiedBy: str
    faxVerifiedAt: str
    deliveryStatus: DeliveryStatusDTO
    hasException: bool
    priority: Priority


# ============================================
# Update DTO
# ============================================

class OutboundDeliveryUpdateDTO(BaseModel):
    """Partial update for outbound delivery"""
    status: Optional[DeliveryChannelStatus] = None
    assignedTo: Optional[str] = None
    deliveryMethod: Optional[str] = None
    notes: Optional[str] = None
    # Channel-specific updates
    providerFaxStatus: Optional[DeliveryChannelStatus] = None
    providerFaxError: Optional[str] = None
    providerFaxNextRetry: Optional[str] = None
    markResolved: Optional[bool] = None  # For marking exception as resolved


# ============================================
# Response Models
# ============================================

class OutboundDeliveryListResponse(BaseModel):
    """Response for list of outbound deliveries"""
    success: bool = True
    data: list[OutboundDeliveryDTO]
    total: int
    page: int = 1
    page_size: int = 50
    message: Optional[str] = None


class OutboundDeliveryResponse(BaseModel):
    """Response for single outbound delivery"""
    success: bool = True
    data: OutboundDeliveryDTO
    message: Optional[str] = None

