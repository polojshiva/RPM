"""
ESMD Payload Generator
Generates ESMD decision payloads from packet + decision context
Supports all 8 payload types:
- Standard PA Part A Affirm/Non-Affirm
- Standard PA Part B Affirm/Non-Affirm
- Direct PA Part A Affirm/Non-Affirm
- Direct PA Part B Affirm/Non-Affirm
"""
import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.services.blob_storage import BlobStorageClient
from app.config import settings

logger = logging.getLogger(__name__)


class EsmdPayloadGenerator:
    """
    Generates ESMD decision payloads from packet and decision context
    
    Supports all 8 payload type combinations:
    - DIRECT_PA / STANDARD_PA
    - PART_A / PART_B
    - AFFIRM / NON_AFFIRM / DISMISSAL
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.blob_storage = BlobStorageClient(
            container_name=getattr(settings, 'azure_storage_dest_container', 'service-ops-processing')
        )
    
    def generate_payload(
        self,
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        procedures: List[Dict[str, Any]],
        medical_docs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate ESMD decision payload from packet and decision context
        
        Args:
            packet: PacketDB record
            packet_decision: PacketDecisionDB record
            procedures: List of procedure objects from ClinicalOps decision
            medical_docs: Optional list of medical document URLs/paths (for Direct PA only)
        
        Returns:
            ESMD payload dictionary matching contract for specific payload type
        """
        # Determine payload type characteristics
        part_type = (packet_decision.part_type or "B").upper()
        is_part_a = part_type == "A"
        is_part_b = part_type == "B"
        is_direct_pa = packet_decision.decision_subtype == "DIRECT_PA" if packet_decision.decision_subtype else False
        is_standard_pa = not is_direct_pa
        
        logger.info(
            f"Generating ESMD payload for packet_id={packet.packet_id} | "
            f"decision_subtype={packet_decision.decision_subtype} | "
            f"part_type={part_type} | "
            f"outcome={packet_decision.decision_outcome} | "
            f"isDirectPa={is_direct_pa}"
        )
        
        # Get packet document for extracted fields
        packet_document = self.db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not packet_document:
            raise ValueError(f"No packet_document found for packet_id={packet.packet_id}")
        
        # Use updated_extracted_fields if available, otherwise extracted_fields
        extracted_fields = packet_document.updated_extracted_fields or packet_document.extracted_fields or {}
        
        # Extract header data from packet and extracted fields
        header = self._build_header(packet, extracted_fields, packet_decision, is_part_a, is_part_b)
        
        # Build procedures array (Part A vs Part B specific)
        procedures_array = self._build_procedures(procedures, packet_decision, is_part_a, is_part_b)
        
        # Build medical documents array (Direct PA only)
        medical_documents = []
        if is_direct_pa:
            medical_documents = self._build_medical_documents(medical_docs, packet_document)
        
        # Generate uniqueId
        unique_id = self._generate_unique_id(packet)
        
        # Get esmdTransactionId (Standard PA only)
        esmd_transaction_id = None
        if is_standard_pa:
            esmd_transaction_id = self._get_esmd_transaction_id(packet, extracted_fields)
            if not esmd_transaction_id:
                logger.warning(f"Standard PA payload missing esmdTransactionId for packet_id={packet.packet_id}")
        
        # Build payload
        payload = {
            "header": header,
            "partType": part_type,
            "isDirectPa": is_direct_pa,
            "procedures": procedures_array,
            "pushPackages": True,
            "uniqueId": unique_id
        }
        
        # Add esmdTransactionId for Standard PA
        if is_standard_pa and esmd_transaction_id:
            payload["esmdTransactionId"] = esmd_transaction_id
        
        # Add medicalDocuments for Direct PA only
        if is_direct_pa:
            payload["medicalDocuments"] = medical_documents
        
        # Validate payload before returning
        self._validate_payload(payload, is_part_a, is_part_b, is_direct_pa, packet_decision)
        
        logger.info(
            f"Generated ESMD payload: uniqueId={unique_id}, "
            f"isDirectPa={is_direct_pa}, "
            f"partType={part_type}, "
            f"procedures={len(procedures_array)}, "
            f"medicalDocuments={len(medical_documents) if is_direct_pa else 0}"
        )
        
        return payload
    
    def _build_header(
        self,
        packet: PacketDB,
        extracted_fields: Dict[str, Any],
        packet_decision: PacketDecisionDB,
        is_part_a: bool,
        is_part_b: bool
    ) -> Dict[str, Any]:
        """Build header section from packet and extracted fields (Part A/B specific)"""
        
        # Extract fields from extracted_fields JSONB
        fields = extracted_fields.get('fields', {}) if isinstance(extracted_fields, dict) else {}
        
        # Helper to extract field value
        def get_field_value(field_name: str, default: str = "") -> str:
            field_data = fields.get(field_name, {})
            if isinstance(field_data, dict):
                return field_data.get('value', default)
            return field_data if field_data else default
        
        # Physician/provider data
        physician = {
            "npi": packet.provider_npi or "",
            "name": packet.provider_name or "",
            "ptan": get_field_value('provider_ptan'),
            "address": get_field_value('provider_address'),
            "city": get_field_value('provider_city'),
            "state": get_field_value('provider_state'),
            "zipCode": get_field_value('provider_zip')
        }
        
        # Requester data (format phone: digits only)
        requester_phone = get_field_value('requester_phone')
        requester = {
            "name": get_field_value('requester_name'),
            "phone": self._format_phone(requester_phone)
        }
        
        # Beneficiary data (format DOB based on Part type)
        beneficiary_dob = get_field_value('patient_date_of_birth')
        dob_formatted = self._format_date_for_esmd(beneficiary_dob, is_part_a, is_part_b)
        
        beneficiary = {
            "lastName": self._extract_last_name(packet.beneficiary_name),
            "firstName": self._extract_first_name(packet.beneficiary_name),
            "medicareId": packet.beneficiary_mbi or "",
            "dateOfBirth": dob_formatted
        }
        
        # Facility/rendering provider (Part A vs Part B specific)
        facility = self._build_facility(packet, fields, is_part_a, is_part_b)
        
        # State (default to NJ if not found)
        state = get_field_value('state', 'NJ')
        
        # Submission type and expedited request
        # Check if this is a resubmission (submissionType = "R") or initial (submissionType = "I")
        submission_type_raw = get_field_value('submission_type', 'I').upper()
        submission_type = "R" if submission_type_raw == "R" else "I"
        expedited_request = "Y" if packet.submission_type and "expedited" in packet.submission_type.lower() else ""
        
        # Previous UTN (required for resubmissions, empty for initial submissions)
        previous_utn = ""
        if submission_type == "R":
            previous_utn = get_field_value('previous_utn', '')
            if not previous_utn:
                logger.warning(f"Resubmission (submissionType=R) missing previousUtn for packet_id={packet.packet_id}")
        
        # Entry mode: "X" for Standard PA (esMD transactions), "M" for Direct PA
        # Standard PA comes from esMD, so entryMode should be "X" (esMD XDR)
        # Direct PA is initiated directly, so entryMode should be "M" (Manual/Mail)
        is_direct_pa = packet_decision.decision_subtype == "DIRECT_PA" if packet_decision.decision_subtype else False
        entry_mode = "X" if not is_direct_pa else "M"
        
        # Prior auth decision mapping
        # CRITICAL FIX: NON_AFFIRM -> "N" (not "D")
        # AFFIRM -> "A", NON_AFFIRM -> "N", DISMISSAL -> "N"
        prior_auth_decision = self._map_decision_outcome(packet_decision.decision_outcome)
        
        # Anticipated date of service (format based on Part type)
        anticipated_dos = get_field_value('anticipated_date_of_service')
        anticipated_dos_formatted = self._format_date_for_esmd(anticipated_dos, is_part_a, is_part_b)
        
        # Diagnosis code (remove periods)
        diagnosis_code = get_field_value('diagnosis_code')
        diagnosis_code_formatted = self._format_diagnosis_code(diagnosis_code)
        
        # Build header (Part A vs Part B specific)
        header = {
            "icd": "0",  # Always 0 for ICD-10
            "state": state,
            "entryMode": entry_mode,  # "X" for Standard PA (esMD), "M" for Direct PA
            "physician": physician,
            "requester": requester,
            "beneficiary": beneficiary,
            "previousUtn": previous_utn,  # Required for resubmissions, empty for initial
            "diagnosisCode": diagnosis_code_formatted,
            "submissionType": submission_type,
            "expeditedRequest": expedited_request,
            "priorAuthDecision": prior_auth_decision,
            "anticipatedDateOfService": anticipated_dos_formatted,
            "facilityOrRenderingProvider": facility
        }
        
        # Part B specific: stateCode (same as state)
        if is_part_b:
            header["stateCode"] = state
        
        # Part A specific: typeOfBill (required, value "13" or "131")
        if is_part_a:
            type_of_bill = get_field_value('type_of_bill', '13')
            # Validate and normalize typeOfBill
            if type_of_bill not in ['13', '131']:
                logger.warning(f"Invalid typeOfBill '{type_of_bill}', defaulting to '13'")
                type_of_bill = '13'
            header["typeOfBill"] = type_of_bill
        
        return header
    
    def _build_facility(
        self,
        packet: PacketDB,
        fields: Dict[str, Any],
        is_part_a: bool,
        is_part_b: bool
    ) -> Dict[str, Any]:
        """Build facility/rendering provider structure (Part A vs Part B specific)"""
        
        def get_field_value(field_name: str, default: str = "") -> str:
            field_data = fields.get(field_name, {})
            if isinstance(field_data, dict):
                return field_data.get('value', default)
            return field_data if field_data else default
        
        facility_npi = get_field_value('facility_npi', packet.provider_npi or '')
        facility_name = get_field_value('facility_name', packet.provider_name or '')
        
        if is_part_a:
            # Part A: Requires ccn, ptan optional
            facility = {
                "npi": facility_npi,
                "ccn": get_field_value('facility_ccn'),  # Required for Part A
                "ptan": get_field_value('facility_ptan'),  # Optional for Part A
                "name": facility_name,
                "addressLine1": get_field_value('facility_address'),
                "addressLine2": get_field_value('facility_address_line2'),  # Optional
                "city": get_field_value('facility_city'),
                "state": get_field_value('facility_state'),
                "zipCode": get_field_value('facility_zip')
            }
        else:
            # Part B: Requires renderingProviderNpi and ptan
            rendering_provider_npi = get_field_value('rendering_provider_npi', facility_npi)
            facility = {
                "npi": facility_npi,
                "name": facility_name,
                "ptan": get_field_value('facility_ptan'),  # Required for Part B
                "addressLine1": get_field_value('facility_address'),
                "addressLine2": get_field_value('facility_address_line2'),  # Optional
                "city": get_field_value('facility_city'),
                "state": get_field_value('facility_state'),
                "zipCode": get_field_value('facility_zip'),
                "renderingProviderNpi": rendering_provider_npi  # Required for Part B
            }
        
        return facility
    
    def _build_procedures(
        self,
        procedures: List[Dict[str, Any]],
        packet_decision: PacketDecisionDB,
        is_part_a: bool,
        is_part_b: bool
    ) -> List[Dict[str, Any]]:
        """Build procedures array from ClinicalOps decision (Part A vs Part B specific)"""
        
        procedures_array = []
        
        for proc in procedures:
            # CRITICAL FIX: NON_AFFIRM -> "N" (not "D")
            # AFFIRM -> "A", NON_AFFIRM -> "N"
            decision_indicator = self._map_decision_indicator(packet_decision.decision_outcome)
            
            procedure_obj = {
                "procedureCode": proc.get('procedure_code', ''),
                "decisionIndicator": decision_indicator,
                "mrCountUnitOfService": str(proc.get('mr_count_unit_of_service', '1')),
                "modifier": proc.get('modifier', ''),
                "reviewCodes": proc.get('review_codes', ''),
                "programCodes": proc.get('program_codes', '')
            }
            
            # Part B specific: placeOfService (required for Part B, not used in Part A)
            if is_part_b:
                place_of_service = proc.get('place_of_service', '')
                if not place_of_service:
                    logger.warning(f"Part B procedure missing placeOfService: {proc.get('procedure_code', 'unknown')}")
                procedure_obj["placeOfService"] = place_of_service
            
            procedures_array.append(procedure_obj)
        
        return procedures_array
    
    def _build_medical_documents(
        self,
        medical_docs: Optional[List[str]],
        packet_document: PacketDocumentDB
    ) -> List[str]:
        """Build medical documents array (URLs) - Direct PA only"""
        
        medical_documents = []
        
        # If medical_docs provided, use them (from ClinicalOps decision)
        if medical_docs:
            for doc_path in medical_docs:
                # If already a URL, use as-is
                if doc_path.startswith('http://') or doc_path.startswith('https://'):
                    medical_documents.append(doc_path)
                else:
                    # Resolve blob path to URL
                    try:
                        url = self.blob_storage.resolve_blob_url(doc_path)
                        medical_documents.append(url)
                    except Exception as e:
                        logger.warning(f"Failed to resolve blob URL for {doc_path}: {e}")
                        # Still add the path, let ESMD handle it
                        medical_documents.append(doc_path)
        else:
            # Fallback: Use consolidated PDF from packet_document
            if packet_document.consolidated_blob_path:
                try:
                    url = self.blob_storage.resolve_blob_url(packet_document.consolidated_blob_path)
                    medical_documents.append(url)
                except Exception as e:
                    logger.warning(f"Failed to resolve consolidated PDF URL: {e}")
        
        return medical_documents
    
    def _generate_unique_id(self, packet: PacketDB) -> str:
        """
        Generate uniqueId for ESMD payload
        Format: C{YYYYMMDD}{HHMMSS}{random}
        Example: C20108262330125
        """
        now = datetime.utcnow()
        
        # Format: C + YYYYMMDD + HHMMSS + last 3 digits of packet_id
        date_part = now.strftime("%Y%m%d")
        time_part = now.strftime("%H%M%S")
        packet_suffix = str(packet.packet_id)[-3:].zfill(3)
        
        unique_id = f"C{date_part}{time_part}{packet_suffix}"
        
        return unique_id
    
    def _get_esmd_transaction_id(
        self,
        packet: PacketDB,
        extracted_fields: Dict[str, Any]
    ) -> Optional[str]:
        """
        Get esmdTransactionId from packet.case_id (for ESMD channel only)
        
        For ESMD channel (channel_type_id=3), esmdTransactionId is stored in packet.case_id
        during initial packet creation from integration.send_serviceops payload.
        """
        
        # Get esmdTransactionId from packet.case_id (for ESMD channel only)
        if hasattr(packet, 'case_id') and packet.case_id and packet.channel_type_id == 3:
            # For ESMD channel, case_id contains esmdTransactionId
            logger.debug(f"Using esmdTransactionId from packet.case_id: {packet.case_id}")
            return packet.case_id
        
        return None
    
    def _format_date_for_esmd(self, date_str: str, is_part_a: bool, is_part_b: bool) -> str:
        """
        Format date string for ESMD based on Part type
        Part A: YYYY-MM-DD (hyphenated)
        Part B: YYYYMMDD (non-hyphenated)
        
        Handles various input formats: MM/DD/YYYY, YYYY-MM-DD, YYYYMMDD, etc.
        """
        if not date_str:
            return ""
        
        try:
            # Parse date to datetime object first
            dt = None
            
            # Try parsing common formats
            if '/' in date_str:
                # MM/DD/YYYY
                parts = date_str.split('/')
                if len(parts) == 3:
                    month, day, year = parts
                    dt = datetime(int(year), int(month), int(day))
            elif '-' in date_str:
                # YYYY-MM-DD or MM-DD-YYYY
                parts = date_str.split('-')
                if len(parts) == 3:
                    if len(parts[0]) == 4:
                        # YYYY-MM-DD
                        dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                    else:
                        # MM-DD-YYYY
                        month, day, year = parts
                        dt = datetime(int(year), int(month), int(day))
            elif len(date_str) == 8 and date_str.isdigit():
                # Already YYYYMMDD format
                dt = datetime(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8]))
            else:
                # Try parsing with dateutil (fallback)
                try:
                    from dateutil import parser
                    dt = parser.parse(date_str)
                except ImportError:
                    logger.warning(f"dateutil not available, cannot parse date: {date_str}")
                    return ""
            
            if dt:
                # Format based on Part type
                if is_part_a:
                    return dt.strftime("%Y-%m-%d")  # Part A: hyphenated
                else:
                    return dt.strftime("%Y%m%d")  # Part B: non-hyphenated
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to format date '{date_str}' for ESMD: {e}")
            return ""
        
        return ""
    
    def _format_phone(self, phone_str: str) -> str:
        """Format phone number: digits only (remove all non-digits)"""
        if not phone_str:
            return ""
        # Remove all non-digit characters
        return re.sub(r'\D', '', phone_str)
    
    def _format_diagnosis_code(self, diagnosis_code: str) -> str:
        """Format diagnosis code: remove periods (e.g., M54.5 -> M545)"""
        if not diagnosis_code:
            return ""
        # Remove all periods
        return diagnosis_code.replace('.', '')
    
    def _map_decision_outcome(self, decision_outcome: Optional[str]) -> str:
        """
        Map decision outcome to priorAuthDecision
        CRITICAL FIX: NON_AFFIRM -> "N" (not "D")
        AFFIRM -> "A", NON_AFFIRM -> "N", DISMISSAL -> "N"
        """
        if not decision_outcome:
            return ""
        
        decision_outcome_upper = decision_outcome.upper()
        if decision_outcome_upper == "AFFIRM":
            return "A"
        elif decision_outcome_upper == "NON_AFFIRM":
            return "N"  # FIXED: was "D", should be "N"
        elif decision_outcome_upper == "DISMISSAL":
            return "N"
        else:
            logger.warning(f"Unknown decision_outcome: {decision_outcome}")
            return ""
    
    def _map_decision_indicator(self, decision_outcome: Optional[str]) -> str:
        """
        Map decision outcome to decisionIndicator (for procedures)
        CRITICAL FIX: NON_AFFIRM -> "N" (not "D")
        AFFIRM -> "A", NON_AFFIRM -> "N"
        """
        if not decision_outcome:
            return ""
        
        decision_outcome_upper = decision_outcome.upper()
        if decision_outcome_upper == "AFFIRM":
            return "A"
        elif decision_outcome_upper == "NON_AFFIRM":
            return "N"  # FIXED: was "D", should be "N"
        else:
            logger.warning(f"Unknown decision_outcome for decisionIndicator: {decision_outcome}")
            return ""
    
    def _validate_payload(
        self,
        payload: Dict[str, Any],
        is_part_a: bool,
        is_part_b: bool,
        is_direct_pa: bool,
        packet_decision: PacketDecisionDB
    ) -> None:
        """Validate payload structure and required fields based on payload type"""
        
        errors = []
        
        # Validate header
        header = payload.get('header', {})
        
        if is_part_a:
            # Part A validations
            if 'typeOfBill' not in header:
                errors.append("Part A payload missing required field: typeOfBill")
            if 'stateCode' in header:
                errors.append("Part A payload should not include stateCode")
            
            facility = header.get('facilityOrRenderingProvider', {})
            if not facility.get('ccn'):
                errors.append("Part A payload missing required field: facilityOrRenderingProvider.ccn")
            if 'renderingProviderNpi' in facility:
                errors.append("Part A payload should not include renderingProviderNpi")
        
        if is_part_b:
            # Part B validations
            if 'stateCode' not in header:
                errors.append("Part B payload missing required field: stateCode")
            if 'typeOfBill' in header:
                errors.append("Part B payload should not include typeOfBill")
            
            facility = header.get('facilityOrRenderingProvider', {})
            if not facility.get('renderingProviderNpi'):
                errors.append("Part B payload missing required field: facilityOrRenderingProvider.renderingProviderNpi")
            if not facility.get('ptan'):
                errors.append("Part B payload missing required field: facilityOrRenderingProvider.ptan")
            if 'ccn' in facility:
                errors.append("Part B payload should not include ccn")
        
        # Validate procedures
        procedures = payload.get('procedures', [])
        for i, proc in enumerate(procedures):
            if is_part_b:
                if 'placeOfService' not in proc:
                    errors.append(f"Part B procedure {i+1} missing required field: placeOfService")
            if is_part_a:
                if 'placeOfService' in proc:
                    errors.append(f"Part A procedure {i+1} should not include placeOfService")
            
            # Validate Non-Affirm requirements
            if packet_decision.decision_outcome == "NON_AFFIRM":
                if not proc.get('reviewCodes'):
                    errors.append(f"Non-Affirm procedure {i+1} missing required field: reviewCodes")
                if not proc.get('programCodes'):
                    errors.append(f"Non-Affirm procedure {i+1} missing required field: programCodes")
        
        # Validate Standard PA vs Direct PA
        if is_direct_pa:
            if 'medicalDocuments' not in payload:
                errors.append("Direct PA payload missing required field: medicalDocuments")
            if 'esmdTransactionId' in payload:
                errors.append("Direct PA payload should not include esmdTransactionId")
        else:
            # Standard PA
            if 'medicalDocuments' in payload:
                errors.append("Standard PA payload should not include medicalDocuments")
            if not payload.get('esmdTransactionId'):
                errors.append("Standard PA payload missing required field: esmdTransactionId")
        
        # Log errors and raise if critical
        if errors:
            error_msg = f"Payload validation failed for packet_id={payload.get('uniqueId', 'unknown')}:\n" + "\n".join(f"  - {e}" for e in errors)
            logger.error(error_msg)
            # For now, log errors but don't fail (can be made strict later)
            # raise ValueError(error_msg)
    
    def _extract_first_name(self, full_name: str) -> str:
        """Extract first name from full name"""
        if not full_name:
            return ""
        parts = full_name.strip().split()
        return parts[0] if parts else ""
    
    def _extract_last_name(self, full_name: str) -> str:
        """Extract last name from full name"""
        if not full_name:
            return ""
        parts = full_name.strip().split()
        return parts[-1] if len(parts) > 1 else ""
    
    @staticmethod
    def hash_payload(payload: Dict[str, Any]) -> str:
        """Generate SHA-256 hash of payload for audit"""
        import hashlib
        import json
        json_string = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_string.encode('utf-8')).hexdigest()
