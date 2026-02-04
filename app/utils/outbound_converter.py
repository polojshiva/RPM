"""
Outbound Delivery Converter
Convert internal outbound delivery data to DTOs
"""
from typing import List
from app.models.outbound_dto import (
    OutboundDeliveryDTO,
    ChannelDeliveryStatusDTO,
    DeliveryStatusDTO,
    DeliveryChannelStatus,
)


def channel_status_to_dto(channel_dict: dict) -> ChannelDeliveryStatusDTO:
    """Convert internal channel status dict to DTO"""
    status_str = channel_dict.get("status", "N/A")
    # Handle enum or string
    if isinstance(status_str, DeliveryChannelStatus):
        status = status_str
    else:
        try:
            status = DeliveryChannelStatus(status_str)
        except ValueError:
            status = DeliveryChannelStatus.N_A
    
    return ChannelDeliveryStatusDTO(
        status=status,
        completedAt=channel_dict.get("completedAt"),
        confirmationId=channel_dict.get("confirmationId"),
        attempts=channel_dict.get("attempts"),
        lastAttempt=channel_dict.get("lastAttempt"),
        error=channel_dict.get("error"),
        nextRetry=channel_dict.get("nextRetry"),
        trackingNumber=channel_dict.get("trackingNumber"),
        reason=channel_dict.get("reason"),
    )


def delivery_status_to_dto(status_dict: dict) -> DeliveryStatusDTO:
    """Convert internal delivery status dict to DTO"""
    return DeliveryStatusDTO(
        providerFax=channel_status_to_dto(status_dict.get("providerFax", {})),
        providerPortal=channel_status_to_dto(status_dict.get("providerPortal", {})),
        esMD=channel_status_to_dto(status_dict.get("esMD", {})),
        memberMail=channel_status_to_dto(status_dict.get("memberMail", {})),
    )


def delivery_to_dto(delivery: dict) -> OutboundDeliveryDTO:
    """Convert internal delivery dict to OutboundDeliveryDTO"""
    letter_type_str = delivery.get("letterType")
    if isinstance(letter_type_str, str):
        from app.models.outbound_dto import LetterType
        try:
            letter_type = LetterType(letter_type_str)
        except ValueError:
            letter_type = LetterType.APPROVAL  # Default
    else:
        letter_type = letter_type_str
    
    priority_str = delivery.get("priority")
    if isinstance(priority_str, str):
        from app.models.outbound_dto import Priority
        try:
            priority = Priority(priority_str)
        except ValueError:
            priority = Priority.MEDIUM  # Default
    else:
        priority = priority_str
    
    return OutboundDeliveryDTO(
        caseId=delivery["caseId"],
        packetId=delivery["packetId"],
        patient=delivery["patient"],
        provider=delivery["provider"],
        letterType=letter_type,
        submittedAt=delivery["submittedAt"],
        providerFax=delivery["providerFax"],
        faxVerified=delivery.get("faxVerified", False),
        faxVerifiedBy=delivery["faxVerifiedBy"],
        faxVerifiedAt=delivery["faxVerifiedAt"],
        deliveryStatus=delivery_status_to_dto(delivery.get("deliveryStatus", {})),
        hasException=delivery.get("hasException", False),
        priority=priority,
    )


def deliveries_to_dto_list(deliveries: List[dict]) -> List[OutboundDeliveryDTO]:
    """Convert list of internal deliveries to DTO list"""
    return [delivery_to_dto(delivery) for delivery in deliveries]

