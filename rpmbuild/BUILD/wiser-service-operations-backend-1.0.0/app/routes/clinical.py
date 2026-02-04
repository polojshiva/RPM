"""
Clinical Routes
Endpoints for clinical case management
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, status, Depends, Query
from app.models.user import User, UserRole
from app.models.clinical_dto import (
    ClinicalCaseListResponse,
    ClinicalCaseResponse,
    MDReviewResponse,
    MDReviewSubmissionDTO,
    CaseStatus,
    Priority,
    ReviewType,
)
from app.auth.dependencies import get_current_user, require_roles

from app.utils.clinical_converter import (
    cases_to_item_dto_list,
    case_to_detail_dto,
)
from app.utils.audit_logger import log_packet_event


router = APIRouter(prefix="/api/clinical", tags=["Clinical"])


@router.get("/cases", response_model=ClinicalCaseListResponse)
async def list_clinical_cases(
    status: Optional[str] = Query(None, alias="status"),
    assignedTo: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """
    List clinical cases with optional filtering
    """

    
    # TODO: Replace with actual DB query for clinical cases and filtering
    # Example: cases = db.query(ClinicalCase).filter(...)
    cases = []  # Placeholder: implement actual DB logic
    case_dtos = cases_to_item_dto_list(cases)
    return ClinicalCaseListResponse(
        success=True,
        data=case_dtos,
        total=len(case_dtos),
    )


@router.get("/cases/{case_id}", response_model=ClinicalCaseResponse)
async def get_clinical_case(
    case_id: str,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER, UserRole.COORDINATOR])),
):
    """
    Get detailed clinical case by caseId or uniqueId
    """

    
    # TODO: Replace with actual DB query for clinical case by ID
    case = None  # Placeholder: implement actual DB logic
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clinical case {case_id} not found",
        )
    case_dto = case_to_detail_dto(case)
    return ClinicalCaseResponse(
        success=True,
        data=case_dto,
    )


@router.post("/cases/{case_id}/md-review", response_model=MDReviewResponse)
async def submit_md_review_decision(
    case_id: str,
    submission: MDReviewSubmissionDTO,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER])),
):
    """
    Submit MD review decision (agree/disagree with nurse recommendation)
    """

    
    # Check if case exists
    case = get_clinical_case_by_id(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clinical case {case_id} not found",
        )
    
    # Submit MD review
    updated_case = submit_md_review(
        case_id=case_id,
        decision=submission.decision,
        feedback=submission.feedback,
    )
    
    if not updated_case:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update clinical case",
        )
    # TODO: Replace with actual DB update logic for MD review submission
    # Example: update clinical case in DB and fetch updated record
    # updated_case = None  # Placeholder: implement actual DB logic
    # if not updated_case:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail="Failed to submit MD review",
    #     )
    
    case_dto = case_to_detail_dto(updated_case)
    
    return MDReviewResponse(
        success=True,
        data=case_dto,
        message="MD review submitted successfully",
    )

