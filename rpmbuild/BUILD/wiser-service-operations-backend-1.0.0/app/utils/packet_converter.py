"""
Packet Converter
Converts internal Packet model to PacketDTO for API responses
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from app.models.packet import Packet, PacketStatus
from app.models.packet_dto import (
    PacketDTO,
    PacketHighLevelStatus,
    IntakeDetailedStatus,
    ClinicalDetailedStatus,
    DeliveryDetailedStatus,
    Priority,
    Channel,
    SLAStatus,
    ManualReviewType,
    UtnFailInfo,
)
from app.models.channel_type import ChannelType


def _normalize_submission_type_for_sla(submission_type: Optional[str]) -> str:
    """
    Normalize submission type value to determine SLA hours.
    
    Uses partial matching (starts with) to handle values like:
    - 'expedited-initial' -> 'Expedited'
    - 'standard-initial' -> 'Standard'
    - 'expedited-someother' -> 'Expedited'
    
    Args:
        submission_type: Raw submission type value
        
    Returns:
        'Expedited' or 'Standard' (defaults to 'Standard' if None or unrecognized)
    """
    if not submission_type:
        return 'Standard'
    
    value_lower = submission_type.strip().lower()
    
    # Expedited keywords - check if value starts with any of these
    expedited_keywords = ['expedited', 'expedite', 'urgent', 'rush']
    for keyword in expedited_keywords:
        if value_lower.startswith(keyword):
            return 'Expedited'
    
    # Standard keywords - check if value starts with any of these
    standard_keywords = ['standard', 'normal', 'routine', 'regular']
    for keyword in standard_keywords:
        if value_lower.startswith(keyword):
            return 'Standard'
    
    # Default to Standard if unrecognized
    return 'Standard'


def calculate_sla_status(
    received_date: datetime, 
    high_level_status: PacketHighLevelStatus,
    submission_type: Optional[str] = None
) -> SLAStatus:
    """
    Calculate SLA status based on received date, current phase, and submission type.
    Normalizes received_date to midnight for SLA calculation.
    
    SLA targets (total from received_date normalized to midnight):
    - Expedited: 48 hours total
    - Standard: 72 hours total
    
    The SLA starts from received_date normalized to midnight (when message was originally received from payload).
    Status thresholds:
    - CRITICAL: >= 100% of SLA elapsed (overdue)
    - WARNING: >= 75% of SLA elapsed (at risk)
    - ON_TRACK: < 75% of SLA elapsed
    
    Args:
        received_date: When the packet was received (raw timestamp - will be normalized to midnight)
        high_level_status: Current processing phase
        submission_type: "Expedited" or "Standard" (defaults to "Standard" if not provided)
    
    Returns:
        SLAStatus indicating current SLA compliance
    """
    now = datetime.now(timezone.utc)
    
    # Ensure received_date is timezone-aware (assume UTC if naive)
    if received_date.tzinfo is None:
        received_date = received_date.replace(tzinfo=timezone.utc)
    
    # Normalize received_date to midnight for SLA calculation (extract date only)
    normalized_received_date = datetime(
        year=received_date.year,
        month=received_date.month,
        day=received_date.day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=timezone.utc
    )
    
    # Closed states - no SLA tracking
    if high_level_status in [
        PacketHighLevelStatus.CLOSED_DELIVERED,
        PacketHighLevelStatus.CLOSED_DISMISSED
    ]:
        return SLAStatus.ON_TRACK
    
    # Determine SLA target based on submission_type
    # Uses partial matching (starts with) to handle values like 'expedited-initial', 'standard-initial'
    submission_type_normalized = _normalize_submission_type_for_sla(submission_type)
    if submission_type_normalized == 'Expedited':
        sla_hours = 48  # Expedited: 48 hours total
    else:
        sla_hours = 72  # Standard: 72 hours total
    
    # Calculate hours elapsed since normalized_received_date
    hours_elapsed = (now - normalized_received_date).total_seconds() / 3600
    
    # Calculate percentage of SLA elapsed
    percent_elapsed = hours_elapsed / sla_hours
    
    # Determine status based on percentage
    if percent_elapsed >= 1.0:
        return SLAStatus.CRITICAL  # Overdue
    elif percent_elapsed >= 0.75:
        return SLAStatus.WARNING  # At risk (75-99%)
    else:
        return SLAStatus.ON_TRACK  # On track (< 75%)


def map_internal_status_to_high_level(internal_status: PacketStatus) -> PacketHighLevelStatus:
    """Map internal PacketStatus to PacketHighLevelStatus"""
    mapping = {
        PacketStatus.PENDING: PacketHighLevelStatus.INTAKE_VALIDATION,
        PacketStatus.IN_REVIEW: PacketHighLevelStatus.CLINICAL_REVIEW,
        PacketStatus.APPROVED: PacketHighLevelStatus.OUTBOUND_IN_PROGRESS,
        PacketStatus.REJECTED: PacketHighLevelStatus.CLOSED_DISMISSED,
    }
    return mapping.get(internal_status, PacketHighLevelStatus.INTAKE_VALIDATION)


def determine_detailed_status(
    internal_status: PacketStatus,
    high_level_status: PacketHighLevelStatus,
    assigned_to: Optional[str],
) -> str:
    """
    Determine detailed status based on internal status and context.
    This is a simplified mapping - in production, this would come from workflow state.
    """
    if high_level_status == PacketHighLevelStatus.INTAKE_VALIDATION:
        if internal_status == PacketStatus.PENDING:
            if assigned_to:
                return IntakeDetailedStatus.MANUAL_REVIEW.value
            else:
                return IntakeDetailedStatus.RECEIVED.value
        elif internal_status == PacketStatus.IN_REVIEW:
            return IntakeDetailedStatus.VALIDATING.value
        else:
            return IntakeDetailedStatus.CASE_CREATED.value
    
    elif high_level_status == PacketHighLevelStatus.CLINICAL_REVIEW:
        if internal_status == PacketStatus.IN_REVIEW:
            return ClinicalDetailedStatus.PENDING_REVIEW.value
        else:
            return ClinicalDetailedStatus.IN_PROGRESS.value
    
    elif high_level_status == PacketHighLevelStatus.OUTBOUND_IN_PROGRESS:
        return DeliveryDetailedStatus.QUEUED.value
    
    elif high_level_status == PacketHighLevelStatus.CLOSED_DELIVERED:
        return DeliveryDetailedStatus.DELIVERED.value
    
    elif high_level_status == PacketHighLevelStatus.CLOSED_DISMISSED:
        return "Dismissed"
    
    else:
        return IntakeDetailedStatus.RECEIVED.value


def _map_channel_type_id_to_channel(channel_type_id: Optional[int]) -> Channel:
    """
    Map channel_type_id from database to Channel enum for UI display.
    
    Args:
        channel_type_id: Channel type ID (1=Portal, 2=Fax, 3=ESMD), None for backward compatibility
        
    Returns:
        Channel enum value
    """
    if channel_type_id == ChannelType.GENZEON_PORTAL:
        return Channel.PORTAL
    elif channel_type_id == ChannelType.GENZEON_FAX:
        return Channel.FAX
    elif channel_type_id == ChannelType.ESMD:
        return Channel.ESMD
    else:
        # Default to FAX for backward compatibility
        return Channel.FAX


def map_insurance_to_channel(insurance: str) -> Channel:
    """Map insurance provider to submission channel (simplified)"""
    # This is a placeholder - in production, channel would be stored separately
    insurance_lower = insurance.lower()
    if "medicare" in insurance_lower:
        return Channel.FAX
    elif "medicaid" in insurance_lower:
        return Channel.PORTAL
    else:
        return Channel.FAX  # Default


def map_priority_from_submission_type(submission_type: Optional[str]) -> Priority:
    """Map submission_type to Priority (Standard or Expedited)"""
    if submission_type:
        submission_type_normalized = _normalize_submission_type_for_sla(submission_type)
        if submission_type_normalized == 'Expedited':
            return Priority.EXPEDITED
    return Priority.STANDARD


def _calculate_completeness(packet: Packet) -> int:
    """Calculate completeness score for a packet, ensuring it's always an integer."""
    # Use completeness from packet if available
    if packet.completeness is not None:
        return packet.completeness
    # Fallback: default to 75 if not set
    return 75


def extract_from_ocr_fields(documents, field_names: list) -> Optional[str]:
    """
    Extract value from OCR fields in documents.
    PRIORITY: updated_extracted_fields first (working copy), then extracted_fields (baseline).
    Tries multiple field name variations.
    
    Supports both:
    - PacketDocumentDB objects (with updated_extracted_fields/extracted_fields attributes)
    - Dictionary objects (direct updated_extracted_fields/extracted_fields dict)
    """
    if not documents:
        return None
    
    for doc in documents:
        # PRIORITY 1: Check updated_extracted_fields first (working copy - has user edits)
        # PRIORITY 2: Fallback to extracted_fields (baseline - immutable)
        extracted_fields = None
        
        if hasattr(doc, 'updated_extracted_fields') and doc.updated_extracted_fields:
            # PacketDocumentDB: Check updated_extracted_fields first
            extracted_fields = doc.updated_extracted_fields
        elif hasattr(doc, 'extracted_fields'):
            # PacketDocumentDB: Fallback to extracted_fields
            extracted_fields = doc.extracted_fields
        elif isinstance(doc, dict):
            # Dictionary: Check updated_extracted_fields first, then extracted_fields
            extracted_fields = doc.get('updated_extracted_fields') or doc.get('extracted_fields') or doc
        else:
            continue
        
        if not extracted_fields or not extracted_fields.get('fields'):
            continue
        
        fields = extracted_fields['fields']
        for field_name in field_names:
            # Try exact match first
            if field_name in fields:
                field_data = fields[field_name]
                # Handle both dict format (with 'value' key) and direct value
                if isinstance(field_data, dict):
                    value = field_data.get('value')
                else:
                    value = field_data
                
                if value and value != 'TBD' and value != 'N/A' and str(value).strip() != '':
                    return str(value).strip()
            
            # Try case-insensitive match with normalization (more aggressive)
            field_name_normalized = field_name.lower().replace('_', '').replace(' ', '').replace('-', '').replace('/', '')
            for key, field_data in fields.items():
                key_normalized = key.lower().replace('_', '').replace(' ', '').replace('-', '').replace('/', '')
                # Also try partial matches (e.g., "beneficiary" matches "beneficiary name")
                if (key_normalized == field_name_normalized or 
                    field_name_normalized in key_normalized or 
                    key_normalized in field_name_normalized):
                    # Handle both dict format (with 'value' key) and direct value
                    if isinstance(field_data, dict):
                        value = field_data.get('value')
                    else:
                        value = field_data
                    
                    if value and value != 'TBD' and value != 'N/A' and str(value).strip() != '':
                        return str(value).strip()
    
    return None


def packet_to_dto(packet, db_session=None, documents_map=None) -> PacketDTO:
    """
    Convert PacketDB (SQLAlchemy model) to PacketDTO for API response.
    Accepts either Packet (Pydantic) or PacketDB (SQLAlchemy) models.
    
    Optionally extracts beneficiary/provider info from OCR fields in documents
    if db_session is provided.
    """
    """
    Convert internal Packet model to PacketDTO for API response.
    
    This function maps the internal packet structure to the frontend-expected format.
    """
    # Check if this is PacketDB (SQLAlchemy) or Packet (Pydantic)
    is_db_model = hasattr(packet, 'external_id')
    
    # Try to get OCR data from documents if db_session is provided
    ocr_beneficiary_name = None
    ocr_beneficiary_mbi = None
    ocr_provider_name = None
    ocr_provider_npi = None
    
    # Get part_type from packet_document (same as DocumentsTable uses)
    part_type = None
    documents = []
    if is_db_model:
        # Use documents_map if provided (bulk loaded), otherwise query individually
        if documents_map and hasattr(packet, 'packet_id') and packet.packet_id in documents_map:
            document = documents_map[packet.packet_id]
            if document:
                documents = [document]
                # Get part_type - check both part_type field and handle NULL/empty strings
                doc_part_type = getattr(document, 'part_type', None)
                if doc_part_type and str(doc_part_type).strip() and str(doc_part_type).upper() not in ('UNKNOWN', ''):
                    part_type = str(doc_part_type).strip()
        elif db_session:
            try:
                from app.models.document_db import PacketDocumentDB
                # Get the document(s) for this packet (same query as DocumentsTable)
                document = db_session.query(PacketDocumentDB).filter(
                    PacketDocumentDB.packet_id == packet.packet_id
                ).first()
                
                if document:
                    documents = [document]
                    # Get part_type - check both part_type field and handle NULL/empty strings
                    doc_part_type = getattr(document, 'part_type', None)
                    if doc_part_type and str(doc_part_type).strip() and str(doc_part_type).upper() not in ('UNKNOWN', ''):
                        part_type = str(doc_part_type).strip()
            except Exception as e:
                # Log error but don't fail - part_type will remain None
                import logging
                logger = logging.getLogger(__name__)
                packet_id_val = packet.packet_id if hasattr(packet, 'packet_id') else (packet.external_id if hasattr(packet, 'external_id') else 'unknown')
                logger.warning(f"Failed to get part_type for packet {packet_id_val}: {e}", exc_info=True)
        
        # Extract beneficiary info from OCR (outside try/except for document query)
        try:
            # Try multiple field name variations (OCR services may use different naming)
            beneficiary_last_name = extract_from_ocr_fields(
                documents, 
                [
                    'Beneficiary Last Name', 'beneficiaryLastName', 'beneficiary_last_name',
                    'Patient Last Name', 'patientLastName', 'patient_last_name',
                    'Member Last Name', 'memberLastName', 'member_last_name',
                    'Last Name', 'lastName', 'last_name', 'lname'
                ]
            )
            beneficiary_first_name = extract_from_ocr_fields(
                documents,
                [
                    'Beneficiary First Name', 'beneficiaryFirstName', 'beneficiary_first_name',
                    'Patient First Name', 'patientFirstName', 'patient_first_name',
                    'Member First Name', 'memberFirstName', 'member_first_name',
                    'First Name', 'firstName', 'first_name', 'fname'
                ]
            )
            if beneficiary_first_name and beneficiary_last_name:
                ocr_beneficiary_name = f"{beneficiary_first_name} {beneficiary_last_name}".strip()
            else:
                ocr_beneficiary_name = extract_from_ocr_fields(
                    documents,
                    [
                        'Beneficiary Name', 'beneficiaryName', 'beneficiary_name',
                        'Patient Name', 'patientName', 'patient_name',
                        'Member Name', 'memberName', 'member_name',
                        'Full Name', 'fullName', 'full_name'
                    ]
                )
            
            ocr_beneficiary_mbi = extract_from_ocr_fields(
                documents,
                [
                    'Beneficiary Medicare ID',  # Exact match from OCR output
                    'Medicare ID', 'medicareId', 'MBI', 'mbi', 'Beneficiary MBI', 'beneficiaryMbi',
                    'Medicare Beneficiary Identifier', 'Medicare Number', 'medicareNumber',
                    'HICN', 'hicn', 'Health Insurance Claim Number'
                ]
            )
            
            # Extract provider info from OCR
            # Note: OCR uses "Facility Provider Name" and "Attending Physician Name"
            facility_name = extract_from_ocr_fields(
                documents,
                [
                    'Facility Provider Name',  # Exact match from OCR output
                    'Facility Name', 'facilityName', 'facility_name',
                    'Organization Name', 'organizationName', 'organization_name',
                    'Practice Name', 'practiceName', 'practice_name'
                ]
            )
            physician_name = extract_from_ocr_fields(
                documents,
                [
                    'Attending Physician Name',  # Exact match from OCR output
                    'Physician Name', 'physicianName', 'physician_name',
                    'Ordering/Referring Physician Name', 'Ordering Physician Name',
                    'Referring Physician Name', 'Doctor Name', 'doctorName',
                    'Attending Physician', 'attendingPhysician'
                ]
            )
            ocr_provider_name = facility_name or physician_name or extract_from_ocr_fields(
                documents,
                [
                    'Provider Name', 'providerName', 'provider_name',
                    'Rendering Provider Name', 'renderingProviderName',
                    'Billing Provider Name', 'billingProviderName'
                ]
            )
            
            facility_npi = extract_from_ocr_fields(
                documents,
                [
                    'Facility Provider NPI',  # Exact match from OCR output
                    'Facility NPI', 'facilityNpi', 'facility_npi',
                    'Organization NPI', 'organizationNpi', 'organization_npi'
                ]
            )
            physician_npi = extract_from_ocr_fields(
                documents,
                [
                    'Attending Physician NPI',  # Exact match from OCR output (10 digits)
                    'Physician NPI', 'physicianNpi', 'physician_npi',
                    'Ordering/Referring Physician NPI', 'Ordering Physician NPI',
                    'Referring Physician NPI', 'Doctor NPI', 'doctorNpi'
                ]
            )
            # Prefer Attending Physician NPI (usually 10 digits) over Facility Provider NPI (may be 9 digits)
            ocr_provider_npi = physician_npi or facility_npi or extract_from_ocr_fields(
                documents,
                [
                    'Provider NPI', 'providerNpi', 'provider_npi',
                    'Rendering Provider NPI', 'renderingProviderNpi',
                    'Billing Provider NPI', 'billingProviderNpi',
                    'NPI', 'npi'  # Last resort - generic NPI field
                ]
            )
        except Exception as e:
            # Log error but don't fail - fall back to packet table values
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to extract OCR fields for packet {packet.external_id}: {e}")
    
    # Extract fields based on model type
    if is_db_model:
        # PacketDB model (SQLAlchemy)
        packet_id = packet.external_id
        beneficiary_name = ocr_beneficiary_name or packet.beneficiary_name
        beneficiary_mbi = ocr_beneficiary_mbi or packet.beneficiary_mbi
        provider_name = ocr_provider_name or packet.provider_name
        provider_npi = ocr_provider_npi or packet.provider_npi
        provider_fax = packet.provider_fax
        service_type = packet.service_type
        hcpcs = packet.hcpcs
        submission_type = getattr(packet, 'submission_type', None)  # May not exist in older packets (backward compatibility)
        detailed_status = packet.detailed_status
        validation_status = getattr(packet, 'validation_status', None)  # New field
        clinical_status = packet.clinical_status
        delivery_status = packet.delivery_status
        received_date = packet.received_date
        due_date = packet.due_date
        page_count = packet.page_count or 0
        completeness = packet.completeness or 0
        assigned_to = packet.assigned_to
        review_type = packet.review_type
        # Use case_id if available (channel-specific identifier)
        # For Portal: case_id contains Portal's packet_id (PKT- format)
        # For ESMD: case_id contains esmdTransactionId (from original MAC request)
        # For Fax: case_id is NULL (no channel-specific ID exists)
        if hasattr(packet, 'case_id') and packet.case_id:
            case_id = packet.case_id  # Portal's packet_id (PKT- format) or ESMD's esmdTransactionId
        else:
            # Fax channel doesn't have a channel-specific ID
            # Leave as None - frontend will display "N/A"
            case_id = None
        # Extract decision_tracking_id (UUID from integration.send_serviceops)
        decision_tracking_id = str(packet.decision_tracking_id) if hasattr(packet, 'decision_tracking_id') and packet.decision_tracking_id else None
        intake_complete = packet.intake_complete
        validation_complete = packet.validation_complete
        clinical_review_complete = packet.clinical_review_complete
        delivery_complete = packet.delivery_complete
        letter_delivered = packet.letter_delivered
        created_at = packet.created_at
        updated_at = packet.updated_at
        closed_date = packet.closed_date
    else:
        # Packet model (Pydantic) - legacy support
        packet_id = packet.id
        beneficiary_name = packet.patient_name
        beneficiary_mbi = packet.patient_mrn
        provider_name = packet.referring_provider
        provider_npi = packet.referring_provider_npi
        provider_fax = None
        service_type = packet.diagnosis
        hcpcs = None
        detailed_status = packet.detailed_status
        validation_status = None  # Not available in legacy Pydantic models
        clinical_status = None
        delivery_status = None
        received_date = packet.created_at
        due_date = None
        page_count = 0
        completeness = packet.completeness or 0
        assigned_to = packet.assigned_to
        review_type = packet.review_type
        case_id = packet.id.replace("SVC", "CASE") if packet.id else None
        # Extract decision_tracking_id (may not exist in legacy Pydantic models)
        decision_tracking_id = getattr(packet, 'decision_tracking_id', None)
        if decision_tracking_id:
            decision_tracking_id = str(decision_tracking_id)
        else:
            decision_tracking_id = None
        intake_complete = False
        validation_complete = False
        clinical_review_complete = False
        delivery_complete = False
        letter_delivered = None
        created_at = packet.created_at
        updated_at = packet.updated_at
        closed_date = None
    
    # Normalize provider_npi: handle "TBD" or invalid values
    if not provider_npi or provider_npi == "TBD" or len(provider_npi) != 10:
        provider_npi = "0000000000"  # Default placeholder for missing/invalid NPI
    
    # Determine high-level status from detailed_status or default
    # NULL detailed_status means "New" - not in any workflow phase
    if detailed_status:
        detailed_lower = detailed_status.lower()
        
        # Closed states (check first)
        if "dismissal complete" in detailed_lower:
            high_level_status = PacketHighLevelStatus.CLOSED_DISMISSED
        elif "decision complete" in detailed_lower:
            high_level_status = PacketHighLevelStatus.CLOSED_DELIVERED
        # Active states
        elif "send decision letter" in detailed_lower or "generate decision letter" in detailed_lower:
            high_level_status = PacketHighLevelStatus.OUTBOUND_IN_PROGRESS
        elif "utn received" in detailed_lower or "pending - utn" in detailed_lower:
            high_level_status = PacketHighLevelStatus.CLINICAL_REVIEW
        elif "clinical decision received" in detailed_lower or "pending - clinical review" in detailed_lower:
            high_level_status = PacketHighLevelStatus.CLINICAL_REVIEW
        elif "validation" in detailed_lower or "intake" in detailed_lower or "pending - new" in detailed_lower:
            high_level_status = PacketHighLevelStatus.INTAKE_VALIDATION
        else:
            # Default: if status is set but unrecognized, assume Intake Validation
            high_level_status = PacketHighLevelStatus.INTAKE_VALIDATION
    else:
        # NULL status = "New" - return None to indicate not in workflow
        high_level_status = None
    
    # Calculate SLA status (using submission_type to determine SLA hours)
    if received_date:
        received_date_aware = received_date
        if received_date_aware.tzinfo is None:
            received_date_aware = received_date_aware.replace(tzinfo=timezone.utc)
        sla_status = calculate_sla_status(
            received_date_aware, 
            high_level_status,
            submission_type=submission_type
        )
    else:
        sla_status = SLAStatus.ON_TRACK
    
    # Calculate due date if not set (based on submission_type)
    # Due date = received_date (normalized to midnight) + SLA hours (48 for Expedited, 72 for Standard)
    if not due_date and received_date:
        received_date_aware = received_date
        if received_date_aware.tzinfo is None:
            received_date_aware = received_date_aware.replace(tzinfo=timezone.utc)
        
        # Normalize received_date to midnight for due date calculation (extract date only)
        normalized_received_date = datetime(
            year=received_date_aware.year,
            month=received_date_aware.month,
            day=received_date_aware.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=timezone.utc
        )
        
        # Determine SLA hours based on submission_type
        # Uses partial matching (starts with) to handle values like 'expedited-initial', 'standard-initial'
        submission_type_normalized = _normalize_submission_type_for_sla(submission_type)
        if submission_type_normalized == 'Expedited':
            sla_hours = 48  # Expedited: 48 hours
        else:
            sla_hours = 72  # Standard: 72 hours
        
        # Calculate due date using normalized received_date
        due_date = normalized_received_date + timedelta(hours=sla_hours)
    
    # case_id is set from packet.case_id (channel-specific identifier) if available
    # For Portal: case_id = packet.case_id (PKT- format from payload.packet_id)
    # For ESMD: case_id = packet.case_id (esmdTransactionId from payload.submission_metadata)
    # For Fax: case_id = None (no channel-specific ID exists)
    # Fallback only for legacy Pydantic models (not for DB models)
    if not case_id and not is_db_model:
        case_id = packet_id.replace("SVC", "CASE") if packet_id else None
    
    # Handle None high_level_status (for "New" packets not in workflow)
    # For frontend compatibility, use INTAKE_VALIDATION as default but detailedStatus will be NULL
    if high_level_status is None:
        # New packet - not in workflow yet
        final_high_level_status = PacketHighLevelStatus.INTAKE_VALIDATION  # Default for frontend
        final_detailed_status = None  # NULL means "New"
    else:
        final_high_level_status = high_level_status
        final_detailed_status = detailed_status  # Keep as-is (can be None)
    
    # Get field validation errors if available
    field_validation_errors = None
    has_field_validation_errors = None
    if is_db_model:
        # Get flag from packet
        has_field_validation_errors = getattr(packet, 'has_field_validation_errors', False)
        
        # Get detailed errors from validation service if db_session available
        if db_session and has_field_validation_errors:
            try:
                from app.services.validation_persistence import get_field_validation_errors
                validation_data = get_field_validation_errors(packet.packet_id, db_session)
                if validation_data:
                    field_validation_errors = validation_data.get('field_errors', {})
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not get field validation errors for packet {packet.external_id}: {e}")
    
    # Get UTN_FAIL info and decision info from packet_decision if available
    utn_fail_info = None
    operational_decision = None
    clinical_decision = None
    utn = None
    if is_db_model and db_session:
        try:
            from app.models.packet_decision_db import PacketDecisionDB
            from sqlalchemy.exc import ProgrammingError
            # Get active decision (is_active = True)
            packet_decision = db_session.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet.packet_id,
                PacketDecisionDB.is_active == True
            ).first()
            
            # If no active decision, get the most recent decision (for completed packets)
            if not packet_decision:
                packet_decision = db_session.query(PacketDecisionDB).filter(
                    PacketDecisionDB.packet_id == packet.packet_id
                ).order_by(
                    PacketDecisionDB.created_at.desc()
                ).first()
            
            if packet_decision:
                # Get operational and clinical decisions
                operational_decision = packet_decision.operational_decision
                clinical_decision = packet_decision.clinical_decision
                
                # Get UTN value
                utn = packet_decision.utn
                
                # Get UTN_FAIL info if applicable
                if packet_decision.requires_utn_fix or packet_decision.utn_status == 'FAILED':
                    utn_fail_payload = packet_decision.utn_fail_payload or {}
                    utn_fail_info = UtnFailInfo(
                        requires_utn_fix=packet_decision.requires_utn_fix or False,
                        utn_status=packet_decision.utn_status,
                        error_code=utn_fail_payload.get('error_code') if isinstance(utn_fail_payload, dict) else None,
                        error_description=utn_fail_payload.get('error_description') if isinstance(utn_fail_payload, dict) else None,
                        esmd_attempt_count=packet_decision.esmd_attempt_count
                    )
        except ProgrammingError as e:
            # Handle missing column gracefully (decision_subtype may not exist in production yet)
            if 'decision_subtype' in str(e) or 'UndefinedColumn' in str(e):
                logger.warning(
                    f"Failed to get decision info for packet {packet.external_id if hasattr(packet, 'external_id') else 'unknown'}: "
                    f"decision_subtype column does not exist. Skipping decision info. "
                    f"This is expected if migration 012 has not been applied yet."
                )
                # Decision info will remain None - this is acceptable
            else:
                # Re-raise if it's a different ProgrammingError
                raise
        except Exception as e:
            # Log but don't fail - Decision info is optional
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get decision info for packet {packet_id}: {e}")
    
    # Build PacketDTO
    return PacketDTO(
        id=packet_id,
        caseId=case_id,
        decisionTrackingId=decision_tracking_id,
        beneficiaryName=beneficiary_name,
        beneficiaryMbi=beneficiary_mbi,
        providerName=provider_name,
        providerNpi=provider_npi,
        providerFax=provider_fax,
        serviceType=service_type,
        hcpcs=hcpcs,
        submissionType=submission_type,
        partType=part_type,  # From document.part_type (1-to-1 relationship)
        highLevelStatus=final_high_level_status,
        detailedStatus=final_detailed_status,  # Can be None for "New" packets
        status=final_high_level_status,  # Legacy field
        validationStatus=validation_status,  # New workflow field
        clinicalStatus=clinical_status,
        deliveryStatus=delivery_status,
        priority=map_priority_from_submission_type(submission_type),  # Map from submission_type (Expedited = 48h, Standard = 72h)
        receivedDate=received_date or created_at,
        dueDate=due_date,
        channel=_map_channel_type_id_to_channel(packet.channel_type_id if is_db_model and hasattr(packet, 'channel_type_id') else None),
        pageCount=page_count,
        completeness=completeness,
        assignedTo=assigned_to,
        slaStatus=sla_status,
        closedDate=closed_date,
        reviewType=review_type,
        dismissalReason=None,  # Would need to join with dismissal_reason table
        intakeComplete=intake_complete,
        validationComplete=validation_complete,
        clinicalReviewComplete=clinical_review_complete,
        deliveryComplete=delivery_complete,
        letterDelivered=letter_delivered,
        utnFailInfo=utn_fail_info,
        utn=utn,
        operationalDecision=operational_decision,
        clinicalDecision=clinical_decision,
        hasFieldValidationErrors=has_field_validation_errors,
        fieldValidationErrors=field_validation_errors,
    )

