"""
Field Validation Service
Validates extracted fields according to business rules.
Only shows errors for unfixable issues or auto-fix failures.
"""
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Diagnosis codes that require specific diagnosis codes
REQUIRED_DIAGNOSIS_PROCEDURES = {
    'vagus_nerve_stimulation': {
        'procedure_codes': ['64553', '64554', '64555', '64556', '64557', '64558', '64559', '64560', '64561', '64562'],
        'required_diagnosis_codes': [
            'G40011', 'G40019', 'G40111', 'G40119', 'G40211', 'G40219',
            'F3132', 'F314', 'F3181', 'F321', 'F322', 'F331', 'F332',
            'Z006', 'N3941', 'N3946', 'R338', 'R339', 'R350', 'R3911', 'R3914', 'R3915',
            'E08621', 'E09621', 'E10621', 'E11621', 'E13621',
            'I83011', 'I83012', 'I83013', 'I83015', 'I83018',
            'I83021', 'I83022', 'I83023', 'I83024', 'I83025', 'I83028',
            'I83211', 'I83212'
        ]
    },
    'sacral_nerve_stimulation': {
        'procedure_codes': ['64553', '64554', '64555', '64556', '64557', '64558', '64559', '64560', '64561', '64562'],
        'required_diagnosis_codes': [
            'G40011', 'G40019', 'G40111', 'G40119', 'G40211', 'G40219',
            'F3132', 'F314', 'F3181', 'F321', 'F322', 'F331', 'F332',
            'Z006', 'N3941', 'N3946', 'R338', 'R339', 'R350', 'R3911', 'R3914', 'R3915',
            'E08621', 'E09621', 'E10621', 'E11621', 'E13621',
            'I83011', 'I83012', 'I83013', 'I83015', 'I83018',
            'I83021', 'I83022', 'I83023', 'I83024', 'I83025', 'I83028',
            'I83211', 'I83212'
        ]
    },
    'skin_substitutes': {
        'procedure_codes': ['Q4101', 'Q4102', 'Q4103', 'Q4104', 'Q4105', 'Q4106', 'Q4107', 'Q4108', 'Q4109', 'Q4110'],
        'required_diagnosis_codes': [
            'G40011', 'G40019', 'G40111', 'G40119', 'G40211', 'G40219',
            'F3132', 'F314', 'F3181', 'F321', 'F322', 'F331', 'F332',
            'Z006', 'N3941', 'N3946', 'R338', 'R339', 'R350', 'R3911', 'R3914', 'R3915',
            'E08621', 'E09621', 'E10621', 'E11621', 'E13621',
            'I83011', 'I83012', 'I83013', 'I83015', 'I83018',
            'I83021', 'I83022', 'I83023', 'I83024', 'I83025', 'I83028',
            'I83211', 'I83212'
        ]
    }
}


def get_field_value(fields: Dict[str, Any], field_names: List[str]) -> Optional[str]:
    """Helper to get field value from fields dict"""
    for field_name in field_names:
        if field_name in fields:
            field_data = fields[field_name]
            if isinstance(field_data, dict):
                value = str(field_data.get('value', '')).strip()
            else:
                value = str(field_data).strip()
            if value and value not in ['TBD', 'N/A', '']:
                return value
    return None


def validate_state(state: str) -> List[str]:
    """
    Validation Rule 2: State must be NJ (after normalization).
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    if not state:
        errors.append("State is required")
        return errors
    
    state_normalized = state.strip().upper()
    if state_normalized not in ['NJ', 'NEW JERSEY']:
        errors.append(f"State must be NJ. Current: {state}")
    
    return errors


def validate_diagnosis_code_requirement(
    diagnosis_code: Optional[str],
    procedure_codes: List[str],
    part_type: Optional[str]
) -> List[str]:
    """
    Validation Rule 1, 15, 18: Diagnosis code requirements.
    
    - Not mandatory for Part A (except for specific procedures)
    - Required for Vagus Nerve stimulation, Sacral Nerve stimulation, and skin substitutes
    - Must be in allowed list for these procedures
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # If Part A and not in exception list, no requirement
    if part_type and part_type.upper() == 'PART_A':
        # Check if any procedure code matches exception procedures
        requires_diagnosis = False
        required_codes = []
        
        for proc_type, proc_info in REQUIRED_DIAGNOSIS_PROCEDURES.items():
            if any(proc_code in procedure_codes for proc_code in proc_info['procedure_codes']):
                requires_diagnosis = True
                required_codes = proc_info['required_diagnosis_codes']
                break
        
        if not requires_diagnosis:
            return errors  # No requirement for Part A
    
    # Check if diagnosis is required for specific procedures
    requires_diagnosis = False
    required_codes = []
    procedure_name = ""
    
    for proc_type, proc_info in REQUIRED_DIAGNOSIS_PROCEDURES.items():
        if any(proc_code in procedure_codes for proc_code in proc_info['procedure_codes']):
            requires_diagnosis = True
            required_codes = proc_info['required_diagnosis_codes']
            procedure_name = proc_type.replace('_', ' ').title()
            break
    
    if requires_diagnosis:
        if not diagnosis_code or not diagnosis_code.strip():
            errors.append(f"Diagnosis code required for {procedure_name}")
        else:
            # Check if diagnosis code is in allowed list
            diagnosis_clean = diagnosis_code.replace('.', '').strip().upper()
            diagnosis_codes = [code.strip().upper() for code in diagnosis_clean.split(',')]
            
            # Check if any diagnosis code is in the required list
            found_valid = False
            for diag_code in diagnosis_codes:
                if diag_code in required_codes:
                    found_valid = True
                    break
            
            if not found_valid:
                errors.append(
                    f"Diagnosis code must be one of the required codes for {procedure_name}. "
                    f"Current: {diagnosis_code}"
                )
    
    return errors


def validate_request_type(request_type: Optional[str]) -> List[str]:
    """
    Validation Rule 3: Request Type must be "I" (Initial) or "R" (Resubmission).
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    if not request_type:
        errors.append("Request Type is required")
        return errors
    
    request_type_normalized = request_type.strip().upper()
    if request_type_normalized not in ['I', 'INITIAL', 'R', 'RESUBMISSION']:
        errors.append(f"Request Type must be 'I' (Initial) or 'R' (Resubmission). Current: {request_type}")
    
    return errors


def validate_phone_after_fix(phone: str, field_name: str) -> List[str]:
    """
    Validation Rule 4: Phone/Fax must be 10 digits after auto-fix.
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    if not phone:
        return errors  # Empty is OK (not required)
    
    # Phone should already be normalized by auto-fix (digits only)
    digits_only = ''.join(c for c in phone if c.isdigit())
    
    if len(digits_only) != 10:
        errors.append(f"{field_name} must be 10 digits. Current: {len(digits_only)} digits")
    
    return errors


def validate_date_after_fix(date_str: str, field_name: str, required: bool = False) -> List[str]:
    """
    Validation Rule 5: Date must be YYYY-MM-DD format after auto-fix.
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    if not date_str:
        if required:
            errors.append(f"{field_name} is required")
        return errors
    
    # Date should already be normalized by auto-fix
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        errors.append(f"{field_name} must be in YYYY-MM-DD format. Current: {date_str}")
    
    return errors


def validate_diagnosis_code_format(diagnosis: str) -> List[str]:
    """
    Validation Rule 6: Diagnosis code must not have periods after auto-fix.
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    if not diagnosis:
        return errors  # Empty is OK
    
    # Diagnosis should already be normalized by auto-fix (no periods)
    if '.' in diagnosis:
        errors.append("Diagnosis code must not contain periods. Current: " + diagnosis)
    
    return errors


def validate_place_of_service(place: Optional[str], location: Optional[str]) -> List[str]:
    """
    Validation Rule 7: Place of Service must be numeric only.
    If both Place and Location exist → use Place of Service.
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Use Place if both exist
    value_to_check = place if place else location
    
    if not value_to_check:
        return errors  # Empty is OK
    
    # Check numeric only
    if not value_to_check.isdigit():
        errors.append(f"Place of Service must be numeric only. Current: {value_to_check}")
    
    return errors


def validate_npi(npi: str, field_name: str) -> List[str]:
    """
    Validation Rule 8: NPI must be exactly 10 digits (after normalization).
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    if not npi:
        return errors  # Empty is OK (not always required)
    
    # NPI should already be normalized (10 digits, padded if 9)
    digits_only = ''.join(c for c in npi if c.isdigit())
    
    if len(digits_only) != 10:
        errors.append(f"{field_name} must be exactly 10 digits. Current: {len(digits_only)} digits")
    
    return errors


def validate_provider_address(
    address_1: Optional[str],
    address_2: Optional[str],
    city: Optional[str],
    state: Optional[str]
) -> List[str]:
    """
    Validation Rule 9: Provider address validation.
    1. State value should NOT be in City field (should be moved by auto-fix)
    2. Address 1 should not be too long (suite should be in Address 2)
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Check if state abbreviation is still in city (auto-fix should have moved it)
    # Use word boundaries to match only complete words, not substrings within city names
    # This prevents false positives like "Manalapan" (contains "PA"), "Parsippany" (contains "NY"), 
    # "Camden" (contains "CA"), "MULLICA HILL" (contains "CA")
    if city:
        city_upper = city.upper()
        state_abbreviations = ['NJ', 'NY', 'PA', 'CA', 'TX', 'FL']
        for abbrev in state_abbreviations:
            # Only match if state abbreviation appears as a separate word (word boundaries)
            if re.search(rf'\b{re.escape(abbrev)}\b', city_upper):
                errors.append(f"State abbreviation '{abbrev}' found in City field. Should be in State field.")
                break
    
    # Check if address_1 is too long and contains suite (should be moved by auto-fix)
    if address_1 and len(address_1) > 50:
        suite_indicators = ['suite', 'ste', 'apt', 'apartment', 'unit']
        address_1_lower = address_1.lower()
        for indicator in suite_indicators:
            if indicator in address_1_lower:
                errors.append(
                    f"Address 1 is too long and contains suite information. "
                    f"Suite should be moved to Address 2. Current length: {len(address_1)}"
                )
                break
    
    return errors


def validate_procedure_codes_optional(
    proc_code_2: Optional[str],
    proc_code_3: Optional[str],
    units_2: Optional[str],
    units_3: Optional[str]
) -> List[str]:
    """
    Validation Rule 10-11: Procedure codes 2 & 3 can be blank.
    Units of Service 2 & 3 can be blank if corresponding Proc code is also blank.
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # If proc_code_2 exists, units_2 should exist
    if proc_code_2 and proc_code_2.strip() and (not units_2 or not units_2.strip()):
        errors.append("Units of Service 2 is required when Procedure Code 2 is provided")
    
    # If proc_code_3 exists, units_3 should exist
    if proc_code_3 and proc_code_3.strip() and (not units_3 or not units_3.strip()):
        errors.append("Units of Service 3 is required when Procedure Code 3 is provided")
    
    return errors


def validate_ccn(ccn: Optional[str], part_type: Optional[str]) -> List[str]:
    """
    Validation Rule 14: For Part A, CCN should start with 31 or 83 and should be all digits.
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Only validate for Part A
    if not part_type or part_type.upper() != 'PART_A':
        return errors
    
    if not ccn:
        return errors  # Empty is OK (not always required)
    
    # Check all digits
    if not ccn.isdigit():
        errors.append(f"CCN must be all digits for Part A. Current: {ccn}")
        return errors
    
    # Check starts with 31 or 83
    if not (ccn.startswith('31') or ccn.startswith('83')):
        errors.append(f"CCN must start with 31 or 83 for Part A. Current: {ccn}")
    
    return errors


def validate_all_fields(
    extracted_fields: Dict[str, Any],
    packet: Any,  # PacketDB type, avoiding circular import
    db_session: Any  # Session type, avoiding circular import
) -> Dict[str, Any]:
    """
    Validate all fields according to business rules.
    
    Args:
        extracted_fields: Dictionary with 'fields' key containing field data
        packet: PacketDB instance
        db_session: Database session
    
    Returns:
        {
            'field_errors': {
                'field_name': ['error message 1', 'error message 2']
            },
            'auto_fix_applied': {
                'field_name': {
                    'original': 'original value',
                    'fixed': 'fixed value',
                    'status': 'success' | 'failed'
                }
            },
            'has_errors': bool,
            'validated_at': str,
            'validated_by': str
        }
    """
    if not extracted_fields or not isinstance(extracted_fields, dict):
        return {
            'field_errors': {},
            'auto_fix_applied': {},
            'has_errors': False,
            'validated_at': datetime.utcnow().isoformat(),
            'validated_by': 'system'
        }
    
    fields = extracted_fields.get('fields', {})
    if not fields:
        return {
            'field_errors': {},
            'auto_fix_applied': {},
            'has_errors': False,
            'validated_at': datetime.utcnow().isoformat(),
            'validated_by': 'system'
        }
    
    field_errors = {}
    
    # Get field values
    state = get_field_value(fields, ['Rendering/Facility State', 'Facility Provider State', 'State'])
    request_type = get_field_value(fields, ['Request Type', 'Submission Type'])
    phone = get_field_value(fields, ['Requester Phone', 'Provider Phone', 'Facility Provider Phone'])
    fax = get_field_value(fields, ['Requester Fax', 'Provider Fax', 'Facility Provider Fax'])
    date_service = get_field_value(fields, ['Anticipated Date of Service', 'Date of Service'])
    diagnosis_code = get_field_value(fields, ['Diagnosis Codes', 'Diagnosis Code'])
    place_of_service = get_field_value(fields, ['Place of Service', 'Place Of Service'])
    location_of_service = get_field_value(fields, ['Location of Service', 'Location Of Service'])
    facility_npi = get_field_value(fields, ['Facility Provider NPI', 'Rendering/Facility NPI', 'Provider NPI'])
    attending_npi = get_field_value(fields, ['Attending Physician NPI', 'Attending NPI'])
    proc_code_1 = get_field_value(fields, ['Procedure Code set 1', 'Procedure Code 1'])
    proc_code_2 = get_field_value(fields, ['Procedure Code set 2', 'Procedure Code 2'])
    proc_code_3 = get_field_value(fields, ['Procedure Code set 3', 'Procedure Code 3'])
    units_2 = get_field_value(fields, ['Units of Service set 2', 'Units of Service 2'])
    units_3 = get_field_value(fields, ['Units of Service set 3', 'Units of Service 3'])
    ccn = get_field_value(fields, ['Facility Provider CCN', 'Rendering/Facility PTAN/CCN', 'CCN'])
    address_1 = get_field_value(fields, ['Rendering/Facility Address Line 1', 'Facility Provider Address 1'])
    address_2 = get_field_value(fields, ['Rendering/Facility Address Line 2', 'Facility Provider Address 2'])
    city = get_field_value(fields, ['Rendering/Facility City', 'Facility Provider City'])
    
    # Get part type from packet or document
    part_type = None
    if hasattr(packet, 'part_type'):
        part_type = packet.part_type
    elif hasattr(packet, 'documents') and packet.documents:
        # Try to get from first document
        first_doc = packet.documents[0] if isinstance(packet.documents, list) else None
        if first_doc and hasattr(first_doc, 'part_type'):
            part_type = first_doc.part_type
    
    # Validation Rule 2: State must be NJ
    if state:
        state_errors = validate_state(state)
        if state_errors:
            field_errors['state'] = state_errors
    
    # Validation Rule 3: Request Type
    if request_type:
        request_type_errors = validate_request_type(request_type)
        if request_type_errors:
            field_errors['request_type'] = request_type_errors
    
    # Validation Rule 4: Phone/Fax after auto-fix
    if phone:
        phone_errors = validate_phone_after_fix(phone, 'Phone Number')
        if phone_errors:
            field_errors['phone_number'] = phone_errors
    
    if fax:
        fax_errors = validate_phone_after_fix(fax, 'Fax Number')
        if fax_errors:
            field_errors['fax_number'] = fax_errors
    
    # Validation Rule 5: Date format after auto-fix
    if date_service:
        date_errors = validate_date_after_fix(date_service, 'Anticipated Date of Service')
        if date_errors:
            field_errors['anticipated_date_of_service'] = date_errors
    
    # Validation Rule 6: Diagnosis code format
    if diagnosis_code:
        diagnosis_format_errors = validate_diagnosis_code_format(diagnosis_code)
        if diagnosis_format_errors:
            field_errors['diagnosis_code'] = diagnosis_format_errors
    
    # Validation Rule 7: Place of Service
    if place_of_service or location_of_service:
        place_errors = validate_place_of_service(place_of_service, location_of_service)
        if place_errors:
            field_errors['place_of_service'] = place_errors
    
    # Validation Rule 8: NPI
    if facility_npi:
        npi_errors = validate_npi(facility_npi, 'Facility Provider NPI')
        if npi_errors:
            field_errors['facility_npi'] = npi_errors
    
    if attending_npi:
        npi_errors = validate_npi(attending_npi, 'Attending Physician NPI')
        if npi_errors:
            field_errors['attending_npi'] = npi_errors
    
    # Validation Rule 9: Provider Address
    if address_1 or city or state:
        address_errors = validate_provider_address(address_1, address_2, city, state)
        if address_errors:
            field_errors['provider_address'] = address_errors
    
    # Validation Rule 10-11: Procedure Codes optional
    procedure_errors = validate_procedure_codes_optional(proc_code_2, proc_code_3, units_2, units_3)
    if procedure_errors:
        field_errors['procedure_codes'] = procedure_errors
    
    # Validation Rule 14: CCN
    if ccn:
        ccn_errors = validate_ccn(ccn, part_type)
        if ccn_errors:
            field_errors['ccn'] = ccn_errors
    
    # Validation Rule 1, 15, 18: Diagnosis code requirement
    procedure_codes = [p for p in [proc_code_1, proc_code_2, proc_code_3] if p]
    diagnosis_requirement_errors = validate_diagnosis_code_requirement(
        diagnosis_code, procedure_codes, part_type
    )
    if diagnosis_requirement_errors:
        if 'diagnosis_code' in field_errors:
            field_errors['diagnosis_code'].extend(diagnosis_requirement_errors)
        else:
            field_errors['diagnosis_code'] = diagnosis_requirement_errors
    
    # Get auto-fix results from extracted_fields if available
    auto_fix_applied = extracted_fields.get('auto_fix_applied', {})
    
    return {
        'field_errors': field_errors,
        'auto_fix_applied': auto_fix_applied,
        'has_errors': len(field_errors) > 0,
        'validated_at': datetime.utcnow().isoformat(),
        'validated_by': 'system'
    }
