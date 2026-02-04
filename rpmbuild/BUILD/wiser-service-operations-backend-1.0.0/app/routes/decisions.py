"""
Decisions Routes
Endpoints for approve and dismissal decisions
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends, Query, Request, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.services.db import get_db
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.api import ApiResponse
from app.models.packet_decision_db import PacketDecisionDB
from app.models.send_integration_db import SendIntegrationDB
from app.services.decisions_service import DecisionsService
from app.services.blob_storage import BlobStorageClient, BlobStorageError
from app.services.workflow_orchestrator import WorkflowOrchestratorService
from app.config import settings
import tempfile
import uuid
import hashlib
import json
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/packets", tags=["Decisions"])


# Request/Response Models
class ApproveDecisionRequest(BaseModel):
    """Request model for approve decision"""
    notes: Optional[str] = None


class DismissalDecisionRequest(BaseModel):
    """Request model for dismissal decision"""
    denial_reason: str = Field(..., description="Denial reason code")
    denial_details: Dict[str, Any] = Field(..., description="Reason-specific structured data")
    notes: Optional[str] = None
    
    @field_validator('denial_reason')
    @classmethod
    def validate_denial_reason(cls, v: str) -> str:
        """Validate denial reason is one of allowed values"""
        allowed = ['MISSING_FIELDS', 'INVALID_PECOS', 'INVALID_HETS', 'PROCEDURE_NOT_SUPPORTED', 'NO_MEDICAL_RECORDS', 'OTHER']
        if v not in allowed:
            raise ValueError(f"denial_reason must be one of: {', '.join(allowed)}")
        return v


class DecisionResponse(BaseModel):
    """Response model for decision endpoints"""
    packet_decision_id: int
    packet_id: str
    document_id: str
    decision_type: str
    denial_reason: Optional[str] = None
    denial_details: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    linked_validation_run_ids: Optional[Dict[str, Optional[int]]] = None
    created_at: str
    created_by: str
    # New workflow fields
    operational_decision: Optional[str] = Field(None, description="Operational decision: PENDING, DISMISSAL, DISMISSAL_COMPLETE, DECISION_COMPLETE")
    clinical_decision: Optional[str] = Field(None, description="Clinical decision: PENDING, AFFIRM, NON_AFFIRM")
    is_active: Optional[bool] = Field(None, description="Whether this is the active decision record")
    # New workflow fields
    operational_decision: Optional[str] = Field(None, description="Operational decision: PENDING, DISMISSAL, DISMISSAL_COMPLETE, DECISION_COMPLETE")
    clinical_decision: Optional[str] = Field(None, description="Clinical decision: PENDING, AFFIRM, NON_AFFIRM")
    is_active: Optional[bool] = Field(None, description="Whether this is the active decision record")


@router.post(
    "/{packet_id}/documents/{doc_id}/decisions/approve",
    response_model=ApiResponse[DecisionResponse],
    status_code=status.HTTP_200_OK
)
async def approve_decision(
    packet_id: str,
    doc_id: str,
    request: ApproveDecisionRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Approve a packet/document and send to Clinical Ops
    
    Args:
        packet_id: External packet ID
        doc_id: External document ID
        request: Approve decision request (optional notes)
        
    Returns:
        Decision record with packet_decision_id
    """
    # Validate packet exists
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # CRITICAL: Refresh packet from database to get latest validation error flag
    # This ensures we check the most up-to-date validation status
    db.refresh(packet)
    
    # Check for field validation errors BEFORE creating decision
    # This prevents creating a decision if validation errors exist
    if hasattr(packet, 'has_field_validation_errors') and packet.has_field_validation_errors:
        from app.services.validation_persistence import get_field_validation_errors
        validation_data = get_field_validation_errors(packet.packet_id, db)
        field_errors = validation_data.get('field_errors', {}) if validation_data else {}
        
        error_summary = []
        for field, errors in field_errors.items():
            error_summary.append(f"{field}: {', '.join(errors)}")
        
        error_message = (
            f"Cannot approve packet: Field validation errors exist. "
            f"Please fix all validation errors before sending to Clinical Ops. "
            f"Errors: {'; '.join(error_summary) if error_summary else 'Unknown validation errors'}"
        )
        
        logger.error(
            f"Blocked approve decision for packet {packet.external_id}: {error_message}"
        )
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message
        )
    
    # Validate document exists and belongs to packet
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Get correlation_id from request state
    correlation_id = getattr(http_request.state, 'correlation_id', None)
    
    # Check for existing active decision (idempotency check)
    # This prevents duplicate decisions from rapid double-clicks or concurrent requests
    existing_active_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).first()
    
    if existing_active_decision:
        # Check if it was created very recently (within last 5 seconds)
        time_since_creation = (datetime.now(timezone.utc) - existing_active_decision.created_at).total_seconds()
        if time_since_creation < 5:
            logger.warning(
                f"Duplicate approve request detected for packet_id={packet_id}. "
                f"Existing decision created {time_since_creation:.2f} seconds ago. "
                f"Returning existing decision."
            )
            # Return existing decision instead of creating new one
            db.refresh(existing_active_decision)
            # Get packet and document for response
            existing_packet = db.query(PacketDB).filter(PacketDB.packet_id == existing_active_decision.packet_id).first()
            existing_document = db.query(PacketDocumentDB).filter(PacketDocumentDB.packet_document_id == existing_active_decision.packet_document_id).first()
            return ApiResponse(
                success=True,
                message="Decision already exists",
                data=DecisionResponse(
                    packet_decision_id=existing_active_decision.packet_decision_id,
                    packet_id=existing_packet.external_id if existing_packet else str(existing_active_decision.packet_id),
                    document_id=existing_document.external_id if existing_document else str(existing_active_decision.packet_document_id),
                    decision_type=existing_active_decision.decision_type,
                    denial_reason=existing_active_decision.denial_reason,
                    denial_details=existing_active_decision.denial_details,
                    notes=existing_active_decision.notes,
                    linked_validation_run_ids=existing_active_decision.linked_validation_run_ids,
                    operational_decision=existing_active_decision.operational_decision,
                    clinical_decision=existing_active_decision.clinical_decision,
                    is_active=existing_active_decision.is_active,
                    created_at=existing_active_decision.created_at.isoformat(),
                    created_by=existing_active_decision.created_by or current_user.email
                ),
                correlation_id=correlation_id
            )
    
    # Log decision
    logger.info(
        f"Approve decision requested: "
        f"packet_id={packet_id}, "
        f"doc_id={doc_id}, "
        f"user={current_user.email}"
    )
    
    try:
        # Create approve decision
        decision = DecisionsService.create_approve_decision(
            db=db,
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            notes=request.notes,
            correlation_id=correlation_id,
            created_by=current_user.email
        )
        
        # Update packet status using workflow orchestrator
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Pending - Clinical Review",
            validation_status="Validation Complete",
            release_lock=True
        )
        
        # Create validation record for audit trail
        WorkflowOrchestratorService.create_validation_record(
            db=db,
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            validation_status="Validation Complete",
            validation_type="FINAL",
            is_passed=True,
            validated_by=current_user.email
        )
        
        # Send to ClinicalOps outbox
        # NOTE: We already checked for validation errors above, but check again here as a safety net
        # Refresh packet one more time before sending to ensure we have the latest state
        db.refresh(packet)
        
        from app.services.clinical_ops_outbox_service import ClinicalOpsOutboxService
        try:
            outbox_record = ClinicalOpsOutboxService.send_case_ready_for_review(
                db=db,
                packet=packet,
                packet_document=document,
                created_by=current_user.email
            )
            logger.info(
                f"Sent CASE_READY_FOR_REVIEW to ClinicalOps: "
                f"message_id={outbox_record.message_id}, "
                f"packet_id={packet_id}"
            )
        except ValueError as e:
            # ValueError from send_case_ready_for_review means validation errors exist
            # This should not happen if our check above worked, but handle it anyway
            logger.error(
                f"Blocked CASE_READY_FOR_REVIEW to ClinicalOps for packet_id={packet_id}: {e}",
                exc_info=True
            )
            # Rollback the decision creation since we can't send to ClinicalOps
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            logger.error(
                f"Failed to send CASE_READY_FOR_REVIEW to ClinicalOps for packet_id={packet_id}: {e}",
                exc_info=True
            )
            # Don't fail the entire request if outbox write fails (non-validation errors)
            # The decision is already created and status is updated
        
        db.commit()
        db.refresh(packet)
        
        logger.info(
            f"Packet {packet_id} approved: "
            f"status=Pending - Clinical Review, "
            f"validation_status=Validation Complete, "
            f"operational_decision=PENDING, "
            f"lock released"
        )
        
        # Build response
        response_data = DecisionResponse(
            packet_decision_id=decision.packet_decision_id,
            packet_id=packet_id,
            document_id=doc_id,
            decision_type=decision.decision_type,
            denial_reason=None,
            denial_details=None,
            notes=decision.notes,
            linked_validation_run_ids=decision.linked_validation_run_ids,
            created_at=decision.created_at.isoformat(),
            created_by=decision.created_by or current_user.email,
            operational_decision=decision.operational_decision,
            clinical_decision=decision.clinical_decision,
            is_active=decision.is_active
        )
        
        return ApiResponse(
            success=True,
            data=response_data,
            message="Packet approved and sent to Clinical Ops",
            correlation_id=correlation_id
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error during approve decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during approve decision"
        )


@router.post(
    "/{packet_id}/documents/{doc_id}/decisions/dismissal",
    response_model=ApiResponse[DecisionResponse],
    status_code=status.HTTP_200_OK
)
async def dismissal_decision(
    packet_id: str,
    doc_id: str,
    request: DismissalDecisionRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Dismiss a packet/document with denial reason and details
    
    Args:
        packet_id: External packet ID
        doc_id: External document ID
        request: Dismissal decision request with denial_reason and denial_details
        
    Returns:
        Decision record with packet_decision_id
    """
    # Validate packet exists
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Validate document exists and belongs to packet
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Validate denial_details based on denial_reason
    denial_reason = request.denial_reason
    denial_details = request.denial_details
    
    if denial_reason == 'MISSING_FIELDS':
        if not isinstance(denial_details.get('missingFields'), list) or len(denial_details.get('missingFields', [])) == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="denial_details.missingFields must be a non-empty array for MISSING_FIELDS reason"
            )
    elif denial_reason == 'INVALID_PECOS':
        if not denial_details.get('explanation') or not denial_details.get('explanation').strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="denial_details.explanation is required for INVALID_PECOS reason"
            )
    elif denial_reason == 'INVALID_HETS':
        if not denial_details.get('explanation') or not denial_details.get('explanation').strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="denial_details.explanation is required for INVALID_HETS reason"
            )
    elif denial_reason == 'PROCEDURE_NOT_SUPPORTED':
        if not denial_details.get('procedureCode') or not denial_details.get('procedureCode').strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="denial_details.procedureCode is required for PROCEDURE_NOT_SUPPORTED reason"
            )
    elif denial_reason == 'NO_MEDICAL_RECORDS':
        if not denial_details.get('reason') or not denial_details.get('reason').strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="denial_details.reason is required for NO_MEDICAL_RECORDS reason"
            )
    elif denial_reason == 'OTHER':
        if not denial_details.get('reason') or not denial_details.get('reason').strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="denial_details.reason is required for OTHER reason"
            )
    
    # Get correlation_id from request state
    correlation_id = getattr(http_request.state, 'correlation_id', None)
    
    # Check for existing active dismissal (idempotency check)
    # This prevents duplicate dismissals from rapid double-clicks or concurrent requests
    existing_active_dismissal = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.decision_type == 'DISMISSAL',
        PacketDecisionDB.is_active == True
    ).first()
    
    if existing_active_dismissal:
        # Check if it was created very recently (within last 5 seconds)
        time_since_creation = (datetime.now(timezone.utc) - existing_active_dismissal.created_at).total_seconds()
        if time_since_creation < 5:
            logger.warning(
                f"Duplicate dismissal request detected for packet_id={packet_id}. "
                f"Existing dismissal created {time_since_creation:.2f} seconds ago. "
                f"Returning existing decision."
            )
            # Return existing decision instead of creating new one
            db.refresh(existing_active_dismissal)
            # Get packet and document for response
            existing_packet = db.query(PacketDB).filter(PacketDB.packet_id == existing_active_dismissal.packet_id).first()
            existing_document = db.query(PacketDocumentDB).filter(PacketDocumentDB.packet_document_id == existing_active_dismissal.packet_document_id).first()
            return ApiResponse(
                success=True,
                message="Dismissal already exists",
                data=DecisionResponse(
                    packet_decision_id=existing_active_dismissal.packet_decision_id,
                    packet_id=existing_packet.external_id if existing_packet else str(existing_active_dismissal.packet_id),
                    document_id=existing_document.external_id if existing_document else str(existing_active_dismissal.packet_document_id),
                    decision_type=existing_active_dismissal.decision_type,
                    denial_reason=existing_active_dismissal.denial_reason,
                    denial_details=existing_active_dismissal.denial_details,
                    notes=existing_active_dismissal.notes,
                    linked_validation_run_ids=existing_active_dismissal.linked_validation_run_ids,
                    operational_decision=existing_active_dismissal.operational_decision,
                    clinical_decision=existing_active_dismissal.clinical_decision,
                    is_active=existing_active_dismissal.is_active,
                    created_at=existing_active_dismissal.created_at.isoformat(),
                    created_by=existing_active_dismissal.created_by or current_user.email
                ),
                correlation_id=correlation_id
            )
    
    # Log decision
    logger.info(
        f"Dismissal decision requested: "
        f"packet_id={packet_id}, "
        f"doc_id={doc_id}, "
        f"denial_reason={denial_reason}, "
        f"user={current_user.email}"
    )
    
    try:
        # Create dismissal decision
        decision = DecisionsService.create_dismissal_decision(
            db=db,
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            denial_reason=denial_reason,
            denial_details=denial_details,
            notes=request.notes,
            correlation_id=correlation_id,
            created_by=current_user.email
        )
        
        # Set initial status before workflow starts
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Dismissal",
            validation_status="Validation Complete",
            release_lock=True
        )
        
        # Create validation record for audit trail
        WorkflowOrchestratorService.create_validation_record(
            db=db,
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            validation_status="Validation Complete",
            validation_type="FINAL",
            is_passed=True,
            validated_by=current_user.email
        )
        
        # Commit the decision first so it's persisted before workflow processing
        # This ensures the decision exists even if workflow fails
        db.commit()
        db.refresh(decision)
        
        # Process dismissal workflow (letter generation + ESMD payload + outbox)
        # Note: Status updates are handled inside process_dismissal
        # Note: process_dismissal will handle its own commits
        try:
            from app.services.dismissal_workflow_service import DismissalWorkflowService
            
            workflow_result = DismissalWorkflowService.process_dismissal(
                db=db,
                packet=packet,
                packet_decision=decision,
                created_by=current_user.email
            )
            
            logger.info(
                f"Dismissal workflow completed: "
                f"packet_id={packet_id}, "
                f"letter_status={workflow_result.get('letter_status', 'UNKNOWN')}, "
                f"outbox_message_id={workflow_result.get('letter_outbox_message_id')}"
            )
            # Refresh decision to get updated letter_status and other fields
            db.refresh(decision)
        except Exception as e:
            logger.error(
                f"Error in dismissal workflow for packet_id={packet_id}: {e}",
                exc_info=True
            )
            # Don't re-raise - allow dismissal to proceed even if letter generation fails
            # The decision is already committed, and letter can be uploaded manually
            # Just log the error and continue with response
            logger.warning(
                f"Dismissal decision created but workflow failed for packet_id={packet_id}. "
                f"Decision is saved. Letter can be uploaded manually via upload endpoint."
            )
            # Refresh decision even if workflow failed (to get current state)
            try:
                db.refresh(decision)
            except Exception:
                pass  # Ignore refresh errors if decision was rolled back
        
        db.refresh(packet)
        
        logger.info(
            f"Packet {packet_id} dismissed: "
            f"status={packet.detailed_status}, "
            f"validation_status={packet.validation_status}, "
            f"operational_decision=DISMISSAL, "
            f"lock released"
        )
        
        # Build response
        response_data = DecisionResponse(
            packet_decision_id=decision.packet_decision_id,
            packet_id=packet_id,
            document_id=doc_id,
            decision_type=decision.decision_type,
            denial_reason=decision.denial_reason,
            denial_details=decision.denial_details,
            notes=decision.notes,
            linked_validation_run_ids=decision.linked_validation_run_ids,
            created_at=decision.created_at.isoformat(),
            created_by=decision.created_by or current_user.email,
            operational_decision=decision.operational_decision,
            clinical_decision=decision.clinical_decision,
            is_active=decision.is_active
        )
        
        # Determine message based on letter status
        if hasattr(decision, 'letter_status') and decision.letter_status == 'PENDING':
            message = "Packet dismissed successfully. Letter generation is pending - please upload the letter manually."
        else:
            message = "Packet dismissed successfully"
        
        return ApiResponse(
            success=True,
            data=response_data,
            message=message,
            correlation_id=correlation_id
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error during dismissal decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during dismissal decision"
        )


@router.post(
    "/{packet_id}/affirm",
    response_model=ApiResponse[DecisionResponse],
    status_code=status.HTTP_200_OK
)
async def affirm_decision(
    packet_id: str,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Directly affirm a packet's clinical decision without sending to ClinicalOps.
    This bypasses the external ClinicalOps system entirely and immediately sets the decision to AFFIRM.
    No send_clinicalops record is created.
    
    Args:
        packet_id: External packet ID
        
    Returns:
        Updated decision record
    """
    # Validate packet exists
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Status validation removed - allow affirm from any status
    # Users can now affirm directly without requiring "Send to Clinical Ops" first
    
    # Check for existing active decision
    active_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).first()
    
    # Get document for the packet (needed if creating new decision)
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No document found for this packet"
        )
    
    # If decision exists, validate it's still PENDING
    if active_decision:
        if active_decision.clinical_decision not in ("PENDING", None):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Clinical decision already set to '{active_decision.clinical_decision}'. Cannot affirm."
            )
    
    # Get correlation_id from request state
    correlation_id = getattr(http_request.state, 'correlation_id', None)
    
    logger.info(
        f"Affirm decision requested: "
        f"packet_id={packet_id}, "
        f"user={current_user.email}, "
        f"existing_decision={active_decision is not None}"
    )
    
    try:
        # If decision exists, update it; otherwise create new one with AFFIRM
        if active_decision:
            # Update existing decision
            updated_decision = DecisionsService.update_clinical_decision(
                db=db,
                packet_id=packet.packet_id,
                new_clinical_decision="AFFIRM",
                decision_outcome="AFFIRM",
                created_by=current_user.email
            )
        else:
            # Create new decision directly with AFFIRM (bypasses ClinicalOps entirely)
            # First create approve decision (which sets clinical_decision to PENDING)
            decision = DecisionsService.create_approve_decision(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                notes=f"Direct affirm by {current_user.email} (bypassed ClinicalOps)",
                correlation_id=correlation_id,
                created_by=current_user.email
            )
            
            # Immediately update to AFFIRM (bypasses PENDING state)
            updated_decision = DecisionsService.update_clinical_decision(
                db=db,
                packet_id=packet.packet_id,
                new_clinical_decision="AFFIRM",
                decision_outcome="AFFIRM",
                created_by=current_user.email
            )
        
        # Update packet status to "Clinical Decision Received"
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Clinical Decision Received"
        )
        
        # NOTE: We do NOT create a send_clinicalops record at all
        # This is a direct affirm that bypasses ClinicalOps entirely
        # If a send_clinicalops record exists (from previous "Send to Clinical Ops"), we leave it as-is
        
        db.commit()
        db.refresh(packet)
        db.refresh(updated_decision)
        
        logger.info(
            f"Packet {packet_id} directly affirmed: "
            f"clinical_decision=AFFIRM, "
            f"status=Clinical Decision Received, "
            f"user={current_user.email}"
        )
        
        # Build response
        response_data = DecisionResponse(
            packet_decision_id=updated_decision.packet_decision_id,
            packet_id=packet_id,
            document_id=document.external_id if document else None,
            decision_type=updated_decision.decision_type,
            denial_reason=None,
            denial_details=None,
            notes=updated_decision.notes,
            linked_validation_run_ids=updated_decision.linked_validation_run_ids,
            created_at=updated_decision.created_at.isoformat(),
            created_by=updated_decision.created_by or current_user.email,
            operational_decision=updated_decision.operational_decision,
            clinical_decision=updated_decision.clinical_decision,
            is_active=updated_decision.is_active
        )
        
        return ApiResponse(
            success=True,
            data=response_data,
            message="Decision affirmed successfully",
            correlation_id=correlation_id
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error during affirm decision: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during affirm decision"
        )


@router.get(
    "/{packet_id}/documents/{doc_id}/validations/history",
    response_model=ApiResponse[List[Dict[str, Any]]],
    status_code=status.HTTP_200_OK
)
async def get_validation_history(
    packet_id: str,
    doc_id: str,
    validation_type: Optional[str] = Query(None, description="Filter by type: HETS or PECOS"),
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get validation run history for a document
    
    Returns metadata only (no PHI in request/response payloads)
    """
    # Validate packet exists
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Validate document exists
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Query validation runs
    from app.models.validation_run_db import ValidationRunDB
    from sqlalchemy import desc
    
    query = db.query(ValidationRunDB).filter(
        ValidationRunDB.packet_document_id == document.packet_document_id
    )
    
    if validation_type:
        if validation_type not in ['HETS', 'PECOS']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="validation_type must be 'HETS' or 'PECOS'"
            )
        query = query.filter(ValidationRunDB.validation_type == validation_type)
    
    runs = query.order_by(desc(ValidationRunDB.created_at)).limit(limit).all()
    
    # Return metadata only (no PHI)
    history = []
    for run in runs:
        history.append({
            "id": run.validation_run_id,
            "type": run.validation_type,
            "timestamp": run.created_at.isoformat(),
            "response_success": run.response_success,
            "response_status_code": run.response_status_code,
            "upstream_request_id": run.upstream_request_id,
            "duration_ms": run.duration_ms,
            "created_by": run.created_by
        })
    
    return ApiResponse(
        success=True,
        data=history,
        message=f"Retrieved {len(history)} validation runs"
    )


@router.get(
    "/{packet_id}/documents/{doc_id}/decisions/history",
    response_model=ApiResponse[Dict[str, Any]],
    status_code=status.HTTP_200_OK
)
async def get_decision_history(
    packet_id: str,
    doc_id: str,
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get decision history for a document
    """
    # Validate packet exists
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Validate document exists
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Query decisions
    from app.models.packet_decision_db import PacketDecisionDB
    from sqlalchemy import desc
    
    decisions = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_document_id == document.packet_document_id
    ).order_by(desc(PacketDecisionDB.created_at)).limit(limit).all()
    
    # Build response
    history = []
    for decision in decisions:
        history.append({
            "id": decision.packet_decision_id,
            "decision_type": decision.decision_type,
            "denial_reason": decision.denial_reason,
            "denial_details": decision.denial_details,  # Include for now (mostly non-PHI)
            "notes": decision.notes,
            "linked_validation_run_ids": decision.linked_validation_run_ids,
            "timestamp": decision.created_at.isoformat(),
            "created_by": decision.created_by
        })
    
    # Get latest decision
    latest = history[0] if history else None
    
    return ApiResponse(
        success=True,
        data={
            "decisions": history,
            "latest_decision": latest,
            "total": len(history)
        },
        message=f"Retrieved {len(history)} decisions"
    )


@router.post(
    "/{packet_id}/documents/{doc_id}/decisions/upload-letter",
    response_model=ApiResponse[Dict[str, Any]],
    status_code=status.HTTP_200_OK
)
async def upload_decision_letter(
    packet_id: str,
    doc_id: str,
    letter_file: UploadFile = File(..., description="PDF letter file"),
    http_request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload a manually created decision letter (for dismissals when letter generation is pending).
    
    This endpoint allows users to upload a manually created letter when:
    - Letter generation endpoint is not configured
    - Letter generation failed
    - Letter status is PENDING
    
    The uploaded letter will be processed the same way as an API-generated letter:
    - Uploaded to blob storage
    - Letter metadata stored in packet_decision
    - Sent to integration outbox
    - Packet status updated to completion
    
    Args:
        packet_id: External packet ID
        doc_id: External document ID
        letter_file: PDF file containing the decision letter
        
    Returns:
        Success response with letter metadata and updated packet status
    """
    # Validate packet exists
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Validate document exists
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Get active decision (should be dismissal)
    decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).first()
    
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active decision found for this packet"
        )
    
    # Validate file type
    if not letter_file.filename or not letter_file.filename.endswith('.pdf'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported"
        )
    
    # Get correlation_id from request state
    correlation_id = getattr(http_request.state, 'correlation_id', None) if http_request else None
    
    logger.info(
        f"Uploading manual letter for packet_id={packet_id} | "
        f"decision_id={decision.packet_decision_id} | "
        f"filename={letter_file.filename} | "
        f"user={current_user.email}"
    )
    
    temp_file_path = None
    try:
        # Save uploaded file to temp location
        from pathlib import Path
        temp_dir = Path(tempfile.gettempdir()) / "service_ops_letter_upload"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file_path = temp_dir / f"letter_{uuid.uuid4().hex[:8]}_{letter_file.filename}"
        
        # Read file content
        content = await letter_file.read()
        file_size = len(content)
        
        # Write to temp file
        with open(temp_file_path, 'wb') as f:
            f.write(content)
        
        # Calculate SHA256 hash
        file_hash = hashlib.sha256(content).hexdigest()
        
        # Upload to blob storage
        container_name = settings.azure_storage_dest_container
        if not container_name:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Azure storage container not configured"
            )
        
        # Create blob path: letter-generation/YYYY/MM-DD/{decision_tracking_id}/letter.pdf
        now = datetime.now(timezone.utc)
        date_prefix = now.strftime("%Y/%m-%d")
        blob_path = f"letter-generation/{date_prefix}/{packet.decision_tracking_id}/{letter_file.filename}"
        
        blob_client = BlobStorageClient(
            storage_account_url=settings.storage_account_url,
            container_name=container_name,
            connection_string=settings.azure_storage_connection_string
        )
        
        # Upload file
        blob_client.upload_file(
            local_path=str(temp_file_path),
            dest_blob_path=blob_path,
            container_name=container_name,
            content_type="application/pdf"
        )
        
        # Generate blob URL
        blob_url = blob_client.resolve_blob_url(blob_path, container_name=container_name)
        
        # Create letter metadata (similar to LetterGen API response)
        letter_metadata = {
            "blob_url": blob_url,
            "filename": letter_file.filename,
            "file_size_bytes": file_size,
            "template_used": "manual_upload",
            "generated_at": now.isoformat(),
            "inbound_json_blob_url": None,
            "inbound_metadata_blob_url": None,
            "uploaded_by": current_user.email,
            "uploaded_at": now.isoformat(),
            "sha256": file_hash,
            "manual_upload": True,
            "note": "Letter uploaded manually by user"
        }
        
        # Update packet_decision
        decision.letter_owner = 'SERVICE_OPS'
        decision.letter_status = 'READY'
        decision.letter_package = letter_metadata
        decision.letter_generated_at = now
        
        # Update packet status to "Generate Decision Letter - Complete"
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Generate Decision Letter - Complete"
        )
        
        # Send letter to Integration outbox (same as API-generated letter)
        letter_structured_payload = {
            "message_type": "LETTER_PACKAGE",
            "decision_tracking_id": str(packet.decision_tracking_id),
            "letter_package": letter_metadata,
            "medical_documents": [],
            "packet_id": packet.packet_id,
            "external_id": packet.external_id,
            "letter_type": decision.decision_type.lower() if decision.decision_type else "dismissal",
            "attempt_count": 1,
            "payload_version": 1,
            "correlation_id": str(uuid.uuid4()),
            "created_at": now.isoformat(),
            "created_by": current_user.email
        }
        
        # Generate payload hash
        letter_payload_json = json.dumps(letter_structured_payload, sort_keys=True)
        letter_payload_hash = hashlib.sha256(letter_payload_json.encode('utf-8')).hexdigest()
        letter_structured_payload["payload_hash"] = letter_payload_hash
        
        letter_outbox_record = SendIntegrationDB(
            decision_tracking_id=packet.decision_tracking_id,
            payload=letter_structured_payload,
            message_status_id=1,  # INGESTED
            correlation_id=uuid.UUID(letter_structured_payload["correlation_id"]),
            attempt_count=1,
            payload_hash=letter_payload_hash,
            payload_version=1,
            audit_user=current_user.email,
            audit_timestamp=now
        )
        db.add(letter_outbox_record)
        db.flush()
        
        decision.letter_sent_to_integration_at = now
        decision.letter_status = 'SENT'
        
        # Update packet status
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Send Decision Letter - Pending"
        )
        
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Send Decision Letter - Complete"
        )
        
        # Update operational decision to DISMISSAL_COMPLETE if it's a dismissal
        if decision.decision_type == 'DISMISSAL':
            DecisionsService.update_operational_decision(
                db=db,
                packet_id=packet.packet_id,
                new_operational_decision='DISMISSAL_COMPLETE',
                created_by=current_user.email
            )
            
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Dismissal Complete"
            )
        
        db.commit()
        db.refresh(letter_outbox_record)
        
        logger.info(
            f"Manual letter uploaded successfully for packet_id={packet_id} | "
            f"blob_url={blob_url} | "
            f"letter_status=SENT | "
            f"outbox_message_id={letter_outbox_record.message_id}"
        )
        
        return ApiResponse(
            success=True,
            data={
                "letter_metadata": letter_metadata,
                "letter_outbox_message_id": letter_outbox_record.message_id,
                "packet_status": packet.detailed_status,
                "letter_status": decision.letter_status
            },
            message="Letter uploaded and processed successfully",
            correlation_id=correlation_id
        )
        
    except BlobStorageError as e:
        logger.error(f"Blob storage error during letter upload: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload letter to blob storage: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error during letter upload: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload letter: {str(e)}"
        )
    finally:
        # Cleanup temp file
        if temp_file_path and temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_file_path}: {e}")

