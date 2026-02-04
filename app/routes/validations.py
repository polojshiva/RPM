"""
Validations Routes
Endpoints for HETS and PECOS validation services
"""
import time
import logging
from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from sqlalchemy.orm import Session
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.services.db import get_db
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.api import ApiResponse
from app.models.validations_dto import (
    HetsValidationRequest,
    HetsValidationResponse,
    PecosValidationResponse
)
from app.services.validations_service import ValidationsService, ValidationServiceError
from app.services.validations_persistence import ValidationsPersistenceService
from app.services.workflow_orchestrator import WorkflowOrchestratorService
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/packets", tags=["Validations"])


def get_validations_service() -> ValidationsService:
    """Dependency to get ValidationsService instance"""
    return ValidationsService()


@router.post(
    "/{packet_id}/documents/{doc_id}/validations/hets",
    response_model=ApiResponse[HetsValidationResponse],
    status_code=status.HTTP_200_OK
)
async def validate_hets(
    packet_id: str,
    doc_id: str,
    request: HetsValidationRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    validations_service: ValidationsService = Depends(get_validations_service)
):
    """
    Validate eligibility using HETS service
    
    Validates that the packet and document exist, then proxies the request
    to the HETS service and returns the raw JSON response.
    Persists the validation run to database for audit trail.
    
    Args:
        packet_id: External packet ID
        doc_id: External document ID
        request: HETS validation request payload
        
    Returns:
        Raw JSON response from HETS service (passthrough) + validation_run_id
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
    
    # Get correlation_id from request state (set by middleware)
    correlation_id = getattr(http_request.state, 'correlation_id', None)
    
    # Log validation request (without PHI)
    logger.info(
        f"HETS validation requested: "
        f"packet_id={packet_id}, "
        f"doc_id={doc_id}, "
        f"payer={request.payer}, "
        f"provider_npi={request.provider.npi[:3]}***, "
        f"user={current_user.email}"
    )
    
    # Get criteria from request or settings (auto-populate if not provided, default to "Production")
    criteria = request.criteria
    if not criteria:
        try:
            criteria = settings.get_hets_criteria()
        except (ValueError, AttributeError):
            # Default to "Production" if not configured
            criteria = "Production"
    
    # Prepare request payload for persistence
    request_payload = {
        "payer": request.payer,
        "provider": {"npi": request.provider.npi},
        "patient": {
            "mbi": request.patient.mbi,
            "dob": request.patient.dob,
            "lastName": request.patient.lastName,
            "firstName": request.patient.firstName
        },
        "criteria": criteria,
        "dateOfService": request.dateOfService
    }
    
    # Update packet validation status to "Validation In Progress"
    WorkflowOrchestratorService.update_packet_status(
        db=db,
        packet=packet,
        new_status=packet.detailed_status,  # Keep current detailed_status
        validation_status="Validation In Progress"
    )
    
    # Create validation audit record for "In Progress"
    WorkflowOrchestratorService.create_validation_record(
        db=db,
        packet_id=packet.packet_id,
        packet_document_id=document.packet_document_id,
        validation_status="Validation In Progress",
        validation_type="HETS",
        validated_by=current_user.email,
        update_reason="HETS validation started"
    )
    db.commit()
    
    # Start timer
    start_time = time.time()
    
    # Call HETS service
    try:
        result = await validations_service.validate_hets(
            payer=request.payer,
            provider_npi=request.provider.npi,
            patient_mbi=request.patient.mbi,
            patient_dob=request.patient.dob,
            patient_last_name=request.patient.lastName,
            patient_first_name=request.patient.firstName,
            criteria=criteria,
            date_of_service=request.dateOfService
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Extract upstream request ID if present
        upstream_request_id = result.get('request_id') if isinstance(result, dict) else None
        
        # Determine response success
        response_success = result.get('success') if isinstance(result, dict) else True
        response_status_code = 200  # Success if we got here
        
        # Persist validation run (don't determine pass/fail automatically - user will decide)
        validation_run = ValidationsPersistenceService.create_validation_run(
            db=db,
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            validation_type='HETS',
            request_payload=request_payload,
            response_payload=result,
            response_status_code=response_status_code,
            response_success=response_success,
            upstream_request_id=upstream_request_id,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            created_by=current_user.email
        )
        
        # Keep validation status as "Validation In Progress" - user will mark as valid/invalid
        # Don't create final validation record yet - wait for user decision
        
        db.commit()
        
        # Return response with validation_run_id (no validation_status or is_passed - user decides)
        return ApiResponse(
            success=True,
            data=result,  # Passthrough raw JSON
            message="HETS validation completed successfully. Please review and mark as Valid or Invalid.",
            validation_run_id=validation_run.validation_run_id  # Include in response
        )
    
    except ValidationServiceError as e:
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Update packet validation status to "Validation Failed"
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status=packet.detailed_status,
            validation_status="Validation Failed"
        )
        
        # Persist failed validation run
        try:
            validation_run = ValidationsPersistenceService.create_validation_run(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_type='HETS',
                request_payload=request_payload,
                response_payload=None,
                response_status_code=e.status_code if hasattr(e, 'status_code') else 502,
                response_success=False,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                created_by=current_user.email
            )
            
            # Create validation audit record for failure
            WorkflowOrchestratorService.create_validation_record(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_status="Validation Failed",
                validation_type="HETS",
                validation_errors={"error": str(e)},
                is_passed=False,
                validated_by=current_user.email,
                update_reason=f"HETS validation failed: {str(e)}"
            )
            # Ensure the session is committed before raising HTTPException
            db.commit()
        except Exception as persist_error:
            logger.error(f"Failed to persist failed HETS validation run: {persist_error}")
            db.rollback()
        
        logger.error(f"HETS validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Update packet validation status to "Validation Failed"
        try:
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status=packet.detailed_status,
                validation_status="Validation Failed"
            )
        except Exception:
            pass  # Don't fail if status update fails
        
        # Persist failed validation run
        try:
            validation_run = ValidationsPersistenceService.create_validation_run(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_type='HETS',
                request_payload=request_payload,
                response_payload=None,
                response_status_code=500,
                response_success=False,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                created_by=current_user.email
            )
            
            # Create validation audit record for failure
            WorkflowOrchestratorService.create_validation_record(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_status="Validation Failed",
                validation_type="HETS",
                validation_errors={"error": str(e)},
                is_passed=False,
                validated_by=current_user.email,
                update_reason=f"Unexpected error during HETS validation: {str(e)}"
            )
            db.commit()
        except Exception as persist_error:
            logger.error(f"Failed to persist failed HETS validation run: {persist_error}")
            db.rollback()
        
        logger.exception(f"Unexpected error during HETS validation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during HETS validation"
        )


@router.get(
    "/{packet_id}/documents/{doc_id}/validations/pecos",
    response_model=ApiResponse[PecosValidationResponse],
    status_code=status.HTTP_200_OK
)
async def validate_pecos(
    packet_id: str,
    doc_id: str,
    npi: str = Query(..., description="Provider NPI (10 digits)"),
    http_request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    validations_service: ValidationsService = Depends(get_validations_service)
):
    """
    Validate provider enrollment using PECOS service
    
    Validates that the packet and document exist, then proxies the request
    to the PECOS service and returns the raw JSON response.
    Persists the validation run to database for audit trail.
    
    Args:
        packet_id: External packet ID
        doc_id: External document ID
        npi: Provider NPI (10 digits) - query parameter
        
    Returns:
        Raw JSON response from PECOS service (passthrough) + validation_run_id
    """
    # Validate NPI format
    npi_clean = ''.join(filter(str.isdigit, str(npi)))
    if len(npi_clean) != 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NPI must be exactly 10 digits"
        )
    
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
    
    # Get correlation_id from request state (set by middleware)
    correlation_id = getattr(http_request.state, 'correlation_id', None) if http_request else None
    
    # Log validation request (without PHI)
    logger.info(
        f"PECOS validation requested: "
        f"packet_id={packet_id}, "
        f"doc_id={doc_id}, "
        f"npi={npi_clean[:3]}***, "
        f"user={current_user.email}"
    )
    
    # Prepare request payload for persistence
    request_payload = {"npi": npi_clean}
    
    # Update packet validation status to "Validation In Progress"
    WorkflowOrchestratorService.update_packet_status(
        db=db,
        packet=packet,
        new_status=packet.detailed_status,  # Keep current detailed_status
        validation_status="Validation In Progress"
    )
    
    # Create validation audit record for "In Progress"
    WorkflowOrchestratorService.create_validation_record(
        db=db,
        packet_id=packet.packet_id,
        packet_document_id=document.packet_document_id,
        validation_status="Validation In Progress",
        validation_type="PECOS",
        validated_by=current_user.email,
        update_reason="PECOS validation started"
    )
    db.commit()
    
    # Start timer
    start_time = time.time()
    
    # Call PECOS service
    try:
        result = await validations_service.validate_pecos(npi=npi_clean)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Determine response success
        response_success = result.get('success') if isinstance(result, dict) else True
        response_status_code = 200  # Success if we got here
        
        # Persist validation run (don't determine pass/fail automatically - user will decide)
        validation_run = ValidationsPersistenceService.create_validation_run(
            db=db,
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            validation_type='PECOS',
            request_payload=request_payload,
            response_payload=result,
            response_status_code=response_status_code,
            response_success=response_success,
            normalized_npi=npi_clean,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            created_by=current_user.email
        )
        
        # Keep validation status as "Validation In Progress" - user will mark as valid/invalid
        # Don't create final validation record yet - wait for user decision
        
        db.commit()
        
        # Return response with validation_run_id (no validation_status or is_passed - user decides)
        response = ApiResponse(
            success=True,
            data=result,  # Passthrough raw JSON
            message="PECOS validation completed successfully. Please review and mark as Valid or Invalid.",
            validation_run_id=validation_run.validation_run_id,  # Include in response
            correlation_id=correlation_id
        )
        return response
    
    except ValidationServiceError as e:
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Update packet validation status to "Validation Failed"
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status=packet.detailed_status,
            validation_status="Validation Failed"
        )
        
        # Persist failed validation run
        try:
            validation_run = ValidationsPersistenceService.create_validation_run(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_type='PECOS',
                request_payload=request_payload,
                response_payload=None,
                response_status_code=e.status_code if hasattr(e, 'status_code') else 502,
                response_success=False,
                normalized_npi=npi_clean,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                created_by=current_user.email
            )
            
            # Create validation audit record for failure
            WorkflowOrchestratorService.create_validation_record(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_status="Validation Failed",
                validation_type="PECOS",
                validation_errors={"error": str(e)},
                is_passed=False,
                validated_by=current_user.email,
                update_reason=f"PECOS validation failed: {str(e)}"
            )
            # Ensure the session is committed before raising HTTPException
            db.commit()
        except Exception as persist_error:
            logger.error(f"Failed to persist failed PECOS validation run: {persist_error}")
            db.rollback()
        
        logger.error(f"PECOS validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Update packet validation status to "Validation Failed"
        try:
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status=packet.detailed_status,
                validation_status="Validation Failed"
            )
        except Exception:
            pass  # Don't fail if status update fails
        
        # Persist failed validation run
        try:
            validation_run = ValidationsPersistenceService.create_validation_run(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_type='PECOS',
                request_payload=request_payload,
                response_payload=None,
                response_status_code=500,
                response_success=False,
                normalized_npi=npi_clean,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                created_by=current_user.email
            )
            
            # Create validation audit record for failure
            WorkflowOrchestratorService.create_validation_record(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                validation_status="Validation Failed",
                validation_type="PECOS",
                validation_errors={"error": str(e)},
                is_passed=False,
                validated_by=current_user.email,
                update_reason=f"Unexpected error during PECOS validation: {str(e)}"
            )
            db.commit()
        except Exception as persist_error:
            logger.error(f"Failed to persist failed PECOS validation run: {persist_error}")
            db.rollback()
        
        logger.exception(f"Unexpected error during PECOS validation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during PECOS validation"
        )


@router.post(
    "/{packet_id}/documents/{doc_id}/validations/{validation_type}/mark-result",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_200_OK
)
async def mark_validation_result(
    packet_id: str,
    doc_id: str,
    validation_type: str,
    is_passed: bool = Query(..., description="True if validation passed, False if failed"),
    notes: str = Query(None, description="Optional notes about the validation decision"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mark validation result as Valid or Invalid after user review
    
    Args:
        packet_id: External packet ID
        doc_id: External document ID
        validation_type: 'HETS' or 'PECOS'
        is_passed: True if validation passed, False if failed
        notes: Optional notes about the decision
        
    Returns:
        Success response with updated validation status
    """
    # Validate validation_type
    if validation_type.upper() not in ['HETS', 'PECOS']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="validation_type must be 'HETS' or 'PECOS'"
        )
    
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
    
    # Get the latest validation run for this validation type
    from app.models.validation_run_db import ValidationRunDB
    latest_run = db.query(ValidationRunDB).filter(
        ValidationRunDB.packet_document_id == document.packet_document_id,
        ValidationRunDB.validation_type == validation_type.upper()
    ).order_by(ValidationRunDB.created_at.desc()).first()
    
    if not latest_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {validation_type} validation run found for this document"
        )
    
    # Determine validation status based on is_passed
    validation_status = "Validation Complete" if is_passed else "Validation Failed"
    
    # Update packet validation status
    WorkflowOrchestratorService.update_packet_status(
        db=db,
        packet=packet,
        new_status=packet.detailed_status,  # Keep current detailed_status
        validation_status=validation_status
    )
    
    # Create validation audit record for user's decision
    validation_record = WorkflowOrchestratorService.create_validation_record(
        db=db,
        packet_id=packet.packet_id,
        packet_document_id=document.packet_document_id,
        validation_status=validation_status,
        validation_type=validation_type.upper(),
        validation_result=latest_run.response_payload,
        is_passed=is_passed,
        validated_by=current_user.email,
        update_reason=f"User marked {validation_type} validation as {'Valid' if is_passed else 'Invalid'}" + (f": {notes}" if notes else "")
    )
    db.commit()
    
    logger.info(
        f"User marked {validation_type} validation result: "
        f"packet_id={packet_id}, "
        f"is_passed={is_passed}, "
        f"user={current_user.email}"
    )
    
    return ApiResponse(
        success=True,
        data={
            "validation_status": validation_status,
            "is_passed": is_passed,
            "validation_type": validation_type.upper(),
            "validated_by": current_user.email,
            "validated_at": validation_record.validated_at.isoformat()
        },
        message=f"{validation_type} validation marked as {'Valid' if is_passed else 'Invalid'}"
    )


@router.post(
    "/{packet_id}/documents/{doc_id}/validations/{validation_type}/mark-status",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_200_OK
)
async def mark_validation_status(
    packet_id: str,
    doc_id: str,
    validation_type: str,
    is_passed: bool = Query(..., description="True if validation passed, False if failed"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mark validation as Valid or Invalid after user review
    
    Args:
        packet_id: External packet ID
        doc_id: External document ID
        validation_type: 'HETS' or 'PECOS'
        is_passed: True if user marked as valid, False if invalid
        
    Returns:
        Success response with updated validation status
    """
    if validation_type not in ['HETS', 'PECOS']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="validation_type must be 'HETS' or 'PECOS'"
        )
    
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
    
    # Get the latest validation run for this type
    from app.models.validation_run_db import ValidationRunDB
    latest_run = db.query(ValidationRunDB).filter(
        ValidationRunDB.packet_id == packet.packet_id,
        ValidationRunDB.packet_document_id == document.packet_document_id,
        ValidationRunDB.validation_type == validation_type
    ).order_by(ValidationRunDB.created_at.desc()).first()
    
    if not latest_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {validation_type} validation run found for this document"
        )
    
    # Determine validation status
    validation_status = "Validation Complete" if is_passed else "Validation Failed"
    
    # Update packet validation status
    WorkflowOrchestratorService.update_packet_status(
        db=db,
        packet=packet,
        new_status=packet.detailed_status,  # Keep current detailed_status
        validation_status=validation_status
    )
    
    # Create validation audit record with user's decision
    validation_record = WorkflowOrchestratorService.create_validation_record(
        db=db,
        packet_id=packet.packet_id,
        packet_document_id=document.packet_document_id,
        validation_status=validation_status,
        validation_type=validation_type,
        validation_result=latest_run.response_payload,
        is_passed=is_passed,
        validated_by=current_user.email,
        update_reason=f"User marked {validation_type} validation as {'Valid' if is_passed else 'Invalid'}"
    )
    db.commit()
    
    logger.info(
        f"User {current_user.email} marked {validation_type} validation as "
        f"{'Valid' if is_passed else 'Invalid'} for packet_id={packet_id}"
    )
    
    return ApiResponse(
        success=True,
        data={
            "validation_status": validation_status,
            "is_passed": is_passed,
            "validation_type": validation_type,
            "validated_by": current_user.email
        },
        message=f"{validation_type} validation marked as {'Valid' if is_passed else 'Invalid'}"
    )

