"""
Letter Generation Service
Calls LetterGen API to generate affirmation, non-affirmation, and dismissal letters
"""
import logging
import time
import httpx
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.config import settings

logger = logging.getLogger(__name__)


class LetterGenerationError(Exception):
    """Exception raised when letter generation fails"""
    pass


class LetterGenerationService:
    """
    Service for generating letters via LetterGen API
    
    Supports:
    - Affirmation letters (AFFIRM decisions)
    - Non-affirmation letters (NON_AFFIRM decisions)
    - Dismissal letters (DISMISSAL decisions)
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.base_url = settings.lettergen_base_url
        self.timeout = settings.lettergen_timeout_seconds
        self.max_retries = settings.lettergen_max_retries
        self.retry_base_seconds = settings.lettergen_retry_base_seconds
        
        if not self.base_url:
            logger.warning("LETTERGEN_BASE_URL not configured. Letter generation will fail.")
    
    def generate_letter(
        self,
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        packet_document: PacketDocumentDB,
        letter_type: str  # 'affirmation', 'non-affirmation', 'dismissal'
    ) -> Dict[str, Any]:
        """
        Generate letter via LetterGen API
        
        Args:
            packet: PacketDB record
            packet_decision: PacketDecisionDB record
            packet_document: PacketDocumentDB record
            letter_type: Type of letter ('affirmation', 'non-affirmation', 'dismissal')
            
        Returns:
            Dictionary with letter metadata from LetterGen API:
            {
                "blob_url": "...",
                "filename": "...",
                "file_size_bytes": ...,
                "template_used": "...",
                "generated_at": "...",
                "inbound_json_blob_url": "...",
                "inbound_metadata_blob_url": "..."
            }
            
        Raises:
            LetterGenerationError: If letter generation fails after all retries
        """
        logger.info(
            f"Generating {letter_type} letter for packet_id={packet.packet_id} | "
            f"decision_id={packet_decision.packet_decision_id}"
        )
        
        # Build request payload
        if letter_type == 'affirmation':
            payload = self._build_affirmation_request(packet, packet_decision, packet_document)
            endpoint = '/api/v2/affirmation'
        elif letter_type == 'non-affirmation':
            payload = self._build_non_affirmation_request(packet, packet_decision, packet_document)
            endpoint = '/api/v2/non-affirmation'
        elif letter_type == 'dismissal':
            payload = self._build_dismissal_request(packet, packet_decision, packet_document)
            endpoint = '/api/v2/dismissal'
        else:
            raise ValueError(f"Unknown letter_type: {letter_type}")
        
        # Call LetterGen API with retry logic
        response = self._call_lettergen_api_with_retry(endpoint, payload)
        
        # Store full API response in letter_package for audit and recovery
        # Also add our internal tracking fields
        letter_metadata = {
            # Core API response fields
            "success": response.get('success', True),
            "filename": response.get('filename'),
            "blob_url": response.get('blob_url'),
            "file_size_bytes": response.get('file_size_bytes'),
            "letter_type": response.get('letter_type', letter_type),
            "channel": response.get('channel'),
            "fax_number": response.get('fax_number'),
            "generated_at": response.get('generated_at') or datetime.utcnow().isoformat(),
            "template_used": response.get('template_used'),
            "fax_metadata_file": response.get('fax_metadata_file'),
            "fax_metadata_blob_url": response.get('fax_metadata_blob_url'),
            "inbound_json_blob_url": response.get('inbound_json_blob_url'),
            "inbound_metadata_blob_url": response.get('inbound_metadata_blob_url'),
            # Internal tracking fields
            "generated_by": "ServiceOps",
            "api_response": response  # Store full response for audit
        }
        
        logger.info(
            f"Successfully generated {letter_type} letter for packet_id={packet.packet_id} | "
            f"blob_url={letter_metadata.get('blob_url')}"
        )
        
        return letter_metadata
    
    def _build_affirmation_request(
        self,
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        packet_document: PacketDocumentDB
    ) -> Dict[str, Any]:
        """
        Build request payload for affirmation letter matching LetterGen API contract.
        
        API expects flat structure:
        - patient_name (string | null)
        - patient_id (string | null)
        - date (string | null) - YYYY-MM-DD format
        - provider_name (string | null)
        - channel (string) - "mail" or "fax" (default: "mail")
        - fax_number (string | null) - required if channel="fax"
        
        Additional properties allowed (API supports additionalProperties: true)
        """
        extracted_fields = packet_document.updated_extracted_fields or packet_document.extracted_fields or {}
        fields = extracted_fields.get('fields', {}) if isinstance(extracted_fields, dict) else {}
        
        def get_field_value(field_name: str, default: str = "") -> str:
            field_data = fields.get(field_name, {})
            if isinstance(field_data, dict):
                return field_data.get('value', default)
            return field_data if field_data else default
        
        # Extract patient name (full name, not split)
        patient_name = packet.beneficiary_name or ""
        
        # Extract patient ID (MBI)
        patient_id = packet.beneficiary_mbi or ""
        
        # Format date as YYYY-MM-DD
        date_str = None
        if packet.received_date:
            date_str = packet.received_date.strftime("%Y-%m-%d")
        
        # Extract provider name
        provider_name = packet.provider_name or ""
        
        # Determine channel based on channel_type_id
        # Keep channel_type_id mapping: 1=Portal, 2=Fax, 3=ESMD
        channel_type_name = self._get_channel_type_name(packet.channel_type_id)
        
        # Map to API's channel field
        # API expects "mail" or "fax", but we'll send channel_type_name and let API handle it
        # If API requires "mail"/"fax", we'll map: 2=Fax→"fax", 1/3→"mail"
        # For now, keep channel_type_name as-is per user request
        channel = channel_type_name  # "Portal", "Fax", or "ESMD"
        
        # Extract fax number (only if channel is Fax)
        # Don't worry about fax extraction for now - integration not sending fax details yet
        fax_number = None
        if packet.channel_type_id == 2:  # Fax channel
            fax_number = packet.provider_fax or get_field_value('provider_fax') or None
        
        # Build flat request payload matching API contract
        request_payload = {
            "patient_name": patient_name,
            "patient_id": patient_id,
            "date": date_str,
            "provider_name": provider_name,
            "channel": channel,  # "Portal", "Fax", or "ESMD"
            "fax_number": fax_number  # None if not Fax channel or not available
        }
        
        # Add additional fields (API allows additionalProperties: true)
        # These can be used by the letter template
        additional_fields = {
            "case_id": packet.external_id,
            "decision_tracking_id": str(packet.decision_tracking_id),
            "provider_npi": packet.provider_npi or "",
            "provider_address": get_field_value('provider_address'),
            "provider_city": get_field_value('provider_city'),
            "provider_state": get_field_value('provider_state'),
            "provider_zip": get_field_value('provider_zip'),
            "provider_phone": get_field_value('provider_phone'),
            "beneficiary_mbi": packet.beneficiary_mbi or "",
            "beneficiary_date_of_birth": get_field_value('patient_date_of_birth'),
            "decision_outcome": "AFFIRM",
            "decision_subtype": packet_decision.decision_subtype or "STANDARD_PA",
            "part_type": packet_decision.part_type or "B",
            "utn": packet_decision.utn,
            "submission_date": packet.received_date.isoformat() if packet.received_date else None
        }
        
        # Add procedures if available
        procedures = self._extract_procedures_from_decision(packet_decision)
        if procedures:
            additional_fields["procedures"] = procedures
        
        # Add medical documents if available
        medical_docs = packet_decision.letter_medical_docs
        if medical_docs and isinstance(medical_docs, list):
            additional_fields["medical_documents"] = medical_docs
        
        # Merge additional fields into request payload
        request_payload.update(additional_fields)
        
        return request_payload
    
    def _build_non_affirmation_request(
        self,
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        packet_document: PacketDocumentDB
    ) -> Dict[str, Any]:
        """Build request payload for non-affirmation letter"""
        # Start with affirmation payload structure
        request_payload = self._build_affirmation_request(packet, packet_decision, packet_document)
        
        # Update decision outcome in additional fields
        request_payload["decision_outcome"] = "NON_AFFIRM"
        
        # Add review codes and program codes from procedures
        procedures = request_payload.get("procedures", [])
        if procedures:
            # Extract review_codes and program_codes from first procedure
            first_proc = procedures[0] if isinstance(procedures, list) else {}
            request_payload["review_codes"] = first_proc.get('review_codes', '')
            request_payload["program_codes"] = first_proc.get('program_codes', '')
        
        return request_payload
    
    def _build_dismissal_request(
        self,
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        packet_document: PacketDocumentDB
    ) -> Dict[str, Any]:
        """Build request payload for dismissal letter matching LetterGen API contract"""
        extracted_fields = packet_document.updated_extracted_fields or packet_document.extracted_fields or {}
        fields = extracted_fields.get('fields', {}) if isinstance(extracted_fields, dict) else {}
        
        def get_field_value(field_name: str, default: str = "") -> str:
            field_data = fields.get(field_name, {})
            if isinstance(field_data, dict):
                return field_data.get('value', default)
            return field_data if field_data else default
        
        # Extract patient name (full name, not split)
        patient_name = packet.beneficiary_name or ""
        
        # Extract patient ID (MBI)
        patient_id = packet.beneficiary_mbi or ""
        
        # Format date as YYYY-MM-DD
        date_str = None
        if packet.received_date:
            date_str = packet.received_date.strftime("%Y-%m-%d")
        
        # Extract provider name
        provider_name = packet.provider_name or ""
        
        # Determine channel based on channel_type_id
        channel_type_name = self._get_channel_type_name(packet.channel_type_id)
        channel = channel_type_name  # "Portal", "Fax", or "ESMD"
        
        # Extract fax number (only if channel is Fax)
        # Don't worry about fax extraction for now - integration not sending fax details yet
        fax_number = None
        if packet.channel_type_id == 2:  # Fax channel
            fax_number = packet.provider_fax or get_field_value('provider_fax') or None
        
        # Build flat request payload matching API contract
        request_payload = {
            "patient_name": patient_name,
            "patient_id": patient_id,
            "date": date_str,
            "provider_name": provider_name,
            "channel": channel,  # "Portal", "Fax", or "ESMD"
            "fax_number": fax_number  # None if not Fax channel or not available
        }
        
        # Add additional fields (API allows additionalProperties: true)
        additional_fields = {
            "case_id": packet.external_id,
            "decision_tracking_id": str(packet.decision_tracking_id),
            "provider_npi": packet.provider_npi or "",
            "provider_address": get_field_value('provider_address'),
            "provider_city": get_field_value('provider_city'),
            "provider_state": get_field_value('provider_state'),
            "provider_zip": get_field_value('provider_zip'),
            "provider_phone": get_field_value('provider_phone'),
            "beneficiary_mbi": packet.beneficiary_mbi or "",
            "beneficiary_date_of_birth": get_field_value('patient_date_of_birth'),
            "decision_outcome": "DISMISSAL",
            "denial_reason": packet_decision.denial_reason or "",
            "denial_details": packet_decision.denial_details or {},
            "submission_date": packet.received_date.isoformat() if packet.received_date else None
        }
        
        # Merge additional fields into request payload
        request_payload.update(additional_fields)
        
        return request_payload
    
    def _call_lettergen_api_with_retry(
        self,
        endpoint: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call LetterGen API with retry logic for transient failures
        
        Args:
            endpoint: API endpoint (e.g., '/api/v2/affirmation')
            payload: Request payload
            
        Returns:
            Response dictionary from LetterGen API
            
        Raises:
            LetterGenerationError: If all retries fail
        """
        if not self.base_url:
            raise LetterGenerationError("LETTERGEN_BASE_URL not configured")
        
        url = f"{self.base_url.rstrip('/')}{endpoint}"
        
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"Calling LetterGen API: {url} | "
                    f"Attempt {attempt + 1}/{self.max_retries}"
                )
                
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, json=payload)
                    
                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code == 400:
                        # Bad Request - don't retry
                        error_details = response.json() if response.content else {}
                        error_msg = error_details.get('detail', error_details.get('message', 'Bad request'))
                        raise LetterGenerationError(
                            f"LetterGen API bad request (400): {error_msg} | "
                            f"Details: {error_details}"
                        )
                    elif response.status_code == 422:
                        # Validation error - don't retry
                        # Parse detailed validation errors from FastAPI format
                        error_details = response.json() if response.content else {}
                        error_msg = error_details.get('detail', 'Validation error')
                        
                        # Extract field-level errors if available
                        if isinstance(error_msg, list):
                            # FastAPI validation error format: [{"loc": ["body", "field"], "msg": "...", "type": "..."}]
                            field_errors = []
                            for err in error_msg:
                                if isinstance(err, dict):
                                    loc = err.get('loc', [])
                                    msg = err.get('msg', '')
                                    field_errors.append(f"{'.'.join(str(x) for x in loc)}: {msg}")
                            error_msg = "; ".join(field_errors) if field_errors else "Validation error"
                        elif isinstance(error_msg, dict):
                            error_msg = error_msg.get('message', str(error_msg))
                        else:
                            error_msg = str(error_msg)
                        
                        raise LetterGenerationError(
                            f"LetterGen API validation error (422): {error_msg} | "
                            f"Details: {error_details}"
                        )
                    elif response.status_code in [500, 502, 503, 504]:
                        # Server error - retry
                        error_msg = f"LetterGen API server error ({response.status_code})"
                        last_exception = LetterGenerationError(error_msg)
                        logger.warning(f"{error_msg} | Attempt {attempt + 1}/{self.max_retries}")
                    else:
                        # Other error - don't retry
                        error_msg = f"LetterGen API error ({response.status_code}): {response.text}"
                        raise LetterGenerationError(error_msg)
                        
            except httpx.TimeoutException as e:
                last_exception = LetterGenerationError(f"LetterGen API timeout: {str(e)}")
                logger.warning(f"LetterGen API timeout | Attempt {attempt + 1}/{self.max_retries}")
            except httpx.RequestError as e:
                last_exception = LetterGenerationError(f"LetterGen API request error: {str(e)}")
                logger.warning(f"LetterGen API request error | Attempt {attempt + 1}/{self.max_retries}")
            except LetterGenerationError as e:
                # Re-raise validation errors immediately (no retry)
                raise
            
            # Exponential backoff before retry
            if attempt < self.max_retries - 1:
                delay = self.retry_base_seconds * (2 ** attempt)
                logger.debug(f"Waiting {delay}s before retry...")
                time.sleep(delay)
        
        # All retries exhausted
        raise LetterGenerationError(
            f"LetterGen API call failed after {self.max_retries} attempts: {str(last_exception)}"
        )
    
    def reprocess_by_urls(
        self,
        inbound_json_blob_url: str,
        inbound_metadata_blob_url: str
    ) -> Dict[str, Any]:
        """
        Reprocess letter generation using recovery endpoint
        
        Args:
            inbound_json_blob_url: Blob URL to inbound JSON
            inbound_metadata_blob_url: Blob URL to inbound metadata
            
        Returns:
            Response dictionary from LetterGen API
        """
        if not self.base_url:
            raise LetterGenerationError("LETTERGEN_BASE_URL not configured")
        
        endpoint = "/api/v2/recovery"
        payload = {
            "inbound_json_blob_url": inbound_json_blob_url,
            "inbound_metadata_blob_url": inbound_metadata_blob_url
        }
        
        return self._call_lettergen_api_with_retry(endpoint, payload)
    
    def _get_channel_type_name(self, channel_type_id: Optional[int]) -> str:
        """Convert channel_type_id to channel name"""
        channel_map = {
            1: "Portal",
            2: "Fax",
            3: "ESMD"
        }
        return channel_map.get(channel_type_id, "Unknown")
    
    def _extract_procedures_from_decision(self, packet_decision: PacketDecisionDB) -> list:
        """Extract procedures from packet_decision (if stored in esmd_request_payload)"""
        procedures = []
        
        if packet_decision.esmd_request_payload and isinstance(packet_decision.esmd_request_payload, dict):
            esmd_procedures = packet_decision.esmd_request_payload.get('procedures', [])
            if isinstance(esmd_procedures, list):
                procedures = esmd_procedures
        
        return procedures

