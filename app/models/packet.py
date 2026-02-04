"""
Packet Models
Pydantic models for packet management
"""
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr

# Import enums from packet_dto to avoid duplication
if TYPE_CHECKING:
    from app.models.packet_dto import PacketHighLevelStatus, ManualReviewType
else:
    # Import at runtime to avoid circular dependency
    from app.models.packet_dto import PacketHighLevelStatus, ManualReviewType


class PacketStatus(str, Enum):
    """Packet workflow status"""
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditLogEntry(BaseModel):
    """Audit log entry for packet changes"""
    action: str  # 'create', 'update', 'delete', 'status_change'
    user_id: str
    timestamp: datetime
    details: Optional[str] = None


class PacketBase(BaseModel):
    """Base packet model with common fields"""
    patient_name: str = Field(..., min_length=1, max_length=200)
    patient_dob: datetime
    patient_mrn: str = Field(..., min_length=1, max_length=50)
    patient_phone: str = Field(..., max_length=20)
    patient_email: EmailStr
    diagnosis: str = Field(..., min_length=1, max_length=500)
    referring_provider: str = Field(..., min_length=1, max_length=200)
    referring_provider_npi: str = Field(..., min_length=10, max_length=10)
    insurance: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)


class PacketCreate(PacketBase):
    """Model for creating a new packet"""
    status: PacketStatus = PacketStatus.PENDING
    assigned_to: Optional[str] = None


class PacketUpdate(BaseModel):
    """Model for updating a packet (all fields optional)"""
    patient_name: Optional[str] = Field(None, min_length=1, max_length=200)
    patient_dob: Optional[datetime] = None
    patient_mrn: Optional[str] = Field(None, min_length=1, max_length=50)
    patient_phone: Optional[str] = Field(None, max_length=20)
    patient_email: Optional[EmailStr] = None
    diagnosis: Optional[str] = Field(None, min_length=1, max_length=500)
    referring_provider: Optional[str] = Field(None, min_length=1, max_length=200)
    referring_provider_npi: Optional[str] = Field(None, min_length=10, max_length=10)
    insurance: Optional[str] = Field(None, min_length=1, max_length=200)
    status: Optional[PacketStatus] = None
    assigned_to: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=2000)


class Packet(PacketBase):
    """Complete packet model"""
    id: str
    status: PacketStatus
    assigned_to: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    audit_log: List[AuditLogEntry] = []
    
    # New fields for workflow state (replaces notes encoding)
    high_level_status: Optional[PacketHighLevelStatus] = Field(None, description="High-level workflow status")
    detailed_status: Optional[str] = Field(None, description="Detailed status within current phase")
    review_type: Optional[ManualReviewType] = Field(None, description="Type of manual review required")
    completeness: Optional[int] = Field(None, ge=0, le=100, description="Completeness score (0-100)")

    class Config:
        from_attributes = True


class PacketResponse(BaseModel):
    """Single packet response"""
    success: bool = True
    data: Packet
    message: Optional[str] = None


class PacketListResponse(BaseModel):
    """Paginated packet list response"""
    success: bool = True
    data: List[Packet]
    total: int
    page: int
    page_size: int
    message: Optional[str] = None
