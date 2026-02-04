"""
P2P Request DTO Models
Matching frontend P2PRequest interface
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class P2PStatus(str, Enum):
    """P2P status enum matching frontend"""
    NEW_REQUEST = "New Request"
    SCHEDULING = "Scheduling"
    SCHEDULED = "Scheduled"
    AWAITING_PROVIDER = "Awaiting Provider"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NO_SHOW = "No Show"


class P2PPriority(str, Enum):
    """P2P priority enum matching frontend"""
    EXPEDITED = "Expedited"
    HIGH = "High"
    STANDARD = "Standard"


class TimeSlotDTO(BaseModel):
    """Time slot DTO matching frontend TimeSlot interface"""
    date: str
    time: str

    class Config:
        json_schema_extra = {
            "example": {
                "date": "2025-01-24",
                "time": "10:00",
            }
        }


class P2PRequestDTO(BaseModel):
    """P2P Request DTO matching frontend P2PRequest interface"""
    id: str
    paId: str
    packetId: str
    status: P2PStatus
    priority: P2PPriority
    providerName: str
    providerNpi: str
    physicianName: str
    contactPhone: str
    contactEmail: str
    preferredSlots: list[TimeSlotDTO] = Field(default_factory=list)
    reason: str
    requestedAt: str
    scheduledFor: Optional[str] = None
    mdReviewer: Optional[str] = None
    beneficiaryName: str
    serviceType: str
    hcpcs: str
    decision: str
    notes: Optional[str] = None

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "id": "P2P-2025-001",
                "paId": "PA-001235",
                "packetId": "SVC-2025-001235",
                "status": "New Request",
                "priority": "Expedited",
                "providerName": "ABC Medical Clinic",
                "providerNpi": "1234567890",
                "physicianName": "Dr. Smith",
                "contactPhone": "555-123-4567",
                "contactEmail": "dr.smith@abcmedical.com",
                "preferredSlots": [
                    {"date": "2025-01-24", "time": "10:00"},
                    {"date": "2025-01-24", "time": "14:00"},
                ],
                "reason": "Patient requires urgent DME for post-surgical recovery.",
                "requestedAt": "2025-01-23T08:30:00",
                "beneficiaryName": "John Smith",
                "serviceType": "DME - TLSO Brace",
                "hcpcs": "L0450",
                "decision": "Non-Affirmed",
            }
        }


class P2PRequestUpdateDTO(BaseModel):
    """Update DTO for P2P requests"""
    status: Optional[P2PStatus] = None
    scheduledFor: Optional[str] = None
    mdReviewer: Optional[str] = None
    notes: Optional[str] = None
    scheduledDate: Optional[str] = None  # For backward compatibility
    scheduledTime: Optional[str] = None  # For backward compatibility

    class Config:
        use_enum_values = True


class P2PRequestListResponse(BaseModel):
    """Response model for P2P request list endpoint"""
    success: bool = True
    data: list[P2PRequestDTO]
    total: int
    message: Optional[str] = None


class P2PRequestResponse(BaseModel):
    """Response model for single P2P request endpoint"""
    success: bool = True
    data: P2PRequestDTO
    message: Optional[str] = None

