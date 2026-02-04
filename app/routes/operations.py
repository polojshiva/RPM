"""
Operations Routes
Endpoints for Support Tickets, P2P Calls, and Analytics
"""
from datetime import datetime, timedelta
from typing import Optional, List, Literal
from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.api import ApiResponse
from app.models.analytics_insights_dto import (
    AnalyticsInsightsResponse,
    TimeRange,
)
from app.services.db import get_db
from app.services.clinical_ops_rejection_processor import ClinicalOpsRejectionProcessor

router = APIRouter(prefix="/api", tags=["Operations"])


# ============================================
# Models
# ============================================

class SupportTicket(BaseModel):
    id: str
    ticketNumber: str
    subject: str
    description: str
    status: str  # 'open' | 'in_progress' | 'pending' | 'resolved' | 'closed'
    priority: str  # 'low' | 'medium' | 'high' | 'urgent'
    category: str  # 'pa_inquiry' | 'technical' | 'billing' | 'general' | 'escalation'
    createdAt: str
    updatedAt: str
    assignedTo: Optional[str] = None
    requesterName: str
    requesterEmail: str
    packetId: Optional[str] = None
    providerNpi: Optional[str] = None  # Added for frontend compatibility
    messages: Optional[List[dict]] = None  # Added for frontend compatibility - stores message history


class P2PCall(BaseModel):
    id: str
    requestId: str
    status: str  # 'new' | 'scheduled' | 'in_progress' | 'completed' | 'cancelled' | 'no_show'
    requestedBy: str
    requestedByRole: str  # 'physician' | 'nurse' | 'case_manager'
    patientName: str
    patientMemberId: str
    packetId: str
    scheduledDate: Optional[str] = None
    scheduledTime: Optional[str] = None
    mdReviewer: Optional[str] = None
    notes: Optional[str] = None
    createdAt: str
    updatedAt: str
    urgency: str  # 'routine' | 'urgent' | 'expedited'
    providerName: Optional[str] = None  # Added for frontend compatibility
    providerNpi: Optional[str] = None  # Added for frontend compatibility
    physicianName: Optional[str] = None  # Added for frontend compatibility (same as requestedBy)
    contactPhone: Optional[str] = None  # Added for frontend compatibility
    contactEmail: Optional[str] = None  # Added for frontend compatibility
    preferredSlots: Optional[List[dict]] = None  # Added for frontend compatibility
    serviceType: Optional[str] = None  # Added for frontend compatibility
    hcpcs: Optional[str] = None  # Added for frontend compatibility
    decision: Optional[str] = None  # Added for frontend compatibility


# Type definitions for validation
TicketStatus = Literal["open", "in_progress", "pending", "resolved", "closed"]
TicketPriority = Literal["low", "medium", "high", "urgent"]
P2PStatus = Literal["new", "scheduled", "in_progress", "completed", "cancelled", "no_show"]


class SupportTicketUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    assignedTo: Optional[str] = None
    notes: Optional[str] = None


class P2PCallUpdate(BaseModel):
    status: Optional[P2PStatus] = None
    scheduledDate: Optional[str] = None
    scheduledTime: Optional[str] = None
    mdReviewer: Optional[str] = None
    notes: Optional[str] = None


# ============================================
# Mock Data (in-memory store)
# ============================================

support_tickets: List[SupportTicket] = [
    SupportTicket(
        id="ST-001",
        ticketNumber="TKT-2025-0001",
        subject="PA Status Inquiry - PA-001235",
        description="Provider inquiring about PA status for DME request.",
        status="open",
        priority="high",
        category="pa_inquiry",
        createdAt="2025-01-23T10:30:00Z",
        updatedAt="2025-01-23T10:30:00Z",
        assignedTo=None,
        requesterName="ABC Medical Clinic",
        requesterEmail="drsmith@abcmedical.com",
        packetId="PA-001235",
        providerNpi="1234567890",
        messages=[
            {
                "id": "msg-1",
                "sender": "Provider",
                "senderName": "Dr. Smith (ABC Medical Clinic)",
                "text": "Hi, I submitted PA-001235 three days ago but haven't received any update. The patient needs the DME urgently. Can you please check the status?",
                "timestamp": "2025-01-23T10:30:00",
            },
        ],
    ),
    SupportTicket(
        id="ST-002",
        ticketNumber="TKT-2025-0002",
        subject="Missing Documentation - PA-001238",
        description="Request for missing documentation clarification.",
        status="pending",
        priority="medium",
        category="pa_inquiry",
        createdAt="2025-01-22T14:15:00Z",
        updatedAt="2025-01-23T09:00:00Z",
        assignedTo="Sarah Wilson",
        requesterName="City Health Center",
        requesterEmail="drjohnson@cityhealthcenter.com",
        packetId="PA-001238",
        providerNpi="9876543210",
        messages=[
            {
                "id": "msg-2",
                "sender": "Provider",
                "senderName": "Dr. Johnson (City Health Center)",
                "text": "The portal shows my PA request is incomplete. What documents are missing?",
                "timestamp": "2025-01-22T14:15:00",
            },
            {
                "id": "msg-3",
                "sender": "Service Ops",
                "senderName": "Sarah Wilson",
                "text": "Hi Dr. Johnson, thank you for reaching out. After reviewing PA-001238, we found that the following documents are needed:\n\n1. Face-to-face encounter notes (within 6 months)\n2. Prescription with specific HCPCS code\n3. Certificate of Medical Necessity\n\nPlease upload these through the portal and we'll process your request promptly.",
                "timestamp": "2025-01-22T15:30:00",
            },
            {
                "id": "msg-4",
                "sender": "Provider",
                "senderName": "Dr. Johnson (City Health Center)",
                "text": "Thank you for clarifying. I'll upload the documents today.",
                "timestamp": "2025-01-22T16:00:00",
            },
            {
                "id": "msg-5",
                "sender": "Service Ops",
                "senderName": "Sarah Wilson",
                "text": "Great! I'll mark this ticket as pending. Please let me know once you've uploaded the documents.",
                "timestamp": "2025-01-23T09:00:00",
            },
        ],
    ),
    SupportTicket(
        id="ST-003",
        ticketNumber="TKT-2025-0003",
        subject="Appeal Process Question",
        description="Provider asking about appeal process for denied PA.",
        status="pending",
        priority="medium",
        category="escalation",
        createdAt="2025-01-21T11:45:00Z",
        updatedAt="2025-01-22T10:00:00Z",
        assignedTo="Mike Chen",
        requesterName="Metro Healthcare",
        requesterEmail="drmartinez@metrohealthcare.com",
        packetId="PA-001241",
        providerNpi="5678901234",
        messages=[
            {
                "id": "msg-6",
                "sender": "Provider",
                "senderName": "Dr. Martinez (Metro Healthcare)",
                "text": "PA-001241 was denied. I want to file an appeal. What is the process?",
                "timestamp": "2025-01-21T11:45:00",
            },
            {
                "id": "msg-7",
                "sender": "Service Ops",
                "senderName": "Mike Chen",
                "text": "Dr. Martinez, I understand your concern. To file an appeal for PA-001241:\n\n1. Submit within 60 days of the denial letter\n2. Include additional clinical documentation supporting medical necessity\n3. You can submit via portal (Appeals section) or fax to our appeals department\n\nWould you like me to send you the detailed appeal form?",
                "timestamp": "2025-01-22T10:00:00",
            },
        ],
    ),
    SupportTicket(
        id="ST-004",
        ticketNumber="TKT-2025-0004",
        subject="Portal Login Issue",
        description="Provider unable to log into the portal.",
        status="resolved",
        priority="low",
        category="technical",
        createdAt="2025-01-20T09:00:00Z",
        updatedAt="2025-01-20T11:30:00Z",
        assignedTo="Sarah Wilson",
        requesterName="Family Care Associates",
        requesterEmail="office@familycareassociates.com",
        providerNpi="4567890123",
        messages=[
            {
                "id": "msg-8",
                "sender": "Provider",
                "senderName": "Office Staff (Family Care Associates)",
                "text": "We can't log into the portal. It keeps showing an error message.",
                "timestamp": "2025-01-20T09:00:00",
            },
            {
                "id": "msg-9",
                "sender": "Service Ops",
                "senderName": "Sarah Wilson",
                "text": "I apologize for the inconvenience. Can you please provide:\n1. The exact error message you're seeing\n2. The username you're trying to use\n3. Have you tried resetting your password?",
                "timestamp": "2025-01-20T09:30:00",
            },
            {
                "id": "msg-10",
                "sender": "Provider",
                "senderName": "Office Staff (Family Care Associates)",
                "text": "The error says \"Invalid credentials\". Username is familycare_admin. Yes, we tried reset but didn't receive the email.",
                "timestamp": "2025-01-20T10:00:00",
            },
            {
                "id": "msg-11",
                "sender": "Service Ops",
                "senderName": "Sarah Wilson",
                "text": "I've reset your password and sent a new reset link to the registered email. Please check your spam folder as well. The new temporary password is also being sent via secure message. Let me know if you're still having issues.",
                "timestamp": "2025-01-20T11:00:00",
            },
            {
                "id": "msg-12",
                "sender": "Provider",
                "senderName": "Office Staff (Family Care Associates)",
                "text": "Got it! We can login now. Thank you so much!",
                "timestamp": "2025-01-20T11:30:00",
            },
        ],
    ),
    SupportTicket(
        id="ST-005",
        ticketNumber="TKT-2025-0005",
        subject="Expedited PA Request - Urgent",
        description="Urgent request for expedited PA processing for hospital discharge.",
        status="open",
        priority="high",
        category="pa_inquiry",
        createdAt="2025-01-23T08:00:00Z",
        updatedAt="2025-01-23T08:00:00Z",
        assignedTo=None,
        requesterName="Sunrise Medical Group",
        requesterEmail="drlee@sunrisemedical.com",
        packetId="PA-001250",
        providerNpi="3456789012",
        messages=[
            {
                "id": "msg-13",
                "sender": "Provider",
                "senderName": "Dr. Lee (Sunrise Medical Group)",
                "text": "Patient requires urgent DME (wheelchair) for discharge from hospital today. PA-001250 was submitted yesterday. Can this be expedited?",
                "timestamp": "2025-01-23T08:00:00",
            },
        ],
    ),
]

p2p_calls: List[P2PCall] = [
    P2PCall(
        id="P2P-2025-001",
        requestId="REQ-2025-0001",
        status="new",
        requestedBy="Dr. Smith",
        requestedByRole="physician",
        patientName="John Smith",
        patientMemberId="MEM-78945612",
        packetId="SVC-2025-001235",
        createdAt="2025-01-23T08:30:00Z",
        updatedAt="2025-01-23T08:30:00Z",
        urgency="expedited",
        notes="Patient requires urgent DME for post-surgical recovery. Denial based on incomplete documentation but we have additional clinical notes to present.",
        providerName="ABC Medical Clinic",
        providerNpi="1234567890",
        physicianName="Dr. Smith",
        contactPhone="555-123-4567",
        contactEmail="dr.smith@abcmedical.com",
        preferredSlots=[
            {"date": "2025-01-24", "time": "10:00"},
            {"date": "2025-01-24", "time": "14:00"},
            {"date": "2025-01-25", "time": "09:00"},
        ],
        serviceType="DME - TLSO Brace",
        hcpcs="L0450",
        decision="Non-Affirmed",
    ),
    P2PCall(
        id="P2P-2025-002",
        requestId="REQ-2025-0002",
        status="scheduled",
        requestedBy="Dr. Johnson",
        requestedByRole="physician",
        patientName="Maria Garcia",
        patientMemberId="MEM-45678901",
        packetId="SVC-2025-001238",
        createdAt="2025-01-22T14:00:00Z",
        updatedAt="2025-01-22T14:00:00Z",
        urgency="routine",
        notes="Would like to discuss alternative treatment options and present additional medical necessity documentation. Attempting to reach Dr. Chen for availability",
        providerName="City Health Center",
        providerNpi="9876543210",
        physicianName="Dr. Johnson",
        contactPhone="555-234-5678",
        contactEmail="dr.johnson@cityhealth.com",
        preferredSlots=[
            {"date": "2025-01-25", "time": "11:00"},
            {"date": "2025-01-26", "time": "15:00"},
        ],
        serviceType="DME - Knee Orthosis",
        hcpcs="L1832",
        decision="Partial Affirmation",
    ),
    P2PCall(
        id="P2P-2025-003",
        requestId="REQ-2025-0003",
        status="scheduled",
        requestedBy="Dr. Martinez",
        requestedByRole="physician",
        patientName="Robert Thompson",
        patientMemberId="MEM-32165498",
        packetId="SVC-2025-001241",
        scheduledDate="2025-01-27",
        scheduledTime="10:00",
        mdReviewer="Dr. Michael Chen",
        createdAt="2025-01-21T10:00:00Z",
        updatedAt="2025-01-21T10:00:00Z",
        urgency="routine",
        notes="Confirmed with both parties. Calendar invite sent.",
        providerName="Metro Healthcare",
        providerNpi="5678901234",
        physicianName="Dr. Martinez",
        contactPhone="555-345-6789",
        contactEmail="dr.martinez@metrohc.com",
        preferredSlots=[
            {"date": "2025-01-27", "time": "10:00"},
            {"date": "2025-01-27", "time": "14:00"},
            {"date": "2025-01-28", "time": "09:00"},
        ],
        serviceType="DME - Lumbar Support",
        hcpcs="L0631",
        decision="Non-Affirmed",
    ),
    P2PCall(
        id="P2P-2025-004",
        requestId="REQ-2025-0004",
        status="scheduled",
        requestedBy="Dr. Williams",
        requestedByRole="physician",
        patientName="William Carter",
        patientMemberId="MEM-98765432",
        packetId="SVC-2025-001244",
        createdAt="2025-01-20T16:00:00Z",
        updatedAt="2025-01-20T16:00:00Z",
        urgency="routine",
        notes="Disagree with denial reasoning. Want to present case directly to MD reviewer. Left voicemail and sent email. Waiting for provider to confirm slot.",
        providerName="Family Care Associates",
        providerNpi="4567890123",
        physicianName="Dr. Williams",
        contactPhone="555-456-7890",
        contactEmail="dr.williams@familycare.com",
        preferredSlots=[
            {"date": "2025-01-26", "time": "13:00"},
        ],
        serviceType="DME - Ankle Brace",
        hcpcs="L1902",
        decision="Non-Affirmed",
    ),
    P2PCall(
        id="P2P-2025-005",
        requestId="REQ-2025-0005",
        status="completed",
        requestedBy="Dr. Lee",
        requestedByRole="physician",
        patientName="Jennifer Martinez",
        patientMemberId="MEM-11223344",
        packetId="SVC-2025-001246",
        scheduledDate="2025-01-22",
        scheduledTime="11:00",
        mdReviewer="Dr. Amanda White",
        createdAt="2025-01-19T09:00:00Z",
        updatedAt="2025-01-22T11:30:00Z",
        urgency="urgent",
        notes="Patient has deteriorating condition. Need expedited review of additional clinical evidence. Call completed. MD reversed decision based on new clinical documentation presented.",
        providerName="Sunrise Medical Group",
        providerNpi="3456789012",
        physicianName="Dr. Lee",
        contactPhone="555-567-8901",
        contactEmail="dr.lee@sunrisemedical.com",
        preferredSlots=[
            {"date": "2025-01-22", "time": "11:00"},
            {"date": "2025-01-22", "time": "15:00"},
        ],
        serviceType="DME - Cervical Collar",
        hcpcs="L0120",
        decision="Affirmed (after P2P)",
    ),
    P2PCall(
        id="P2P-2025-006",
        requestId="REQ-2025-0006",
        status="cancelled",
        requestedBy="Dr. Brown",
        requestedByRole="physician",
        patientName="Susan Anderson",
        patientMemberId="MEM-22334455",
        packetId="SVC-2025-001251",
        createdAt="2025-01-18T14:00:00Z",
        updatedAt="2025-01-18T16:00:00Z",
        urgency="routine",
        notes="Would like to discuss denial with reviewing MD. Provider cancelled - submitted additional documentation instead.",
        providerName="Valley Medical Center",
        providerNpi="2345678901",
        physicianName="Dr. Brown",
        contactPhone="555-678-9012",
        contactEmail="dr.brown@valleymed.com",
        preferredSlots=[
            {"date": "2025-01-23", "time": "10:00"},
        ],
        serviceType="DME - Wrist Orthosis",
        hcpcs="L3806",
        decision="Non-Affirmed",
    ),
]


# ============================================
# Helper Functions
# ============================================

def get_pending_counts() -> dict:
    """Calculate pending counts for badges"""
    open_tickets = sum(1 for t in support_tickets if t.status == "open")
    new_p2p = sum(1 for p in p2p_calls if p.status == "new")
    return {
        "supportTicketsPending": open_tickets,
        "p2pCallsNew": new_p2p,
    }


def days_ago(days: int) -> str:
    """Generate ISO date string for N days ago"""
    date = datetime.now() - timedelta(days=days)
    return date.isoformat()


# ============================================
# Support Tickets Endpoints
# ============================================

from app.models.support_ticket_dto import (
    SupportTicketListResponse,
    SupportTicketResponse,
    SupportTicketUpdateDTO,
    TicketStatus,
    TicketPriority,
)
from app.utils.support_ticket_converter import tickets_to_dto_list, ticket_to_dto

@router.get("/support-tickets", response_model=SupportTicketListResponse)
async def get_support_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """Get all support tickets with optional filters"""
    filtered = support_tickets.copy()
    if status:
        # Map frontend status to backend status
        status_map = {
            "Open": "open",
            "Pending": "pending",
            "Resolved": "resolved",
            "Awaiting Provider Response": "in_progress",
        }
        backend_status = status_map.get(status, status.lower())
        filtered = [t for t in filtered if t.status == backend_status]
    if priority:
        # Map frontend priority to backend priority
        priority_map = {
            "High": "high",
            "Medium": "medium",
            "Low": "low",
        }
        backend_priority = priority_map.get(priority, priority.lower())
        filtered = [t for t in filtered if t.priority == backend_priority]
    
    dto_list = tickets_to_dto_list(filtered)
    return SupportTicketListResponse(
        success=True,
        data=dto_list,
        total=len(dto_list),
    )


@router.get("/support-tickets/{ticket_id}", response_model=SupportTicketResponse)
async def get_support_ticket(
    ticket_id: str,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """Get a single support ticket by ID or ticket number"""
    ticket = next((t for t in support_tickets if t.id == ticket_id or t.ticketNumber == ticket_id), None)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    dto = ticket_to_dto(ticket)
    return SupportTicketResponse(success=True, data=dto)


@router.patch("/support-tickets/{ticket_id}", response_model=SupportTicketResponse)
async def update_support_ticket(
    ticket_id: str,
    update: SupportTicketUpdateDTO,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER])),
):
    """Update a support ticket"""
    for i, ticket in enumerate(support_tickets):
        if ticket.id == ticket_id or ticket.ticketNumber == ticket_id:
            update_data = update.model_dump(exclude_unset=True)
            
            # Map frontend status/priority to backend format
            if "status" in update_data and update_data["status"]:
                status_map = {
                    "Open": "open",
                    "Pending": "pending",
                    "Resolved": "resolved",
                    "Awaiting Provider Response": "in_progress",
                }
                update_data["status"] = status_map.get(update_data["status"], update_data["status"].lower())
            
            if "priority" in update_data and update_data["priority"]:
                priority_map = {
                    "High": "high",
                    "Medium": "medium",
                    "Low": "low",
                }
                update_data["priority"] = priority_map.get(update_data["priority"], update_data["priority"].lower())
            
            ticket_dict = ticket.model_dump()
            ticket_dict.update(update_data)
            ticket_dict["updatedAt"] = datetime.now().isoformat()
            support_tickets[i] = SupportTicket(**ticket_dict)
            
            dto = ticket_to_dto(support_tickets[i])
            return SupportTicketResponse(success=True, data=dto)
    
    raise HTTPException(status_code=404, detail="Ticket not found")


# ============================================
# P2P Calls Endpoints
# ============================================

from app.models.p2p_request_dto import (
    P2PRequestListResponse,
    P2PRequestResponse,
    P2PRequestUpdateDTO,
    P2PStatus,
)
from app.utils.p2p_request_converter import calls_to_dto_list, call_to_dto

@router.get("/p2p-calls", response_model=P2PRequestListResponse)
async def get_p2p_calls(
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """Get all P2P calls with optional filters"""
    filtered = p2p_calls.copy()
    if status:
        # Map frontend status to backend status
        status_map = {
            "New Request": "new",
            "Scheduling": "scheduled",  # Treat as scheduled
            "Scheduled": "scheduled",
            "Awaiting Provider": "in_progress",
            "Completed": "completed",
            "Cancelled": "cancelled",
            "No Show": "no_show",
        }
        backend_status = status_map.get(status, status.lower())
        filtered = [p for p in filtered if p.status == backend_status]
    if urgency:
        # Map frontend priority to backend urgency
        urgency_map = {
            "Expedited": "expedited",
            "High": "urgent",
            "Standard": "routine",
        }
        backend_urgency = urgency_map.get(urgency, urgency.lower())
        filtered = [p for p in filtered if p.urgency == backend_urgency]
    
    dto_list = calls_to_dto_list(filtered)
    return P2PRequestListResponse(
        success=True,
        data=dto_list,
        total=len(dto_list),
    )


@router.get("/p2p-calls/{call_id}", response_model=P2PRequestResponse)
async def get_p2p_call(
    call_id: str,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """Get a single P2P call by ID or request ID"""
    call = next((p for p in p2p_calls if p.id == call_id or p.requestId == call_id), None)
    if not call:
        raise HTTPException(status_code=404, detail="P2P call not found")
    
    dto = call_to_dto(call)
    return P2PRequestResponse(success=True, data=dto)


@router.patch("/p2p-calls/{call_id}", response_model=P2PRequestResponse)
async def update_p2p_call(
    call_id: str,
    update: P2PRequestUpdateDTO,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER])),
):
    """Update a P2P call"""
    for i, call in enumerate(p2p_calls):
        if call.id == call_id or call.requestId == call_id:
            update_data = update.model_dump(exclude_unset=True)
            
            # Map frontend status to backend format
            if "status" in update_data and update_data["status"]:
                status_map = {
                    "New Request": "new",
                    "Scheduling": "scheduled",
                    "Scheduled": "scheduled",
                    "Awaiting Provider": "in_progress",
                    "Completed": "completed",
                    "Cancelled": "cancelled",
                    "No Show": "no_show",
                }
                update_data["status"] = status_map.get(update_data["status"], update_data["status"].lower())
            
            # Handle scheduledFor -> scheduledDate/scheduledTime
            if "scheduledFor" in update_data and update_data["scheduledFor"]:
                scheduled_for = update_data.pop("scheduledFor")
                if "T" in scheduled_for:
                    date_part, time_part = scheduled_for.split("T")
                    update_data["scheduledDate"] = date_part
                    update_data["scheduledTime"] = time_part[:5]  # HH:MM
                else:
                    update_data["scheduledDate"] = scheduled_for
            
            # Also handle scheduledDate/scheduledTime if provided directly
            if "scheduledDate" in update_data or "scheduledTime" in update_data:
                pass  # Already handled above
            
            call_dict = call.model_dump()
            call_dict.update(update_data)
            call_dict["updatedAt"] = datetime.now().isoformat()
            p2p_calls[i] = P2PCall(**call_dict)
            
            dto = call_to_dto(p2p_calls[i])
            return P2PRequestResponse(success=True, data=dto)
    
    raise HTTPException(status_code=404, detail="P2P call not found")


# ============================================
# Analytics Endpoints
# ============================================

@router.get("/analytics/insights", response_model=AnalyticsInsightsResponse)
async def get_analytics_insights(
    timeRange: TimeRange = Query("7d", regex="^(24h|7d|30d)$"),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """
    Get analytics insights data for strategic performance analysis
    """
    # Example DB query for analytics insights (replace with actual model/logic)
    # insights_data = db.query(AnalyticsInsights).filter(...)
    # For now, return an empty list or a stub if model is not defined
    insights_data = []
    return AnalyticsInsightsResponse(
        success=True,
        data=insights_data,
    )


@router.get("/analytics")
async def get_analytics(current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR]))):
    """Get all analytics data combined"""
    return {
        "agingMetrics": {
            "intake": {
                "count": 45,
                "averageAge": 1.2,
                "slaTarget": 2,
                "overSla": 5,
                "distribution": {
                    "0-1 days": 25,
                    "1-2 days": 15,
                    "2+ days": 5,
                },
            },
            "clinical": {
                "count": 78,
                "averageAge": 2.1,
                "slaTarget": 3,
                "overSla": 12,
                "distribution": {
                    "0-1 days": 30,
                    "1-2 days": 28,
                    "2-3 days": 8,
                    "3+ days": 12,
                },
            },
            "outbound": {
                "count": 23,
                "averageAge": 0.4,
                "slaTarget": 0.5,
                "overSla": 3,
                "distribution": {
                    "0-6 hours": 15,
                    "6-12 hours": 5,
                    "12+ hours": 3,
                },
            },
            "total": {
                "activePackets": 146,
                "averageTurnaround": 3.8,
                "slaCompliance": 89.2,
                "overSlaCount": 20,
            },
        },
        "workloadMetrics": {
            "teams": [
                {"name": "Intake Team A", "activeItems": 18, "capacity": 25, "utilization": 72},
                {"name": "Intake Team B", "activeItems": 22, "capacity": 25, "utilization": 88},
                {"name": "Clinical Team A", "activeItems": 35, "capacity": 40, "utilization": 87.5},
                {"name": "Clinical Team B", "activeItems": 38, "capacity": 40, "utilization": 95},
                {"name": "Outbound Team", "activeItems": 15, "capacity": 30, "utilization": 50},
            ],
            "reviewers": [
                {"name": "Dr. Amanda White", "pending": 12, "completed": 45, "avgTime": 2.3},
                {"name": "Dr. Robert Kim", "pending": 15, "completed": 38, "avgTime": 2.8},
                {"name": "Dr. Emily Chen", "pending": 8, "completed": 52, "avgTime": 1.9},
            ],
        },
        "trendData": [
            {"date": days_ago(6), "received": 45, "processed": 42, "pending": 120},
            {"date": days_ago(5), "received": 52, "processed": 48, "pending": 124},
            {"date": days_ago(4), "received": 38, "processed": 45, "pending": 117},
            {"date": days_ago(3), "received": 61, "processed": 55, "pending": 123},
            {"date": days_ago(2), "received": 48, "processed": 52, "pending": 119},
            {"date": days_ago(1), "received": 55, "processed": 50, "pending": 124},
            {"date": days_ago(0), "received": 42, "processed": 38, "pending": 128},
        ],
        "apiHealth": [
            {
                "name": "HETS",
                "status": "operational",
                "uptime": 99.8,
                "avgResponse": 2.1,
                "lastCheck": "2 min ago",
            },
            {
                "name": "PECOS",
                "status": "degraded",
                "uptime": 95.2,
                "avgResponse": 4.5,
                "lastCheck": "1 min ago",
            },
            {
                "name": "OIG",
                "status": "operational",
                "uptime": 99.9,
                "avgResponse": 0.8,
                "lastCheck": "3 min ago",
            },
            {
                "name": "NPI",
                "status": "operational",
                "uptime": 100,
                "avgResponse": 0.4,
                "lastCheck": "1 min ago",
            },
        ],
    }


@router.post(
    "/admin/process-clinical-ops-rejections",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_200_OK
)
async def process_clinical_ops_rejections(
    batch_size: int = Query(10, ge=1, le=50, description="Number of records to process in one batch"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR]))
):
    """
    Process rejected ClinicalOps records and loop them back to validation
    
    This endpoint:
    1. Finds records where is_picked = false with error_reason
    2. Loops packets back to "Intake Validation" status
    3. Creates validation records with error reasons
    
    Args:
        batch_size: Maximum number of records to process (1-50)
        db: Database session
        current_user: Current authenticated user (must be ADMIN or COORDINATOR)
        
    Returns:
        Number of records processed
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get count before processing
        initial_count = ClinicalOpsRejectionProcessor.get_rejected_records_count(db)
        
        # Process rejected records
        processed_count = ClinicalOpsRejectionProcessor.process_rejected_records(
            db=db,
            batch_size=batch_size
        )
        
        # Get count after processing
        remaining_count = ClinicalOpsRejectionProcessor.get_rejected_records_count(db)
        
        logger.info(
            f"Processed {processed_count} rejected ClinicalOps records. "
            f"Remaining: {remaining_count}"
        )
        
        return ApiResponse(
            success=True,
            message=f"Processed {processed_count} rejected records",
            data={
                "processed_count": processed_count,
                "remaining_count": remaining_count,
                "initial_count": initial_count
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing ClinicalOps rejections: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process rejections: {str(e)}"
        )


@router.get(
    "/admin/clinical-ops-rejections-count",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_200_OK
)
async def get_clinical_ops_rejections_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR]))
):
    """
    Get count of rejected ClinicalOps records that need to be processed
    
    Returns:
        Count of unprocessed rejected records
    """
    try:
        count = ClinicalOpsRejectionProcessor.get_rejected_records_count(db)
        
        return ApiResponse(
            success=True,
            message=f"Found {count} rejected records pending processing",
            data={"count": count}
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting rejection count: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get rejection count: {str(e)}"
        )


# Export for pending-actions endpoint to use
def get_operations_pending_counts() -> dict:
    """Get pending counts - to be called from health routes"""
    return get_pending_counts()
