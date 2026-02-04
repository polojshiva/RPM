"""
Outbound Routes
Endpoints for outbound delivery management
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, status, Depends, Query
from app.models.user import User, UserRole
from app.models.outbound_dto import (
    OutboundDeliveryListResponse,
    OutboundDeliveryResponse,
    OutboundDeliveryUpdateDTO,
)
from app.auth.dependencies import get_current_user, require_roles

from app.utils.outbound_converter import (
    deliveries_to_dto_list,
    delivery_to_dto,
)
from app.utils.audit_logger import log_packet_event


router = APIRouter(prefix="/api/outbound", tags=["Outbound"])


@router.get("/deliveries", response_model=OutboundDeliveryListResponse)
async def list_deliveries(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    status: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query("asc", regex="^(asc|desc)$"),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """
    List outbound deliveries with optional filtering and pagination
    """
    # Implement DB query for outbound deliveries with optional filtering and pagination
    query = db.query(OutboundDelivery)
    if status:
        query = query.filter(OutboundDelivery.status == status)
    if assigned_to:
        query = query.filter(OutboundDelivery.assigned_to == assigned_to)
    total = query.count()
    if sort_by:
        sort_column = getattr(OutboundDelivery, sort_by, None)
        if sort_column is not None:
            if sort_order == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
    deliveries = query.offset((page - 1) * page_size).limit(page_size).all()
    delivery_dtos = deliveries_to_dto_list(deliveries)
    return OutboundDeliveryListResponse(
        success=True,
        data=delivery_dtos,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/deliveries/{delivery_id}", response_model=OutboundDeliveryResponse)
async def get_delivery(
    delivery_id: str,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """
    Get detailed outbound delivery by caseId or packetId
    """
    # Implement DB query for outbound delivery by ID
    delivery = db.query(OutboundDelivery).filter(OutboundDelivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outbound delivery {delivery_id} not found",
        )
    delivery_dto = delivery_to_dto(delivery)
    return OutboundDeliveryResponse(
        success=True,
        data=delivery_dto,
    )


@router.patch("/deliveries/{delivery_id}", response_model=OutboundDeliveryResponse)
async def update_delivery(
    delivery_id: str,
    update: OutboundDeliveryUpdateDTO,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER])),
):
    """
    Update outbound delivery (e.g., mark resolved, update status)
    """
    # Implement DB update logic for outbound delivery
    delivery = db.query(OutboundDelivery).filter(OutboundDelivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outbound delivery {delivery_id} not found",
        )
    update_dict = update.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(delivery, field, value)
    db.commit()
    db.refresh(delivery)
    # Log audit event (keep as is)
    log_packet_event(
        packet_id=getattr(delivery, "packetId", "unknown"),
        action="outbound_delivery_updated",
        user_id=current_user.id,
        user_name=current_user.username,
        details={
            "delivery_id": delivery_id,
            "mark_resolved": update.markResolved,
            "has_updates": True,
        },
    )
    delivery_dto = delivery_to_dto(delivery)
    return OutboundDeliveryResponse(
        success=True,
        data=delivery_dto,
        message="Delivery updated successfully",
    )

