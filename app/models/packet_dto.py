"""
PacketDTO Models
Pydantic models matching the frontend Packet interface structure
"""
from enum import Enum
from typing import Optional, Union, Dict, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# Enums
# ============================================

class PacketHighLevelStatus(str, Enum):
    """High-level workflow status"""
    INTAKE_VALIDATION = "Intake Validation"
    CLINICAL_REVIEW = "Clinical Review"
    OUTBOUND_IN_PROGRESS = "Outbound In Progress"
    CLOSED_DELIVERED = "Closed - Delivered"
    CLOSED_DISMISSED = "Closed - Dismissed"
    CLOSED_ARCHIVED = "Closed - Archived"


class IntakeDetailedStatus(str, Enum):
    """Detailed status for Intake Validation phase"""
    INTAKE_VALIDATION = "Intake Validation"
    RECEIVED = "Received"
    OCR_EXTRACTION = "OCR Extraction"
    MANUAL_REVIEW = "Manual Review"
    VALIDATING = "Validating"
    DISMISSAL_LETTER_GENERATED = "Dismissal Letter Generated"
    DISMISSAL_LETTER_REVIEW = "Dismissal Letter Review"
    CASE_CREATED = "Case Created"


class ClinicalDetailedStatus(str, Enum):
    """Detailed status for Clinical Review phase"""
    PENDING_REVIEW = "Pending Review"
    IN_PROGRESS = "In Progress"
    MD_REVIEW = "MD Review"
    NEED_MORE_INFO = "Need More Info"
    COMPLETED = "Completed"
    SKIPPED_DISMISSED = "Skipped - Dismissed"


class DeliveryDetailedStatus(str, Enum):
    """Detailed status for Outbound In Progress phase"""
    QUEUED = "Queued"
    FAX_IN_PROGRESS = "Fax In Progress"
    MAIL_IN_PROGRESS = "Mail In Progress"
    SENT = "Sent"
    DELIVERED = "Delivered"
    DISMISSAL_LETTER_SENDING = "Dismissal Letter Sending"
    DISMISSAL_LETTER_SENT = "Dismissal Letter Sent"


class ClosedDetailedStatus(str, Enum):
    """Detailed status for Closed phase"""
    DELIVERED = "Delivered"
    DISMISSED = "Dismissed"
    ARCHIVED = "Archived"


# Union type for all detailed statuses (used in type hints)
PacketDetailedStatus = Union[
    IntakeDetailedStatus,
    ClinicalDetailedStatus,
    DeliveryDetailedStatus,
    ClosedDetailedStatus,
]


class Priority(str, Enum):
    """Packet priority level"""
    STANDARD = "Standard"
    EXPEDITED = "Expedited"


class Channel(str, Enum):
    """Submission channel"""
    FAX = "Fax"
    PORTAL = "Portal"
    EDI = "EDI"
    MAIL = "Mail"
    EMAIL = "Email"
    ESMD = "esMD"
    MAILROOM = "Mailroom"


class SLAStatus(str, Enum):
    """SLA compliance status"""
    ON_TRACK = "on_track"
    WARNING = "warning"
    CRITICAL = "critical"


class ManualReviewType(str, Enum):
    """Type of manual review required"""
    FIELDS = "fields"
    CLASSIFICATION = "classification"


# ============================================
# PacketDTO Model
# ============================================

class UtnFailInfo(BaseModel):
    """UTN_FAIL information for a packet"""
    requires_utn_fix: bool = Field(False, description="Flag indicating UTN_FAIL requires remediation")
    utn_status: Optional[str] = Field(None, description="UTN status: NONE, SUCCESS, FAILED")
    error_code: Optional[str] = Field(None, description="Error code from UTN_FAIL")
    error_description: Optional[str] = Field(None, description="Error description from UTN_FAIL (primary user-facing message)")
    esmd_attempt_count: Optional[int] = Field(None, description="Number of ESMD send attempts")


class PacketDTO(BaseModel):
    """
    Packet Data Transfer Object matching frontend Packet interface.
    This is the contract between frontend and backend.
    """
    id: str = Field(..., description="Unique packet identifier (e.g., SVC-2025-001234)")
    caseId: Optional[str] = Field(None, description="Associated case identifier (Portal's packet_id for Portal channel, None for ESMD/Fax)")
    decisionTrackingId: Optional[str] = Field(None, description="Decision tracking ID (UUID) from integration.send_serviceops")
    beneficiaryName: str = Field(..., description="Full name of the beneficiary/patient")
    beneficiaryMbi: str = Field(..., description="Medicare Beneficiary Identifier (MBI)")
    providerName: str = Field(..., description="Name of the rendering provider")
    providerNpi: str = Field(..., min_length=10, max_length=10, description="National Provider Identifier")
    providerFax: Optional[str] = Field(None, description="Provider fax number for delivery")
    serviceType: str = Field(..., description="Type of service requested")
    hcpcs: Optional[str] = Field(None, description="HCPCS code for the service")
    submissionType: Optional[str] = Field(None, description="Submission type from OCR: Expedited or Standard")
    partType: Optional[str] = Field(None, description="Medicare Part type: PART_A, PART_B, or UNKNOWN (from document)")
    
    # Two-tier status system
    highLevelStatus: PacketHighLevelStatus = Field(..., description="High-level workflow status")
    detailedStatus: Optional[str] = Field(None, description="Detailed status within current phase (NULL = New, not in workflow)")
    status: PacketHighLevelStatus = Field(..., description="Legacy field (same as highLevelStatus)")
    
    # Validation status (new workflow)
    validationStatus: Optional[str] = Field(None, description="Validation status: Pending - Validation, Validation Complete, etc.")
    
    # Optional sub-statuses
    clinicalStatus: Optional[ClinicalDetailedStatus] = Field(None, description="Clinical review sub-status")
    deliveryStatus: Optional[DeliveryDetailedStatus] = Field(None, description="Delivery sub-status")
    
    priority: Priority = Field(..., description="Priority level")
    receivedDate: datetime = Field(..., description="Date/time packet was received (ISO 8601)")
    dueDate: datetime = Field(..., description="SLA due date (ISO 8601)")
    channel: Channel = Field(..., description="Submission channel")
    pageCount: int = Field(..., ge=0, description="Total number of pages in packet")
    completeness: int = Field(..., ge=0, le=100, description="Completeness score (0-100)")
    assignedTo: Optional[str] = Field(None, description="User ID or name assigned to packet")
    slaStatus: SLAStatus = Field(..., description="Current SLA status")
    closedDate: Optional[datetime] = Field(None, description="Date packet was closed (ISO 8601)")
    
    # Manual review fields
    reviewType: Optional[ManualReviewType] = Field(None, description="Type of manual review required")
    
    # Dismissal fields
    dismissalReason: Optional[str] = Field(None, description="Reason for dismissal (if dismissed)")
    
    # Progress tracking
    intakeComplete: Optional[bool] = Field(None, description="Whether intake phase is complete")
    validationComplete: Optional[bool] = Field(None, description="Whether validation phase is complete")
    clinicalReviewComplete: Optional[bool] = Field(None, description="Whether clinical review is complete")
    deliveryComplete: Optional[bool] = Field(None, description="Whether delivery is complete")
    letterDelivered: Optional[datetime] = Field(None, description="Date letter was delivered (ISO 8601)")
    
    # UTN_FAIL remediation
    utnFailInfo: Optional[UtnFailInfo] = Field(None, description="UTN_FAIL information if packet requires remediation")
    
    # UTN (Unique Tracking Number)
    utn: Optional[str] = Field(None, description="Unique Tracking Number (UTN) from ESMD")
    
    # Decision fields from packet_decision
    operationalDecision: Optional[str] = Field(None, description="Operational decision: PENDING, DISMISSAL, DISMISSAL_COMPLETE, DECISION_COMPLETE")
    clinicalDecision: Optional[str] = Field(None, description="Clinical decision: PENDING, AFFIRM, NON_AFFIRM")
    
    # Field validation
    hasFieldValidationErrors: Optional[bool] = Field(None, description="True if packet has field-level validation errors")
    fieldValidationErrors: Optional[Dict[str, List[str]]] = Field(None, description="Field-level validation errors")

    # Pydantic v2 configuration - use model_config instead of Config class
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "SVC-2025-001234",
                "caseId": "CASE-001234",
                "beneficiaryName": "John Smith",
                "beneficiaryMbi": "1EG4TE5MK72",
                "providerName": "ABC Medical Clinic",
                "providerNpi": "1234567890",
                "providerFax": "(555) 123-4568",
                "serviceType": "DME - TLSO Brace",
                "hcpcs": "L0450",
                "highLevelStatus": "Intake Validation",
                "detailedStatus": "Intake Validation",
                "status": "Intake Validation",
                "clinicalStatus": None,
                "deliveryStatus": None,
                "priority": "Standard",
                "receivedDate": "2025-12-04T14:30:00Z",
                "dueDate": "2025-12-06T14:30:00Z",
                "channel": "Fax",
                "pageCount": 12,
                "completeness": 85,
                "assignedTo": "Jane Reviewer",
                "slaStatus": "warning",
                "closedDate": None,
                "reviewType": "fields",
                "dismissalReason": None,
                "intakeComplete": True,
                "validationComplete": False,
                "clinicalReviewComplete": False,
                "deliveryComplete": False,
                "letterDelivered": None
            }
        }
    )


class PacketDTOListResponse(BaseModel):
    """Paginated packet list response using PacketDTO"""
    success: bool = True
    data: list[PacketDTO]
    total: int
    page: int
    page_size: int
    message: Optional[str] = None
    status_counts: Optional[dict[str, int]] = Field(
        None,
        description="Counts of packets by high-level status (all packets, not just current page)"
    )


class PacketDTOResponse(BaseModel):
    """Single packet response using PacketDTO"""
    success: bool = True
    data: PacketDTO
    message: Optional[str] = None


class PacketDTOUpdate(BaseModel):
    """Model for updating PacketDTO fields (used by ManualReview and other workflows)"""
    assignedTo: Optional[str] = Field(None, description="User ID or name assigned to packet")
    reviewType: Optional[ManualReviewType] = Field(None, description="Type of manual review required")
    detailedStatus: Optional[str] = Field(None, description="Detailed status within current phase")
    completeness: Optional[int] = Field(None, ge=0, le=100, description="Completeness score (0-100)")
    intakeComplete: Optional[bool] = Field(None, description="Whether intake phase is complete")
    validationComplete: Optional[bool] = Field(None, description="Whether validation phase is complete")
    highLevelStatus: Optional[PacketHighLevelStatus] = Field(None, description="High-level workflow status")
    notes: Optional[str] = Field(None, max_length=2000, description="Additional notes or comments")
    
    class Config:
        json_schema_extra = {
            "example": {
                "assignedTo": "Jane Reviewer",
                "reviewType": "fields",
                "detailedStatus": "Validating",
                "completeness": 95,
                "intakeComplete": True,
                "validationComplete": False
            }
        }

