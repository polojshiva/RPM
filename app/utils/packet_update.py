"""
Packet Update Utilities
Helper functions to apply PacketDTOUpdate to internal Packet model
"""
from typing import Optional
from datetime import datetime, timezone
from app.models.packet import Packet, PacketStatus
from app.models.packet_dto import (
    PacketDTOUpdate,
    PacketHighLevelStatus,
    IntakeDetailedStatus,
    ManualReviewType,
)


def map_high_level_status_to_internal(high_level_status: PacketHighLevelStatus) -> PacketStatus:
    """Map PacketHighLevelStatus back to internal PacketStatus"""
    mapping = {
        PacketHighLevelStatus.INTAKE_VALIDATION: PacketStatus.PENDING,
        PacketHighLevelStatus.CLINICAL_REVIEW: PacketStatus.IN_REVIEW,
        PacketHighLevelStatus.OUTBOUND_IN_PROGRESS: PacketStatus.APPROVED,
        PacketHighLevelStatus.CLOSED_DISMISSED: PacketStatus.REJECTED,
        PacketHighLevelStatus.CLOSED_DELIVERED: PacketStatus.APPROVED,  # Treat as approved
        PacketHighLevelStatus.CLOSED_ARCHIVED: PacketStatus.REJECTED,  # Treat as rejected
    }
    return mapping.get(high_level_status, PacketStatus.PENDING)


def map_detailed_status_to_internal(
    detailed_status: str,
    high_level_status: Optional[PacketHighLevelStatus] = None,
) -> PacketStatus:
    """Map detailed status string back to internal PacketStatus"""
    # If we have high_level_status, use that first
    if high_level_status:
        return map_high_level_status_to_internal(high_level_status)
    
    # Otherwise, infer from detailed status
    detailed_lower = detailed_status.lower()
    
    if "manual review" in detailed_lower:
        return PacketStatus.PENDING
    elif "validating" in detailed_lower or "validation" in detailed_lower:
        return PacketStatus.IN_REVIEW
    elif "case created" in detailed_lower or "pending review" in detailed_lower:
        return PacketStatus.IN_REVIEW
    elif "completed" in detailed_lower or "delivered" in detailed_lower:
        return PacketStatus.APPROVED
    elif "dismissed" in detailed_lower:
        return PacketStatus.REJECTED
    else:
        return PacketStatus.PENDING


def apply_dto_update_to_packet(
    packet: Packet,
    dto_update: PacketDTOUpdate,
) -> Packet:
    """
    Apply PacketDTOUpdate fields to internal Packet model.
    
    This function maps DTO fields to internal model fields:
    - assignedTo -> assigned_to (direct)
    - reviewType -> review_type (direct)
    - detailedStatus -> detailed_status (direct)
    - completeness -> completeness (direct)
    - intakeComplete/validationComplete -> affects status
    - highLevelStatus -> high_level_status (direct) and affects status
    - notes -> notes (direct, pure free-text)
    """
    now = datetime.now(timezone.utc)
    update_dict = dto_update.model_dump(exclude_unset=True)
    
    # Get current packet data
    packet_dict = packet.model_dump()
    
    # Update assigned_to if provided
    if "assignedTo" in update_dict:
        packet_dict["assigned_to"] = update_dict["assignedTo"]
    
    # Update review_type directly (no notes encoding)
    if "reviewType" in update_dict:
        packet_dict["review_type"] = update_dict["reviewType"]
    
    # Update completeness directly (no notes encoding)
    if "completeness" in update_dict and update_dict["completeness"] is not None:
        packet_dict["completeness"] = update_dict["completeness"]
    
    # Update high_level_status directly
    if "highLevelStatus" in update_dict and update_dict["highLevelStatus"]:
        packet_dict["high_level_status"] = update_dict["highLevelStatus"]
    
    # Update detailed_status directly
    if "detailedStatus" in update_dict and update_dict["detailedStatus"]:
        packet_dict["detailed_status"] = update_dict["detailedStatus"]
    
    # Update notes (pure free-text, no encoding)
    if "notes" in update_dict:
        packet_dict["notes"] = update_dict["notes"]
    
    # Update status based on highLevelStatus or detailedStatus
    new_status = packet.status
    if "highLevelStatus" in update_dict and update_dict["highLevelStatus"]:
        new_status = map_high_level_status_to_internal(update_dict["highLevelStatus"])
        packet_dict["status"] = new_status
    elif "detailedStatus" in update_dict and update_dict["detailedStatus"]:
        # Infer status from detailed status
        high_level = None
        if "intakeComplete" in update_dict and update_dict.get("intakeComplete"):
            high_level = PacketHighLevelStatus.CLINICAL_REVIEW
        elif "validationComplete" in update_dict and update_dict.get("validationComplete"):
            high_level = PacketHighLevelStatus.CLINICAL_REVIEW
        new_status = map_detailed_status_to_internal(update_dict["detailedStatus"], high_level)
        packet_dict["status"] = new_status
    elif "intakeComplete" in update_dict and update_dict.get("intakeComplete"):
        # If intake is complete, move to validation (IN_REVIEW)
        if not update_dict.get("validationComplete"):
            packet_dict["status"] = PacketStatus.IN_REVIEW
    elif "validationComplete" in update_dict and update_dict.get("validationComplete"):
        # If validation is complete, move to clinical review
        packet_dict["status"] = PacketStatus.IN_REVIEW
    
    # Update updated_at timestamp
    packet_dict["updated_at"] = now
    
    # Preserve audit_log (don't overwrite it)
    if "audit_log" not in packet_dict:
        packet_dict["audit_log"] = packet.audit_log
    
    # Create new Packet instance with updated fields
    return Packet(**packet_dict)



