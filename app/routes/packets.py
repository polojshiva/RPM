"""
Packet Routes
CRUD operations for packet management
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from app.models.user import User, UserRole
from app.models.packet import (
    Packet,
    PacketStatus,
    PacketCreate,
    PacketUpdate,
    PacketResponse,
    PacketListResponse,
    AuditLogEntry,
)
from app.models.packet_dto import (
    PacketDTO,
    PacketDTOResponse,
    PacketDTOListResponse,
    PacketDTOUpdate,
    PacketHighLevelStatus,
)
from app.models.utn_dto import (
    UtnFailDetailsDTO,
    ResendToEsmdRequest,
    ResendToEsmdResponse,
)
from app.models.document_dto import DocumentListResponse
from app.models.letter_dto import LetterListResponse, LetterResponse
from app.models.ocr_extraction_dto import (
    OCRExtractionResponse,
    DocumentClassificationResponse,
    DocumentClassification,
)
from app.models.api import ApiResponse
from app.auth.dependencies import get_current_user, require_roles
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, cast, String
from fastapi import Depends
from app.services.db import get_db
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_decision_db import PacketDecisionDB
from app.utils.healthcare_validation import validate_npi
from app.utils.audit_logger import log_packet_event
from app.utils.packet_converter import packet_to_dto
from app.utils.packet_update import apply_dto_update_to_packet
from app.utils.document_converter import documents_to_dto_list


router = APIRouter(prefix="/api/packets", tags=["Packets"])


class FilterOptionsResponse(BaseModel):
    """Response model for filter options endpoint"""
    detailed_statuses: List[str]
    validation_statuses: List[str]
    operational_decisions: List[str]
    clinical_decisions: List[str]


@router.get("/filter-options", response_model=ApiResponse[FilterOptionsResponse])
async def get_filter_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all possible filter options (all allowed values from schema, not just what's in DB).
    Returns all possible values for status and decision fields based on CHECK constraints.
    """
    try:
        # Return all possible values from CHECK constraints/enums (not just what's currently in DB)
        # These match the CHECK constraints in migration 017
        
        # All possible detailed_status values (from migration 017 CHECK constraint)
        detailed_statuses = [
            'Pending - New',
            'Intake',
            'Validation',
            'Pending - Clinical Review',
            'Clinical Decision Received',
            'Pending - UTN',
            'UTN Received',
            'Generate Decision Letter - Pending',
            'Generate Decision Letter - Complete',
            'Send Decision Letter - Pending',
            'Send Decision Letter - Complete',
            'Decision Complete',
            'Dismissal',
            'Dismissal Complete'
        ]
        
        # All possible validation_status values (from migration 017 CHECK constraint)
        validation_statuses = [
            'Pending - Validation',
            'Validation In Progress',
            'Pending - Manual Review',
            'Validation Updated',
            'Validation Complete',
            'Validation Failed'
        ]
        
        # All possible operational_decision values (from packet_decision_db model)
        operational_decisions = [
            'PENDING',
            'DISMISSAL',
            'DISMISSAL_COMPLETE',
            'DECISION_COMPLETE'
        ]
        
        # All possible clinical_decision values (from packet_decision_db model)
        clinical_decisions = [
            'PENDING',
            'AFFIRM',
            'NON_AFFIRM'
        ]
        
        return ApiResponse(
            success=True,
            data=FilterOptionsResponse(
                detailed_statuses=detailed_statuses,
                validation_statuses=validation_statuses,
                operational_decisions=operational_decisions,
                clinical_decisions=clinical_decisions
            )
        )
    except Exception as e:
        logger.error(f"Error fetching filter options: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch filter options: {str(e)}"
        )



def get_client_ip(request: Request) -> str:
    """Extract client IP from request"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# --- SQLAlchemy-based packet operations (stubs) ---
def get_packet_by_id(db: Session, packet_id: str) -> Optional[Packet]:
    # TODO: Implement DB query for packet by id
    return db.query(Packet).filter(Packet.id == packet_id).first()

def generate_packet_id(db: Session) -> str:
    # TODO: Implement logic for generating unique packet ID (possibly via DB sequence)
    # Placeholder implementation
    return f"SVC-{datetime.now().year}-AUTOID"

def list_packets(db: Session) -> List[Packet]:
    # TODO: Implement DB query for all packets
    return db.query(Packet).all()



@router.get("", response_model=PacketDTOListResponse, response_model_exclude_none=False)
async def list_packets(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    high_level_status: Optional[str] = Query(None, description="Filter by high-level status"),
    detailed_status: Optional[str] = Query(None, description="Filter by detailed status"),
    channel: Optional[str] = Query(None, description="Filter by channel (Portal, Fax, esMD)"),
    priority: Optional[str] = Query(None, description="Filter by priority (Expedited, Standard) - maps to submission_type"),
    search: Optional[str] = Query(None, description="Search in Service-Ops ID (SVC-), Channel ID (PKT-), beneficiary name/MBI, provider name/NPI, decision tracking ID"),
    date_from: Optional[str] = Query(None, description="Filter by received date from (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter by received date to (YYYY-MM-DD)"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned user ID"),
    utn_filter: Optional[str] = Query(None, description="Filter by UTN presence: 'utn' for packets with UTN, 'no-utn' for packets without UTN"),
    validation_status: Optional[str] = Query(None, description="Filter by validation status"),
    operational_decision: Optional[str] = Query(None, description="Filter by operational decision: PENDING, DISMISSAL, DISMISSAL_COMPLETE, DECISION_COMPLETE"),
    clinical_decision: Optional[str] = Query(None, description="Filter by clinical decision: PENDING, AFFIRM, NON_AFFIRM"),
    sort_by: Optional[str] = Query(None, description="Sort field name"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=10000, description="Items per page (max 10000 for client-side filtering)"),
):
    from app.models.channel_type import ChannelType
    
    query = db.query(PacketDB)
    
    # Filter by assigned_to
    if assigned_to:
        query = query.filter(PacketDB.assigned_to == assigned_to)
    
    # Filter by requires_utn_fix (for UTN_FAIL remediation)
    requires_utn_fix_param = request.query_params.get('requires_utn_fix')
    has_utn_join = False
    if requires_utn_fix_param and requires_utn_fix_param.lower() == 'true':
        # Join with packet_decision to filter by requires_utn_fix
        query = query.join(PacketDecisionDB, PacketDB.packet_id == PacketDecisionDB.packet_id).filter(
            PacketDecisionDB.requires_utn_fix == True
        )
        has_utn_join = True
    
    # Filter by UTN presence (UTN vs NO-UTN)
    # Note: We filter by active decision (is_active = True) to match how packet_to_dto fetches UTN
    if utn_filter:
        utn_filter_lower = utn_filter.lower()
        if not has_utn_join:
            # Join with packet_decision if not already joined, filter by active decision
            query = query.join(
                PacketDecisionDB, 
                and_(
                    PacketDB.packet_id == PacketDecisionDB.packet_id,
                    PacketDecisionDB.is_active == True
                )
            )
            has_utn_join = True
        else:
            # If already joined, add is_active filter
            query = query.filter(PacketDecisionDB.is_active == True)
        
        if utn_filter_lower == 'utn':
            # Filter for packets WITH UTN (utn is not NULL)
            query = query.filter(
                and_(
                    PacketDecisionDB.utn.isnot(None),
                    PacketDecisionDB.utn != ''
                )
            )
        elif utn_filter_lower == 'no-utn':
            # Filter for packets WITHOUT UTN (utn is NULL or empty)
            query = query.filter(
                or_(
                    PacketDecisionDB.utn.is_(None),
                    PacketDecisionDB.utn == ''
                )
            )
    
    # Filter by detailed_status
    if detailed_status:
        query = query.filter(PacketDB.detailed_status == detailed_status)
    
    # Filter by validation_status
    if validation_status:
        query = query.filter(PacketDB.validation_status == validation_status)
    
    # Filter by operational_decision and clinical_decision (requires join with packet_decision)
    has_decision_join = has_utn_join
    if operational_decision or clinical_decision:
        if not has_decision_join:
            query = query.join(
                PacketDecisionDB,
                and_(
                    PacketDB.packet_id == PacketDecisionDB.packet_id,
                    PacketDecisionDB.is_active == True
                )
            )
            has_decision_join = True
        else:
            # If already joined, ensure is_active filter is applied
            query = query.filter(PacketDecisionDB.is_active == True)
        
        if operational_decision:
            query = query.filter(PacketDecisionDB.operational_decision == operational_decision.upper())
        
        if clinical_decision:
            query = query.filter(PacketDecisionDB.clinical_decision == clinical_decision.upper())
    
    # Filter by channel (map Channel enum to channel_type_id)
    if channel:
        channel_upper = channel.upper()
        if channel_upper == 'PORTAL':
            query = query.filter(PacketDB.channel_type_id == ChannelType.GENZEON_PORTAL)
        elif channel_upper == 'FAX':
            query = query.filter(PacketDB.channel_type_id == ChannelType.GENZEON_FAX)
        elif channel_upper in ['ESMD', 'ESMD']:
            query = query.filter(PacketDB.channel_type_id == ChannelType.ESMD)
    
    # Filter by priority (maps to submission_type: Expedited or Standard)
    if priority:
        if priority.upper() == 'EXPEDITED':
            query = query.filter(PacketDB.submission_type == 'Expedited')
        elif priority.upper() == 'STANDARD':
            query = query.filter(PacketDB.submission_type == 'Standard')
    
    # Filter by high_level_status (derived from detailed_status patterns)
    if high_level_status:
        if high_level_status == 'Intake Validation':
            query = query.filter(
                and_(
                    PacketDB.detailed_status.isnot(None),
                    PacketDB.detailed_status == 'Intake Validation'
                )
            )
        elif high_level_status == 'Clinical Review':
            query = query.filter(
                or_(
                    PacketDB.detailed_status == 'Clinical Review',
                    PacketDB.detailed_status.like('%Clinical%'),
                    and_(
                        PacketDB.detailed_status.like('%Review%'),
                        PacketDB.detailed_status.notlike('%Intake%')
                    )
                )
            )
        elif high_level_status == 'Outbound In Progress':
            query = query.filter(
                or_(
                    PacketDB.detailed_status == 'Outbound In Progress',
                    PacketDB.detailed_status.like('%Outbound%'),
                    PacketDB.detailed_status.like('%Delivery%')
                )
            )
        elif high_level_status == 'Closed - Delivered':
            query = query.filter(
                or_(
                    PacketDB.detailed_status == 'Closed - Delivered',
                    PacketDB.detailed_status == 'Delivered',
                    PacketDB.detailed_status.like('%Delivered%')
                )
            )
        elif high_level_status == 'Closed - Dismissed':
            query = query.filter(
                or_(
                    PacketDB.detailed_status == 'Closed - Dismissed',
                    PacketDB.detailed_status == 'Dismissed',
                    PacketDB.detailed_status.like('%Dismissed%')
                )
            )
    
    # Search filter (packet ID, case ID, beneficiary name/MBI, provider name/NPI, decision tracking ID)
    if search:
        # Trim and normalize search term
        search_trimmed = search.strip()
        if search_trimmed:
            search_term = f"%{search_trimmed.lower()}%"
            # Build search conditions - handle NULL case_id properly
            search_conditions = [
                PacketDB.external_id.ilike(search_term),  # Service-Ops ID (SVC- format)
                PacketDB.beneficiary_name.ilike(search_term),
                PacketDB.beneficiary_mbi.ilike(search_term),
                PacketDB.provider_name.ilike(search_term),
                PacketDB.provider_npi.ilike(search_term),
                cast(PacketDB.decision_tracking_id, String).ilike(search_term)
            ]
            # Add case_id search only if not NULL (NULL.ilike() returns NULL which doesn't match in or_())
            search_conditions.append(
                and_(PacketDB.case_id.isnot(None), PacketDB.case_id.ilike(search_term))  # Channel ID (PKT- format for Portal)
            )
            query = query.filter(or_(*search_conditions))
    
    # Filter by received date range
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(PacketDB.received_date >= date_from_obj)
        except ValueError:
            # Invalid date format, ignore filter
            pass
    if date_to:
        try:
            from datetime import datetime, timedelta
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            # Include the entire day (up to end of day)
            date_to_end = datetime.combine(date_to_obj, datetime.max.time())
            query = query.filter(PacketDB.received_date <= date_to_end)
        except ValueError:
            # Invalid date format, ignore filter
            pass
    
    # Don't calculate total here - we'll get it from the status counts query for consistency
    if sort_by:
        sort_col = getattr(PacketDB, sort_by, None)
        if sort_col is not None:
            if sort_order == "desc":
                query = query.order_by(sort_col.desc())
            else:
                query = query.order_by(sort_col.asc())
    # Calculate status counts from ALL packets (not just current page)
    # Use SQL to count by detailed_status patterns (more efficient than converting all packets)
    # NULL detailed_status = "New" (not counted in Intake Validation)
    # "Intake Validation" = counted in Intake Validation
    from sqlalchemy import func, case
    
    # Apply same filters to status counts query (except high_level_status which is derived)
    base_query_for_counts = db.query(PacketDB)
    if assigned_to:
        base_query_for_counts = base_query_for_counts.filter(PacketDB.assigned_to == assigned_to)
    
    # Filter by requires_utn_fix (for UTN_FAIL remediation)
    has_utn_join_counts = False
    if requires_utn_fix_param and requires_utn_fix_param.lower() == 'true':
        base_query_for_counts = base_query_for_counts.join(PacketDecisionDB, PacketDB.packet_id == PacketDecisionDB.packet_id).filter(
            PacketDecisionDB.requires_utn_fix == True
        )
        has_utn_join_counts = True
    
    # Filter by UTN presence for status counts (must match main query)
    # Note: We filter by active decision (is_active = True) to match how packet_to_dto fetches UTN
    if utn_filter:
        utn_filter_lower = utn_filter.lower()
        if not has_utn_join_counts:
            base_query_for_counts = base_query_for_counts.join(
                PacketDecisionDB,
                and_(
                    PacketDB.packet_id == PacketDecisionDB.packet_id,
                    PacketDecisionDB.is_active == True
                )
            )
            has_utn_join_counts = True
        else:
            # If already joined, add is_active filter
            base_query_for_counts = base_query_for_counts.filter(PacketDecisionDB.is_active == True)
        
        if utn_filter_lower == 'utn':
            base_query_for_counts = base_query_for_counts.filter(
                and_(
                    PacketDecisionDB.utn.isnot(None),
                    PacketDecisionDB.utn != ''
                )
            )
        elif utn_filter_lower == 'no-utn':
            base_query_for_counts = base_query_for_counts.filter(
                or_(
                    PacketDecisionDB.utn.is_(None),
                    PacketDecisionDB.utn == ''
                )
            )
    
    if detailed_status:
        base_query_for_counts = base_query_for_counts.filter(PacketDB.detailed_status == detailed_status)
    if channel:
        channel_upper = channel.upper()
        if channel_upper == 'PORTAL':
            base_query_for_counts = base_query_for_counts.filter(PacketDB.channel_type_id == ChannelType.GENZEON_PORTAL)
        elif channel_upper == 'FAX':
            base_query_for_counts = base_query_for_counts.filter(PacketDB.channel_type_id == ChannelType.GENZEON_FAX)
        elif channel_upper in ['ESMD', 'ESMD']:
            base_query_for_counts = base_query_for_counts.filter(PacketDB.channel_type_id == ChannelType.ESMD)
    if priority:
        if priority.upper() == 'EXPEDITED':
            base_query_for_counts = base_query_for_counts.filter(PacketDB.submission_type == 'Expedited')
        elif priority.upper() == 'STANDARD':
            base_query_for_counts = base_query_for_counts.filter(PacketDB.submission_type == 'Standard')
    if search:
        # Trim and normalize search term
        search_trimmed = search.strip()
        if search_trimmed:
            search_term = f"%{search_trimmed.lower()}%"
            # Build search conditions - handle NULL case_id properly
            search_conditions = [
                PacketDB.external_id.ilike(search_term),  # Service-Ops ID (SVC- format)
                PacketDB.beneficiary_name.ilike(search_term),
                PacketDB.beneficiary_mbi.ilike(search_term),
                PacketDB.provider_name.ilike(search_term),
                PacketDB.provider_npi.ilike(search_term),
                cast(PacketDB.decision_tracking_id, String).ilike(search_term)
            ]
            # Add case_id search only if not NULL
            search_conditions.append(
                and_(PacketDB.case_id.isnot(None), PacketDB.case_id.ilike(search_term))  # Channel ID (PKT- format for Portal)
            )
            base_query_for_counts = base_query_for_counts.filter(or_(*search_conditions))
    
    # Apply date filters to status counts query
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            base_query_for_counts = base_query_for_counts.filter(PacketDB.received_date >= date_from_obj)
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime, timedelta
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            date_to_end = datetime.combine(date_to_obj, datetime.max.time())
            base_query_for_counts = base_query_for_counts.filter(PacketDB.received_date <= date_to_end)
        except ValueError:
            pass
    
    status_counts_query = base_query_for_counts.with_entities(
        # Total count (all packets, including NULL status)
        func.count(PacketDB.packet_id).label('total_count'),
        # New packets (NULL detailed_status)
        func.sum(case((PacketDB.detailed_status.is_(None), 1), else_=0)).label('new_count'),
        # Intake Validation: includes Intake, Validation, Pending - New, etc.
        func.sum(case((or_(
            PacketDB.detailed_status == 'Pending - New',
            PacketDB.detailed_status == 'Intake',
            PacketDB.detailed_status == 'Validation',
            PacketDB.detailed_status == 'Intake Validation',
            and_(
                PacketDB.detailed_status.isnot(None),
                or_(
                    PacketDB.detailed_status.like('%Intake%'),
                    PacketDB.detailed_status.like('%Validation%')
                ),
                PacketDB.detailed_status.notlike('%Clinical%'),
                PacketDB.detailed_status.notlike('%UTN%'),
                PacketDB.detailed_status.notlike('%Letter%'),
                PacketDB.detailed_status.notlike('%Decision Complete%'),
                PacketDB.detailed_status.notlike('%Dismissal%')
            )
        ), 1), else_=0)).label('intake_validation'),
        # Clinical Review
        func.sum(case((or_(
            PacketDB.detailed_status == 'Pending - Clinical Review',
            PacketDB.detailed_status == 'Clinical Decision Received',
            PacketDB.detailed_status == 'Clinical Review',
            PacketDB.detailed_status.like('%Clinical%'),
            and_(
                PacketDB.detailed_status.like('%Review%'),
                PacketDB.detailed_status.notlike('%Intake%')
            )
        ), 1), else_=0)).label('clinical_review'),
        # UTN Outbound (Pending - UTN, UTN Received)
        func.sum(case((or_(
            PacketDB.detailed_status == 'Pending - UTN',
            PacketDB.detailed_status == 'UTN Received'
        ), 1), else_=0)).label('utn_outbound'),
        # Letter Outbound (Generate/Send Decision Letter statuses)
        func.sum(case((or_(
            PacketDB.detailed_status == 'Generate Decision Letter - Pending',
            PacketDB.detailed_status == 'Generate Decision Letter - Complete',
            PacketDB.detailed_status == 'Send Decision Letter - Pending',
            PacketDB.detailed_status == 'Send Decision Letter - Complete'
        ), 1), else_=0)).label('letter_outbound'),
        # Decision Complete (was Closed - Delivered)
        func.sum(case((or_(
            PacketDB.detailed_status == 'Decision Complete',
            PacketDB.detailed_status == 'Closed - Delivered',  # Backward compatibility
            PacketDB.detailed_status == 'Delivered'
        ), 1), else_=0)).label('decision_complete'),
        # Dismissal Complete (was Closed - Dismissed)
        func.sum(case((or_(
            PacketDB.detailed_status == 'Dismissal Complete',
            PacketDB.detailed_status == 'Closed - Dismissed',  # Backward compatibility
            PacketDB.detailed_status == 'Dismissed'
        ), 1), else_=0)).label('dismissal_complete'),
    )
    
    counts_result = status_counts_query.first()
    # Use the total count from the query (more accurate, includes all packets)
    total_count = int(counts_result.total_count or 0)
    new_count = int(counts_result.new_count or 0)
    intake_validation_count = int(counts_result.intake_validation or 0)
    clinical_count = int(counts_result.clinical_review or 0)
    utn_outbound_count = int(counts_result.utn_outbound or 0)
    letter_outbound_count = int(counts_result.letter_outbound or 0)
    decision_complete_count = int(counts_result.decision_complete or 0)
    dismissal_complete_count = int(counts_result.dismissal_complete or 0)
    
    # Verify total matches sum of all statuses (for debugging, but use total_count as source of truth)
    # total should always be the count of ALL packets in the system
    status_counts = {
        "Intake Validation": intake_validation_count,
        "Clinical Review": clinical_count,
        "UTN Outbound": utn_outbound_count,
        "Letter Outbound": letter_outbound_count,
        "Decision Complete": decision_complete_count,
        "Dismissal Complete": dismissal_complete_count,
    }
    
    # Calculate total from filtered query (respects all filters)
    # This ensures pagination works correctly with filters
    # OPTIMIZATION: Use EXISTS subquery for count (faster than COUNT(*))
    total = query.count()
    
    # OPTIMIZATION: Apply pagination before fetching to reduce memory
    paginated = query.offset((page - 1) * page_size).limit(page_size).all()
    
    # Bulk load documents for all packets in this page to avoid N+1 query issue
    packet_ids = [p.packet_id for p in paginated]
    from app.models.document_db import PacketDocumentDB
    documents_map = {}
    if packet_ids:
        documents = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id.in_(packet_ids)
        ).all()
        # Create a map: packet_id -> document
        for doc in documents:
            if doc.packet_id not in documents_map:
                documents_map[doc.packet_id] = doc
    
    # Convert DB models to DTOs, passing db session and documents map
    packet_dtos = [packet_to_dto(packet, db_session=db, documents_map=documents_map) for packet in paginated]
    
    response = PacketDTOListResponse(
        success=True,
        data=packet_dtos,
        total=total,
        page=page,
        page_size=page_size,
        status_counts=status_counts,
    )
    
    # DEBUG: Log validation error fields for TEST-ERRORS packets
    import logging
    logger = logging.getLogger(__name__)
    test_packets = [p for p in packet_dtos if p.id and 'TEST-ERRORS' in p.id]
    if test_packets:
        for p in test_packets:
            logger.info(f"[DEBUG] Packet {p.id}: hasFieldValidationErrors={p.hasFieldValidationErrors}, fieldValidationErrors={p.fieldValidationErrors}")
            # Force serialization to check if fields are present
            if hasattr(p, 'model_dump'):
                p_dict = p.model_dump(exclude_none=False, mode='json')
                logger.info(f"[DEBUG] Serialized packet dict keys (last 5): {list(p_dict.keys())[-5:]}")
                logger.info(f"[DEBUG] hasFieldValidationErrors in dict: {'hasFieldValidationErrors' in p_dict}")
                logger.info(f"[DEBUG] fieldValidationErrors in dict: {'fieldValidationErrors' in p_dict}")
    
    # Force FastAPI to include None values by using model_dump with exclude_none=False
    # This ensures the fields are serialized even if they're None
    from fastapi.responses import JSONResponse
    import json
    
    # Serialize the response manually to ensure fields are included
    if hasattr(response, 'model_dump'):
        response_dict = response.model_dump(exclude_none=False, mode='json')
    else:
        response_dict = response.dict(exclude_none=False)
    
    return JSONResponse(content=response_dict)


@router.get("/{packet_id}", response_model=PacketDTOResponse)
async def get_packet(
    packet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get packet details. 
    For "Pending - New" packets, automatically locks to current user and changes status to "Intake".
    If packet is already assigned to another user, returns 403 Forbidden.
    """
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found",
        )
    
    # TEMPORARY: Locking disabled for team review - uncomment to re-enable
    # Check if packet is assigned to someone else
    # if packet.assigned_to and packet.assigned_to != current_user.email:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail=f"Packet is currently assigned to {packet.assigned_to}. Only that user can view it."
    #     )
    
    # TEMPORARY: Auto-lock disabled for team review - uncomment to re-enable
    # Auto-lock logic: If packet is "Pending - New" and not assigned, lock it to current user
    # if packet.detailed_status == "Pending - New" and not packet.assigned_to:
    #     from app.services.workflow_orchestrator import WorkflowOrchestratorService
    #     
    #     # Lock packet and change status to "Intake"
    #     WorkflowOrchestratorService.update_packet_status(
    #         db=db,
    #         packet=packet,
    #         new_status="Intake"
    #     )
    #     
    #     # Assign to current user (lock)
    #     packet.assigned_to = current_user.email
    #     packet.updated_at = datetime.now(timezone.utc)
    #     db.commit()
    #     db.refresh(packet)
    #     
    #     # Log the event
    #     log_packet_event(
    #         action="view_and_lock",
    #         outcome="success",
    #         user_id=current_user.id,
    #         username=current_user.email,
    #         ip=get_client_ip(request),
    #         packet_id=packet_id,
    #         details=f"Packet viewed and locked to {current_user.email}, status changed to Intake"
    #     )
    
    packet_dto = packet_to_dto(packet, db_session=db)
    return PacketDTOResponse(success=True, data=packet_dto)


from app.models.document_db import PacketDocumentDB, DocumentDB, LetterDB, OCRExtractionDB, DocumentClassificationDB

@router.get("/{packet_id}/documents", response_model=DocumentListResponse)
async def get_packet_documents(
    packet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get packet documents.
    Enforces lock: If packet is assigned to another user, returns 403 Forbidden.
    """
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packet not found")
    
    # TEMPORARY: Locking disabled for team review - uncomment to re-enable
    # Check if packet is assigned to someone else
    # if packet.assigned_to and packet.assigned_to != current_user.email:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail=f"Packet is currently assigned to {packet.assigned_to}. Only that user can view documents."
    #     )
    
    documents = db.query(PacketDocumentDB).filter(PacketDocumentDB.packet_id == packet.packet_id).all()
    # Convert SQLAlchemy models to DTOs
    # Pass packet_id to avoid extra DB query in document_to_dto
    document_dtos = documents_to_dto_list(documents, packet_id, db)
    return DocumentListResponse(
        success=True,
        data=document_dtos,
        message=f"Retrieved {len(document_dtos)} document(s) for packet {packet_id}",
    )


@router.post(
    "/{packet_id}/documents/{doc_id}/start-validation",
    response_model=PacketDTOResponse,
    status_code=status.HTTP_200_OK
)
async def start_intake_validation(
    packet_id: str,
    doc_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Start Intake Validation phase.
    Transitions: NULL → "Intake Validation"
    Assigns packet to current user (locks it).
    """
    # 1. Get packet (validate it exists)
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # 2. Validate document exists and belongs to packet
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # TEMPORARY: Locking disabled for team review - uncomment to re-enable
    # 3. Check if already assigned to someone else
    # if packet.assigned_to and packet.assigned_to != current_user.email:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail=f"Packet is currently assigned to {packet.assigned_to}"
    #     )
    
    # 4. Check if already in Intake Validation
    if packet.detailed_status == "Intake Validation":
        # TEMPORARY: Auto-assignment disabled for team review - uncomment to re-enable
        # Already in validation, just ensure assignment
        # if not packet.assigned_to:
        #     packet.assigned_to = current_user.email
        #     packet.updated_at = datetime.now(timezone.utc)
        #     db.commit()
        #     db.refresh(packet)
        packet_dto = packet_to_dto(packet, db_session=db)
        return PacketDTOResponse(
            success=True,
            data=packet_dto,
            message="Packet is already in Intake Validation"
        )
    
    # 5. Update status (assignment disabled for team review)
    packet.detailed_status = "Intake Validation"
    # TEMPORARY: Assignment disabled for team review - uncomment to re-enable
    # packet.assigned_to = current_user.email
    packet.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(packet)
    
    # 6. Log the event
    log_packet_event(
        action="start_validation",
        outcome="success",
        user_id=current_user.id,
        username=current_user.email,
        ip=get_client_ip(request),
        packet_id=packet_id,
        details=f"Started Intake Validation, assigned to {current_user.email}"
    )
    
    # 7. Return updated packet
    packet_dto = packet_to_dto(packet, db_session=db)
    return PacketDTOResponse(
        success=True,
        data=packet_dto,
        message="Packet moved to Intake Validation"
    )


@router.post(
    "/{packet_id}/claim-for-review",
    response_model=PacketDTOResponse,
    status_code=status.HTTP_200_OK
)
async def claim_for_review(
    packet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Claim packet for review (if not already assigned).
    If packet is in "Intake Validation" and not assigned, assign to current user.
    If already assigned to someone else, return error.
    """
    # 1. Get packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # TEMPORARY: Locking disabled for team review - uncomment to re-enable
    # 2. Check if already assigned to someone else
    # if packet.assigned_to and packet.assigned_to != current_user.email:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail=f"Packet is currently assigned to {packet.assigned_to}. Only that user can review it."
    #     )
    
    # TEMPORARY: Auto-assignment disabled for team review - uncomment to re-enable
    # 3. If not assigned yet, assign to current user
    # if not packet.assigned_to:
    #     packet.assigned_to = current_user.email
    #     packet.updated_at = datetime.now(timezone.utc)
    #     db.commit()
    #     db.refresh(packet)
    #     
    #     # Log the event
    #     log_packet_event(
    #         action="claim_for_review",
    #         outcome="success",
    #         user_id=current_user.id,
    #         username=current_user.email,
    #         ip=get_client_ip(request) if request else "unknown",
    #         packet_id=packet_id,
    #         details=f"Claimed packet for review, assigned to {current_user.email}"
    #     )
    
    # 4. Return packet
    packet_dto = packet_to_dto(packet, db_session=db)
    return PacketDTOResponse(
        success=True,
        data=packet_dto,
        message="Packet claimed for review"
    )


@router.get("/{packet_id}/letters", response_model=LetterListResponse)
async def get_packet_letters(
    packet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packet not found")
    # Get packet first to get the numeric packet_id
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packet not found")
    letters = db.query(LetterDB).filter(LetterDB.packet_id == packet.packet_id).all()
    return LetterListResponse(
        success=True,
        data=letters,
        message=f"Retrieved {len(letters)} letter(s) for packet {packet_id}",
    )


@router.post("", response_model=PacketResponse)
async def create_packet(
    packet_data: PacketCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR])),
):
    client_ip = get_client_ip(request)
    is_valid, error_msg = validate_npi(packet_data.referring_provider_npi)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid NPI: {error_msg}",
        )
    now = datetime.now(timezone.utc)
    timestamp_int = int(now.timestamp())
    microseconds = now.microsecond
    # Use last 7 digits of timestamp + last digit of microseconds for better uniqueness
    timestamp_suffix = str(timestamp_int)[-7:]
    microsecond_digit = str(microseconds)[-1]
    suffix = f"{timestamp_suffix}{microsecond_digit}"[:7]  # Ensure 7 digits total
    external_id = f"SVC-{now.year}-{suffix}"
    
    # Ensure uniqueness (with progressive expansion if needed)
    max_retries = 100
    retry_count = 0
    digit_count = 7
    while db.query(PacketDB).filter(PacketDB.external_id == external_id).first():
        retry_count += 1
        if retry_count >= max_retries:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate unique external_id after {max_retries} attempts"
            )
        now = datetime.now(timezone.utc)
        timestamp_int = int(now.timestamp())
        microseconds = now.microsecond
        if retry_count <= 10:
            digit_count = 7
        elif retry_count <= 30:
            digit_count = 8
        elif retry_count <= 60:
            digit_count = 9
        else:
            digit_count = 10
        if digit_count <= 7:
            timestamp_suffix = str(timestamp_int)[-7:]
            microsecond_digit = str(microseconds)[-1]
            suffix = f"{timestamp_suffix}{microsecond_digit}"[:7]
        else:
            timestamp_suffix = str(timestamp_int)[-digit_count+1:]
            microsecond_digits = str(microseconds).zfill(6)[:digit_count-7] if digit_count > 7 else ""
            suffix = f"{timestamp_suffix}{microsecond_digits}".zfill(digit_count)[-digit_count:]
        external_id = f"SVC-{now.year}-{suffix}"
    new_packet = PacketDB(
        external_id=external_id,
        beneficiary_name=packet_data.patient_name,  # Map patient_name to beneficiary_name
        beneficiary_mbi=packet_data.patient_mrn or "",  # Map patient_mrn to beneficiary_mbi
        provider_name=packet_data.referring_provider,  # Map referring_provider to provider_name
        provider_npi=packet_data.referring_provider_npi,
        service_type=packet_data.diagnosis or "",  # Map diagnosis to service_type
        received_date=now,
        due_date=now,  # TODO: Calculate proper due date based on priority
        created_at=now,
        updated_at=now,
        assigned_to=packet_data.assigned_to,
        detailed_status='Pending - New'  # Required NOT NULL field - explicit default for new packets
    )
    db.add(new_packet)
    db.commit()
    db.refresh(new_packet)
    log_packet_event(
        action="create",
        outcome="success",
        user_id=current_user.id,
        username=current_user.username,
        ip=client_ip,
        packet_id=new_packet.external_id,
    )
    return PacketResponse(success=True, data=new_packet, message="Packet created")


@router.put("/{packet_id}", response_model=PacketDTOResponse)
async def update_packet(
    packet_id: str,
    packet_data: PacketDTOUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR, UserRole.REVIEWER])),
):
    client_ip = get_client_ip(request)
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found",
        )
    # Apply DTO update to packet using the converter utility
    apply_dto_update_to_packet(packet, packet_data)
    now = datetime.now(timezone.utc)
    packet.updated_at = now
    db.commit()
    db.refresh(packet)
    log_packet_event(
        action="update",
        outcome="success",
        user_id=current_user.id,
        username=current_user.username,
        ip=client_ip,
        packet_id=packet_id,
        details=audit_entry["details"],
    )
    packet_dto = packet_to_dto(packet, db_session=db)
    return PacketDTOResponse(success=True, data=packet_dto, message="Packet updated successfully")


@router.post(
    "/{packet_id}/mark-complete",
    response_model=PacketDTOResponse,
    status_code=status.HTTP_200_OK
)
async def mark_packet_complete(
    packet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark packet as complete (Closed - Delivered).
    This is a temporary function that directly moves packet to Closed - Delivered
    regardless of current state.
    """
    # 1. Get packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # 2. Update packet status directly to Closed - Delivered
    packet.detailed_status = "Closed - Delivered"
    packet.assigned_to = None  # Release any lock
    packet.validation_complete = True
    packet.clinical_review_complete = True
    packet.delivery_complete = True
    packet.closed_date = datetime.now(timezone.utc)
    packet.letter_delivered = datetime.now(timezone.utc)
    packet.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(packet)
    
    # 3. Log the event
    log_packet_event(
        action="mark_complete",
        outcome="success",
        user_id=current_user.id,
        username=current_user.email,
        ip=get_client_ip(request),
        packet_id=packet_id,
        details=f"Packet marked as complete (Closed - Delivered) by {current_user.email}"
    )
    
    # 4. Return updated packet
    packet_dto = packet_to_dto(packet, db_session=db)
    return PacketDTOResponse(
        success=True,
        data=packet_dto,
        message="Packet marked as complete"
    )
@router.delete("/{packet_id}", response_model=ApiResponse)
async def delete_packet(
    packet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN])),
):
    client_ip = get_client_ip(request)
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found",
        )
    db.delete(packet)
    db.commit()
    log_packet_event(
        action="delete",
        outcome="success",
        user_id=current_user.id,
        username=current_user.username,
        ip=client_ip,
        packet_id=packet_id,
    )
    return ApiResponse(success=True, message="Packet deleted")


@router.get("/{packet_id}/ocr-extraction", response_model=OCRExtractionResponse)
async def get_packet_ocr_extraction(
    packet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER])),
):
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packet not found")
    # Get packet first to get the numeric packet_id
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packet not found")
    ocr = db.query(OCRExtractionDB).filter(OCRExtractionDB.packet_id == packet.packet_id).first()
    if not ocr:
        return OCRExtractionResponse(success=True, data=None, fieldIssues=None, message="No OCR extraction data found")
    return OCRExtractionResponse(
        success=True,
        data=ocr.data,
        fieldIssues=ocr.field_issues,
        message="OCR extraction data retrieved successfully",
    )


@router.get("/{packet_id}/classification", response_model=DocumentClassificationResponse)
async def get_packet_classification(
    packet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.REVIEWER])),
):
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packet not found")
    # Get packet first to get the numeric packet_id
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packet not found")
    classification = db.query(DocumentClassificationDB).filter(DocumentClassificationDB.packet_id == packet.packet_id).first()
    if not classification:
        return DocumentClassificationResponse(success=True, data=None, message="No classification data found")
    return DocumentClassificationResponse(
        success=True,
        data={"classification": classification.classification, "confidence": classification.confidence},
        message="Document classification retrieved successfully",
    )


@router.get("/{packet_id}/validation-status", response_model=ApiResponse[Dict[str, Any]])
async def get_packet_validation_status(
    packet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get validation status for HETS and PECOS for a packet
    Returns the active validation records showing which validations were marked as valid/invalid
    """
    from app.models.packet_validation_db import PacketValidationDB
    from typing import Dict, Any
    from sqlalchemy.exc import ProgrammingError
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Get packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Build response
    validation_status: Dict[str, Any] = {
        'hets': None,
        'pecos': None
    }
    
    # Try to get active validation records for HETS and PECOS
    # Handle permission errors gracefully (table might not be accessible)
    try:
        # Note: We filter by is_passed.isnot(None) to only get records where user has explicitly marked as valid/invalid
        # Records with is_passed=None are "Validation In Progress" and shouldn't be shown as final results
        hets_validation = db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == packet.packet_id,
            PacketValidationDB.validation_type == 'HETS',
            PacketValidationDB.is_active == True,
            PacketValidationDB.is_passed.isnot(None)  # Only get records where user has marked result
        ).order_by(PacketValidationDB.validated_at.desc()).first()
        
        pecos_validation = db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == packet.packet_id,
            PacketValidationDB.validation_type == 'PECOS',
            PacketValidationDB.is_active == True,
            PacketValidationDB.is_passed.isnot(None)  # Only get records where user has marked result
        ).order_by(PacketValidationDB.validated_at.desc()).first()
        
        if hets_validation:
            validation_status['hets'] = {
                'is_passed': hets_validation.is_passed,
                'validation_status': hets_validation.validation_status,
                'validated_by': hets_validation.validated_by,
                'validated_at': hets_validation.validated_at.isoformat() if hets_validation.validated_at else None
            }
        
        if pecos_validation:
            validation_status['pecos'] = {
                'is_passed': pecos_validation.is_passed,
                'validation_status': pecos_validation.validation_status,
                'validated_by': pecos_validation.validated_by,
                'validated_at': pecos_validation.validated_at.isoformat() if pecos_validation.validated_at else None
            }
    except ProgrammingError as e:
        # Handle database permission errors gracefully
        # This can happen if the database user doesn't have SELECT permission on packet_validation table
        logger.warning(
            f"Could not query packet_validation table for packet_id={packet_id}: {str(e)}. "
            "Returning empty validation status. This may be a database permission issue."
        )
        # Return empty status - UI will handle this gracefully
    except Exception as e:
        # Handle any other database errors gracefully
        logger.error(
            f"Error querying packet_validation table for packet_id={packet_id}: {str(e)}. "
            "Returning empty validation status."
        )
        # Return empty status - UI will handle this gracefully
    
    return ApiResponse(
        success=True,
        data=validation_status,
        message="Validation status retrieved successfully"
    )


@router.get("/{packet_id}/utn-fail-details", response_model=UtnFailDetailsDTO)
async def get_utn_fail_details(
    packet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get UTN_FAIL details for a packet requiring remediation
    
    Returns UTN_FAIL error details, action required, and ESMD attempt history
    """
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Get packet_decision
    packet_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id
    ).first()
    
    if not packet_decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet decision not found"
        )
    
    # Extract UTN_FAIL data
    utn_fail_payload = packet_decision.utn_fail_payload or {}
    
    return UtnFailDetailsDTO(
        packet_id=packet.external_id,
        decision_tracking_id=str(packet.decision_tracking_id),
        requires_utn_fix=packet_decision.requires_utn_fix or False,
        utn_status=packet_decision.utn_status,
        utn_received_at=packet_decision.utn_received_at,
        error_code=utn_fail_payload.get('error_code') if isinstance(utn_fail_payload, dict) else None,
        error_description=utn_fail_payload.get('error_description') if isinstance(utn_fail_payload, dict) else None,
        action_required=packet_decision.utn_action_required,
        utn_fail_payload=utn_fail_payload if isinstance(utn_fail_payload, dict) else None,
        esmd_request_status=packet_decision.esmd_request_status,
        esmd_attempt_count=packet_decision.esmd_attempt_count,
        esmd_last_error=packet_decision.esmd_last_error
    )


@router.post("/{packet_id}/resend-to-esmd", response_model=ResendToEsmdResponse)
async def resend_to_esmd(
    packet_id: str,
    request_data: ResendToEsmdRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR, UserRole.REVIEWER])),
):
    """
    Resend ESMD payload after fixing data issues
    
    This endpoint:
    1. Validates that packet requires UTN fix
    2. Regenerates ESMD payload from current packet data
    3. Writes new payload to service_ops.send_integration
    4. Updates packet_decision with new attempt count and status
    5. Appends to payload history
    """
    client_ip = get_client_ip(request)
    
    # Get packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Get packet_decision
    packet_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id
    ).first()
    
    if not packet_decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet decision not found. Cannot resend without decision context."
        )
    
    # Validate that resend is needed
    if not packet_decision.requires_utn_fix:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Packet does not require UTN fix. Only packets with requires_utn_fix=true can be resent."
        )
    
    # Check max attempts (prevent infinite retries)
    max_attempts = 5
    if packet_decision.esmd_attempt_count and packet_decision.esmd_attempt_count >= max_attempts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum resend attempts ({max_attempts}) reached. Please contact support."
        )
    
    try:
        # Generate new ESMD payload
        from app.services.esmd_payload_generator import EsmdPayloadGenerator
        import json
        
        payload_generator = EsmdPayloadGenerator(db)
        
        # Get procedures from packet_decision (if stored) or use empty list
        # For resend, we'll use the same procedures from the original decision
        procedures = []
        if packet_decision.esmd_request_payload and isinstance(packet_decision.esmd_request_payload, dict):
            procedures = packet_decision.esmd_request_payload.get('procedures', [])
        
        # Get medical docs from packet_decision
        medical_docs = packet_decision.letter_medical_docs
        if isinstance(medical_docs, list):
            medical_docs = [str(doc) for doc in medical_docs]
        else:
            medical_docs = None
        
        # Generate payload
        esmd_payload = payload_generator.generate_payload(
            packet=packet,
            packet_decision=packet_decision,
            procedures=procedures,
            medical_docs=medical_docs
        )
        
        # Convert to JSON string
        payload_json = json.dumps(esmd_payload)
        payload_hash = payload_generator._hash_payload(payload_json)
        
        # Calculate new attempt count
        new_attempt_count = (packet_decision.esmd_attempt_count or 0) + 1
        
        # Get correlation_id from previous attempt (if exists)
        correlation_id = None
        if packet_decision.esmd_request_payload_history and isinstance(packet_decision.esmd_request_payload_history, list):
            # Use correlation_id from first attempt if available
            first_attempt = packet_decision.esmd_request_payload_history[0] if packet_decision.esmd_request_payload_history else None
            if isinstance(first_attempt, dict) and 'correlation_id' in first_attempt:
                correlation_id = first_attempt['correlation_id']
        
        # Write to integration outbox (service_ops.send_integration)
        from app.models.send_integration_db import SendIntegrationDB
        import uuid as uuid_lib
        
        # Build structured payload with message_type
        # Extract decision outcome and part type for easy querying
        decision_outcome = packet_decision.decision_outcome or ""
        part_type = packet_decision.part_type or esmd_payload.get("partType", "")
        
        structured_payload = {
            "message_type": "ESMD_PAYLOAD",
            "decision_tracking_id": str(packet.decision_tracking_id),
            "decision_type": packet_decision.decision_subtype,  # DIRECT_PA or STANDARD_PA
            "decision_outcome": decision_outcome,  # AFFIRM, NON_AFFIRM, DISMISSAL
            "part_type": part_type,  # A or B
            "is_direct_pa": esmd_payload.get("isDirectPa", False),  # Boolean for easy filtering
            "esmd_payload": esmd_payload,
            "attempt_count": new_attempt_count,
            "payload_hash": payload_hash,
            "payload_version": new_attempt_count,  # Version increments with each attempt
            "correlation_id": str(correlation_id) if correlation_id else str(uuid_lib.uuid4()),
            "resend_of_message_id": first_attempt.get('message_id') if first_attempt else None,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": current_user.email
        }
        
        # Determine resend_of_message_id from first attempt
        resend_of_message_id = None
        if first_attempt and 'message_id' in first_attempt:
            resend_of_message_id = first_attempt['message_id']
        
        outbox_record = SendIntegrationDB(
            decision_tracking_id=packet.decision_tracking_id,
            payload=structured_payload,
            message_status_id=1,  # INGESTED - ready for Integration to poll
            correlation_id=uuid_lib.UUID(structured_payload["correlation_id"]),
            attempt_count=new_attempt_count,
            payload_hash=payload_hash,
            payload_version=new_attempt_count,
            resend_of_message_id=resend_of_message_id,
            audit_user=current_user.email,
            audit_timestamp=datetime.utcnow()
        )
        db.add(outbox_record)
        db.flush()
        
        # Update packet_decision
        packet_decision.esmd_request_status = 'SENT'
        packet_decision.esmd_request_payload = esmd_payload
        packet_decision.esmd_attempt_count = new_attempt_count
        packet_decision.esmd_last_sent_at = datetime.utcnow()
        packet_decision.esmd_last_error = None  # Clear previous error
        
        # Append to payload history (use message_id instead of response_id)
        history = packet_decision.esmd_request_payload_history or []
        if not isinstance(history, list):
            history = []
        
        history.append({
            "attempt": new_attempt_count,
            "payload_hash": payload_hash,
            "sent_at": datetime.utcnow().isoformat(),
            "status": "SENT",
            "message_id": outbox_record.message_id,
            "notes": request_data.notes
        })
        packet_decision.esmd_request_payload_history = history
        
        db.commit()
        db.refresh(outbox_record)
        
        # Log the event
        log_packet_event(
            action="resend_to_esmd",
            outcome="success",
            user_id=current_user.id,
            username=current_user.email,
            ip=client_ip,
            packet_id=packet_id,
            details=f"ESMD payload resent (attempt {new_attempt_count}). Message ID: {outbox_record.message_id}"
        )
        
        return ResendToEsmdResponse(
            success=True,
            message=f"ESMD payload resent successfully (attempt {new_attempt_count})",
            response_id=outbox_record.message_id,  # Keep response_id for API compatibility, but it's actually message_id
            esmd_attempt_count=new_attempt_count
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error resending ESMD payload for packet {packet_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resend ESMD payload: {str(e)}"
        )
