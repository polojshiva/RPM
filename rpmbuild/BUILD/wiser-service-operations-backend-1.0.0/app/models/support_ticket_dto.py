"""
Support Ticket DTO Models
Matching frontend SupportTicket interface
"""
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """Ticket status enum matching frontend"""
    OPEN = "Open"
    PENDING = "Pending"
    RESOLVED = "Resolved"
    AWAITING_PROVIDER_RESPONSE = "Awaiting Provider Response"


class TicketPriority(str, Enum):
    """Ticket priority enum matching frontend"""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TicketType(str, Enum):
    """Ticket type enum matching frontend"""
    PA_STATUS = "PA Status"
    TECHNICAL_ISSUE = "Technical Issue"
    DOCUMENTATION = "Documentation"
    APPEAL = "Appeal"
    GENERAL_INQUIRY = "General Inquiry"


class SupportMessageDTO(BaseModel):
    """Support message DTO matching frontend SupportMessage interface"""
    id: str
    sender: str = Field(..., description="'Provider' or 'Service Ops'")
    senderName: str
    text: str
    timestamp: str
    attachments: Optional[List[str]] = None

    class Config:
        use_enum_values = True


class SupportTicketDTO(BaseModel):
    """Support Ticket DTO matching frontend SupportTicket interface"""
    id: str
    subject: str
    type: TicketType
    status: TicketStatus
    priority: TicketPriority
    providerName: str
    providerNpi: str
    paId: Optional[str] = None
    createdAt: str
    lastUpdate: str
    assignedTo: Optional[str] = None
    messages: List[SupportMessageDTO] = Field(default_factory=list)

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "id": "TKT-2025-0001",
                "subject": "PA Status Inquiry - PA-001235",
                "type": "PA Status",
                "status": "Open",
                "priority": "High",
                "providerName": "ABC Medical Clinic",
                "providerNpi": "1234567890",
                "paId": "PA-001235",
                "createdAt": "2025-01-23T10:30:00",
                "lastUpdate": "2025-01-23T10:30:00",
                "assignedTo": None,
                "messages": [
                    {
                        "id": "msg-1",
                        "sender": "Provider",
                        "senderName": "Dr. Smith (ABC Medical Clinic)",
                        "text": "Hi, I submitted PA-001235 three days ago...",
                        "timestamp": "2025-01-23T10:30:00",
                    }
                ],
            }
        }


class SupportTicketUpdateDTO(BaseModel):
    """Update DTO for support tickets"""
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    assignedTo: Optional[str] = None
    messages: Optional[List[SupportMessageDTO]] = None

    class Config:
        use_enum_values = True


class SupportTicketListResponse(BaseModel):
    """Response model for ticket list endpoint"""
    success: bool = True
    data: List[SupportTicketDTO]
    total: int
    message: Optional[str] = None


class SupportTicketResponse(BaseModel):
    """Response model for single ticket endpoint"""
    success: bool = True
    data: SupportTicketDTO
    message: Optional[str] = None

