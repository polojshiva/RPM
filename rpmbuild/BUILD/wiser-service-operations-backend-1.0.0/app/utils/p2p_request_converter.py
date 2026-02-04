"""
P2P Request Converter
Converts internal P2PCall model to P2PRequestDTO
"""
from typing import List, Optional
from app.routes.operations import P2PCall
from app.models.p2p_request_dto import (
    P2PRequestDTO,
    TimeSlotDTO,
    P2PStatus,
    P2PPriority,
)


def map_status_to_dto(status: str) -> P2PStatus:
    """Map backend status to frontend status"""
    status_map = {
        "new": P2PStatus.NEW_REQUEST,
        "scheduled": P2PStatus.SCHEDULED,
        "in_progress": P2PStatus.AWAITING_PROVIDER,
        "completed": P2PStatus.COMPLETED,
        "cancelled": P2PStatus.CANCELLED,
        "no_show": P2PStatus.NO_SHOW,
    }
    return status_map.get(status.lower(), P2PStatus.NEW_REQUEST)


def map_urgency_to_priority(urgency: str) -> P2PPriority:
    """Map backend urgency to frontend priority"""
    urgency_map = {
        "routine": P2PPriority.STANDARD,
        "urgent": P2PPriority.HIGH,
        "expedited": P2PPriority.EXPEDITED,
    }
    return urgency_map.get(urgency.lower(), P2PPriority.STANDARD)


def combine_scheduled_datetime(scheduled_date: Optional[str], scheduled_time: Optional[str]) -> Optional[str]:
    """Combine scheduledDate and scheduledTime into scheduledFor ISO string"""
    if scheduled_date and scheduled_time:
        # Format: "2025-01-27T10:00:00"
        return f"{scheduled_date}T{scheduled_time}:00"
    elif scheduled_date:
        return f"{scheduled_date}T00:00:00"
    return None


def generate_preferred_slots(call: P2PCall) -> List[TimeSlotDTO]:
    """
    Generate preferred time slots from P2P call.
    
    Uses preferredSlots from call if available, otherwise generates defaults.
    """
    if call.preferredSlots:
        # Use slots from call if available
        return [TimeSlotDTO(**slot) for slot in call.preferredSlots]
    
    # Fallback: generate slots based on scheduled date/time
    slots = []
    if call.scheduledDate:
        base_date = call.scheduledDate
        if call.scheduledTime:
            slots.append(TimeSlotDTO(date=base_date, time=call.scheduledTime))
        else:
            slots.append(TimeSlotDTO(date=base_date, time="10:00"))
            slots.append(TimeSlotDTO(date=base_date, time="14:00"))
    else:
        # Generate default preferred slots (next 3 days, morning and afternoon)
        from datetime import datetime, timedelta
        today = datetime.now()
        for i in range(1, 4):
            date_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            slots.append(TimeSlotDTO(date=date_str, time="10:00"))
            slots.append(TimeSlotDTO(date=date_str, time="14:00"))
    
    return slots


def call_to_dto(call: P2PCall) -> P2PRequestDTO:
    """
    Convert internal P2PCall to P2PRequestDTO.
    
    Uses fields from call model if available, otherwise falls back to defaults.
    """
    # Extract packet ID to get PA ID (format: SVC-2025-001235 -> PA-001235)
    # Only support SVC- prefix (PKT- is used by other modules, avoid confusion)
    if call.packetId and call.packetId.startswith("SVC-"):
        pa_id = call.packetId.replace("SVC-", "PA-")
    else:
        pa_id = call.packetId or ""
    
    # Combine scheduled date/time
    scheduled_for = combine_scheduled_datetime(call.scheduledDate, call.scheduledTime)
    
    # Generate preferred slots
    preferred_slots = generate_preferred_slots(call)
    
    return P2PRequestDTO(
        id=call.id,
        paId=pa_id,
        packetId=call.packetId or "",
        status=map_status_to_dto(call.status),
        priority=map_urgency_to_priority(call.urgency),
        providerName=call.providerName or "Unknown Provider",
        providerNpi=call.providerNpi or "",
        physicianName=call.physicianName or call.requestedBy,
        contactPhone=call.contactPhone or "",
        contactEmail=call.contactEmail or "",
        preferredSlots=preferred_slots,
        reason=call.notes or "P2P call requested",
        requestedAt=call.createdAt,
        scheduledFor=scheduled_for,
        mdReviewer=call.mdReviewer,
        beneficiaryName=call.patientName,
        serviceType=call.serviceType or "DME",
        hcpcs=call.hcpcs or "",
        decision=call.decision or "Non-Affirmed",
        notes=call.notes,
    )


def calls_to_dto_list(calls: List[P2PCall]) -> List[P2PRequestDTO]:
    """Convert list of internal P2P calls to DTO list"""
    return [call_to_dto(call) for call in calls]

