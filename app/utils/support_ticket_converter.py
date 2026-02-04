"""
Support Ticket Converter
Converts internal SupportTicket model to SupportTicketDTO
"""
from typing import List
from app.routes.operations import SupportTicket
from app.models.support_ticket_dto import (
    SupportTicketDTO,
    SupportMessageDTO,
    TicketStatus,
    TicketPriority,
    TicketType,
)


def map_status_to_dto(status: str) -> TicketStatus:
    """Map backend status to frontend status"""
    status_map = {
        "open": TicketStatus.OPEN,
        "pending": TicketStatus.PENDING,
        "resolved": TicketStatus.RESOLVED,
        "in_progress": TicketStatus.AWAITING_PROVIDER_RESPONSE,
    }
    return status_map.get(status.lower(), TicketStatus.OPEN)


def map_priority_to_dto(priority: str) -> TicketPriority:
    """Map backend priority to frontend priority"""
    priority_map = {
        "low": TicketPriority.LOW,
        "medium": TicketPriority.MEDIUM,
        "high": TicketPriority.HIGH,
        "urgent": TicketPriority.HIGH,
    }
    return priority_map.get(priority.lower(), TicketPriority.MEDIUM)


def map_category_to_type(category: str) -> TicketType:
    """Map backend category to frontend type"""
    category_map = {
        "pa_inquiry": TicketType.PA_STATUS,
        "technical": TicketType.TECHNICAL_ISSUE,
        "billing": TicketType.GENERAL_INQUIRY,
        "general": TicketType.GENERAL_INQUIRY,
        "escalation": TicketType.APPEAL,
    }
    return category_map.get(category.lower(), TicketType.GENERAL_INQUIRY)


def ticket_to_dto(ticket: SupportTicket) -> SupportTicketDTO:
    """
    Convert internal SupportTicket to SupportTicketDTO.
    
    Uses messages from ticket.messages if available, otherwise generates from description.
    """
    # Use messages from ticket if available, otherwise generate from description
    messages = []
    if ticket.messages:
        # Convert dict messages to DTOs
        for msg_dict in ticket.messages:
            messages.append(SupportMessageDTO(**msg_dict))
    elif ticket.description:
        # Fallback: generate initial message from description
        messages.append(
            SupportMessageDTO(
                id=f"msg-init-{ticket.id}",
                sender="Provider",
                senderName=f"{ticket.requesterName}",
                text=ticket.description,
                timestamp=ticket.createdAt,
            )
        )
    
    return SupportTicketDTO(
        id=ticket.ticketNumber,  # Use ticketNumber as id to match frontend
        subject=ticket.subject,
        type=map_category_to_type(ticket.category),
        status=map_status_to_dto(ticket.status),
        priority=map_priority_to_dto(ticket.priority),
        providerName=ticket.requesterName,
        providerNpi=ticket.providerNpi or "",  # Use from model if available
        paId=ticket.packetId,
        createdAt=ticket.createdAt,
        lastUpdate=ticket.updatedAt,
        assignedTo=ticket.assignedTo,
        messages=messages,
    )


def tickets_to_dto_list(tickets: List[SupportTicket]) -> List[SupportTicketDTO]:
    """Convert list of internal tickets to DTO list"""
    return [ticket_to_dto(ticket) for ticket in tickets]

