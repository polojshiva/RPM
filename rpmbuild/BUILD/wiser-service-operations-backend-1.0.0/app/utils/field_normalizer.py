"""
Field Normalization Utility
Standardizes extracted_fields structure for reliable processing
"""
import logging
from typing import Dict, Any, Optional, List
from collections import Counter
import copy

logger = logging.getLogger(__name__)


class FieldNormalizer:
    """
    Normalizes extracted_fields to ensure:
    - Consistent field name format (Title Case)
    - No duplicate field names (case-insensitive)
    - Consistent data types (confidence float, field_type normalized, values string)
    - Clean structure (no duplicate field structures in raw)
    """
    
    # Field name normalization mapping (known variations)
    FIELD_NAME_MAPPING = {
        # Beneficiary fields
        'beneficiary name': 'Beneficiary Name',
        'patient name': 'Beneficiary Name',
        'member name': 'Beneficiary Name',
        'beneficiary full name': 'Beneficiary Name',
        'beneficiary first name': 'Beneficiary First Name',
        'patient first name': 'Beneficiary First Name',
        'first name': 'Beneficiary First Name',
        'beneficiary last name': 'Beneficiary Last Name',
        'patient last name': 'Beneficiary Last Name',
        'last name': 'Beneficiary Last Name',
        'beneficiary medicare id': 'Beneficiary Medicare ID',
        'medicare id': 'Beneficiary Medicare ID',
        'mbi': 'Beneficiary Medicare ID',
        'beneficiary mbi': 'Beneficiary Medicare ID',
        'medicare beneficiary identifier': 'Beneficiary Medicare ID',
        'hicn': 'Beneficiary Medicare ID',
        'beneficiary dob': 'Beneficiary DOB',
        'patient dob': 'Beneficiary DOB',
        'date of birth': 'Beneficiary DOB',
        
        # Provider fields
        'facility provider name': 'Facility Provider Name',
        'attending physician name': 'Attending Physician Name',
        'provider name': 'Facility Provider Name',
        'rendering provider name': 'Facility Provider Name',
        'billing provider name': 'Facility Provider Name',
        'attending physician npi': 'Attending Physician NPI',
        'facility provider npi': 'Facility Provider NPI',
        'provider npi': 'Facility Provider NPI',
        'rendering provider npi': 'Facility Provider NPI',
        'billing provider npi': 'Facility Provider NPI',
        'npi': 'Facility Provider NPI',
        'requester fax': 'Requester Fax',
        'provider fax': 'Requester Fax',
        'facility provider fax': 'Requester Fax',
        
        # Procedure codes
        'procedure code set 1': 'Procedure Code set 1',
        'procedure code 1': 'Procedure Code set 1',
        'hcpcs code 1': 'Procedure Code set 1',
        'procedure code set 2': 'Procedure Code set 2',
        'procedure code 2': 'Procedure Code set 2',
        'hcpcs code 2': 'Procedure Code set 2',
        'procedure code set 3': 'Procedure Code set 3',
        'procedure code 3': 'Procedure Code set 3',
        'hcpcs code 3': 'Procedure Code set 3',
        'hcpcs': 'Procedure Code set 1',  # If single HCPCS, map to set 1
        
        # Submission type
        'submission type': 'Submission Type',
        'submissiontype': 'Submission Type',
        'request type': 'Submission Type',
        
        # Service type
        'service type': 'Service Type',
        'servicetype': 'Service Type',
        'type of service': 'Service Type',
    }
    
    @staticmethod
    def normalize_field_name(field_name: str) -> str:
        """
        Normalize field name to Title Case standard format.
        
        Args:
            field_name: Original field name
            
        Returns:
            Normalized field name
        """
        if not field_name or not isinstance(field_name, str):
            return field_name
        
        # Trim whitespace
        field_name = field_name.strip()
        
        # Check mapping first
        field_lower = field_name.lower()
        if field_lower in FieldNormalizer.FIELD_NAME_MAPPING:
            return FieldNormalizer.FIELD_NAME_MAPPING[field_lower]
        
        # If not in mapping, convert to Title Case
        # Handle special cases like "set 1" -> "set 1" (not "Set 1")
        words = field_name.split()
        normalized_words = []
        for word in words:
            if word.lower() in ['set', 'of', 'the', 'a', 'an']:
                normalized_words.append(word.lower())
            else:
                normalized_words.append(word.capitalize())
        
        return ' '.join(normalized_words)
    
    @staticmethod
    def normalize_field_value(field_data: Any) -> Dict[str, Any]:
        """
        Normalize field value structure and data types.
        
        Args:
            field_data: Field data (dict or simple value)
            
        Returns:
            Normalized field data dict with: value, confidence, field_type, source
        """
        if isinstance(field_data, dict):
            # Extract values
            value = field_data.get('value', '')
            confidence = field_data.get('confidence', 1.0)
            field_type = field_data.get('field_type', 'STRING')
            source = field_data.get('source', 'OCR')
        else:
            # Simple value - convert to dict
            value = str(field_data) if field_data is not None else ''
            confidence = 1.0
            field_type = 'STRING'
            source = 'OCR'
        
        # Normalize value: always string, trim whitespace
        value_str = str(value).strip() if value else ''
        
        # Normalize confidence: always float
        if isinstance(confidence, int):
            confidence_float = float(confidence)
        elif isinstance(confidence, float):
            confidence_float = confidence
        else:
            try:
                confidence_float = float(confidence)
            except (ValueError, TypeError):
                confidence_float = 1.0
        
        # Normalize field_type: remove "DocumentFieldType." prefix
        if isinstance(field_type, str):
            if 'DocumentFieldType.' in field_type:
                field_type_clean = field_type.replace('DocumentFieldType.', '')
            else:
                field_type_clean = field_type
        else:
            field_type_clean = 'STRING'
        
        return {
            'value': value_str,
            'confidence': confidence_float,
            'field_type': field_type_clean,
            'source': source
        }
    
    @staticmethod
    def deduplicate_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove duplicate field names (case-insensitive).
        Keeps the first occurrence or the one with highest confidence.
        
        Args:
            fields: Dictionary of field_name -> field_data
            
        Returns:
            Deduplicated fields dictionary
        """
        if not fields:
            return {}
        
        # Build case-insensitive map
        field_map = {}  # lowercase_name -> (original_name, field_data, confidence)
        duplicates_log = []
        
        for field_name, field_data in fields.items():
            field_lower = field_name.lower()
            
            # Normalize field data
            normalized_data = FieldNormalizer.normalize_field_value(field_data)
            confidence = normalized_data.get('confidence', 0.0)
            
            if field_lower in field_map:
                # Duplicate found
                existing_name, existing_data, existing_confidence = field_map[field_lower]
                
                # Keep the one with higher confidence, or first if same
                if confidence > existing_confidence:
                    duplicates_log.append({
                        'removed': existing_name,
                        'kept': field_name,
                        'reason': 'higher_confidence'
                    })
                    field_map[field_lower] = (field_name, normalized_data, confidence)
                else:
                    duplicates_log.append({
                        'removed': field_name,
                        'kept': existing_name,
                        'reason': 'lower_confidence_or_first'
                    })
            else:
                # First occurrence
                field_map[field_lower] = (field_name, normalized_data, confidence)
        
        # Rebuild fields dict with normalized names
        deduplicated = {}
        for field_lower, (original_name, field_data, _) in field_map.items():
            # Normalize the field name
            normalized_name = FieldNormalizer.normalize_field_name(original_name)
            deduplicated[normalized_name] = field_data
        
        if duplicates_log:
            logger.info(f"Deduplicated {len(duplicates_log)} duplicate field(s): {duplicates_log}")
        
        return deduplicated
    
    @staticmethod
    def clean_raw_structure(raw_data: Dict[str, Any], source: str = 'payload') -> Dict[str, Any]:
        """
        Clean raw structure to avoid duplicate field structures.
        Removes 'fields' from raw.ocr if present (fields should only be at top level).
        
        Args:
            raw_data: Raw data dictionary
            source: Source identifier ('payload', 'OCR_INITIAL', etc.)
            
        Returns:
            Cleaned raw structure (metadata only, no duplicate fields)
        """
        if not raw_data or not isinstance(raw_data, dict):
            return {'source': source}
        
        cleaned = {'source': source}
        
        # Copy metadata fields only (not 'fields')
        for key, value in raw_data.items():
            if key == 'fields':
                # Skip - fields should not be in raw
                logger.debug(f"Removed 'fields' from raw structure (should be at top level only)")
                continue
            elif key == 'ocr' and isinstance(value, dict):
                # Clean ocr object - keep metadata, remove fields
                ocr_cleaned = {}
                for ocr_key, ocr_value in value.items():
                    if ocr_key == 'fields':
                        # Skip - fields should not be in raw.ocr
                        logger.debug(f"Removed 'fields' from raw.ocr (should be at top level only)")
                        continue
                    else:
                        ocr_cleaned[ocr_key] = ocr_value
                cleaned['ocr'] = ocr_cleaned
            else:
                cleaned[key] = value
        
        return cleaned
    
    @staticmethod
    def normalize_extracted_fields(extracted_fields: Dict[str, Any], source: str = 'OCR_INITIAL') -> Dict[str, Any]:
        """
        Full normalization of extracted_fields structure.
        
        Steps:
        1. Normalize field names
        2. Deduplicate fields (case-insensitive)
        3. Normalize field values (data types)
        4. Clean raw structure (remove duplicate field structures)
        
        Args:
            extracted_fields: Original extracted_fields dictionary
            source: Source identifier for tracking
            
        Returns:
            Fully normalized extracted_fields dictionary
        """
        if not extracted_fields or not isinstance(extracted_fields, dict):
            return {
                'fields': {},
                'raw': {'source': source},
                'source': source
            }
        
        # Extract fields
        original_fields = extracted_fields.get('fields', {})
        
        # Step 1: Deduplicate and normalize field names
        normalized_fields = FieldNormalizer.deduplicate_fields(original_fields)
        
        # Step 2: Normalize field values (already done in deduplicate_fields)
        # (normalize_field_value is called within deduplicate_fields)
        
        # Step 3: Clean raw structure
        raw_data = extracted_fields.get('raw', {})
        cleaned_raw = FieldNormalizer.clean_raw_structure(raw_data, source)
        
        # Build normalized structure
        normalized = {
            'fields': normalized_fields,
            'raw': cleaned_raw,
            'source': source
        }
        
        # Copy other metadata fields
        for key in ['coversheet_type', 'doc_type', 'overall_document_confidence', 
                    'duration_ms', 'page_number', 'last_updated_at', 'last_updated_by']:
            if key in extracted_fields:
                normalized[key] = extracted_fields[key]
        
        return normalized

