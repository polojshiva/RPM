"""
Field Auto-Fix Service
Automatically fixes formatting issues in extracted fields without showing errors to users.
This includes phone/fax normalization, date formatting, diagnosis code cleanup, and address normalization.
"""
import logging
import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


def normalize_phone_number(phone: str) -> Tuple[str, bool]:
    """
    Remove all special characters from phone number, keep digits only.
    
    Args:
        phone: Phone number string (e.g., "(732) 849-0077")
    
    Returns:
        (normalized_phone, is_valid): Tuple of normalized phone and validity
        - is_valid = True if 10 digits after cleanup
        - is_valid = False if wrong length or missing digits
    """
    if not phone or not isinstance(phone, str):
        return "", False
    
    # Remove all non-digit characters
    digits_only = ''.join(c for c in phone if c.isdigit())
    
    # Check if valid (exactly 10 digits)
    is_valid = len(digits_only) == 10
    
    return digits_only, is_valid


def normalize_fax_number(fax: str) -> Tuple[str, bool]:
    """
    Same logic as phone number normalization.
    
    Args:
        fax: Fax number string (e.g., "732-849-0015")
    
    Returns:
        (normalized_fax, is_valid): Tuple of normalized fax and validity
    """
    return normalize_phone_number(fax)


def normalize_date(date_str: str) -> Tuple[str, bool]:
    """
    Convert date to YYYY-MM-DD format.
    
    Supports formats:
    - YYYY-MM-DD (already correct)
    - MM/DD/YYYY
    - DD/MM/YYYY (if day > 12, assume DD/MM)
    - YYYY/MM/DD
    
    Returns:
        (normalized_date, is_valid): Tuple of normalized date and validity
    """
    if not date_str or not isinstance(date_str, str):
        return "", False
    
    date_str = date_str.strip()
    if not date_str:
        return "", False
    
    # Try YYYY-MM-DD format (already correct)
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d"), True
    except ValueError:
        pass
    
    # Try MM/DD/YYYY format
    try:
        dt = datetime.strptime(date_str, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d"), True
    except ValueError:
        pass
    
    # Try DD/MM/YYYY format (if day > 12, assume DD/MM)
    try:
        parts = date_str.split("/")
        if len(parts) == 3:
            day, month, year = parts
            if int(day) > 12:  # Day is clearly > 12, so it's DD/MM/YYYY
                dt = datetime.strptime(date_str, "%d/%m/%Y")
                return dt.strftime("%Y-%m-%d"), True
    except (ValueError, IndexError):
        pass
    
    # Try YYYY/MM/DD format
    try:
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        return dt.strftime("%Y-%m-%d"), True
    except ValueError:
        pass
    
    # If none of the formats work, return invalid
    logger.warning(f"Could not parse date format: {date_str}")
    return "", False


def normalize_diagnosis_code(diagnosis: str) -> Tuple[str, bool]:
    """
    Remove periods, make comma-separated if multiple codes.
    
    Examples:
    - "G40.011" → "G40011"
    - "G40.011, M2551" → "G40011, M2551"
    - "812." → "812"
    
    Args:
        diagnosis: Diagnosis code string
    
    Returns:
        (normalized_code, is_valid): Tuple of normalized code and validity
    """
    if not diagnosis or not isinstance(diagnosis, str):
        return "", False
    
    diagnosis = diagnosis.strip()
    if not diagnosis:
        return "", False
    
    # Remove all periods
    normalized = diagnosis.replace(".", "")
    
    # Split by comma if multiple codes, trim each, rejoin
    if "," in normalized:
        codes = [code.strip() for code in normalized.split(",")]
        normalized = ", ".join(codes)
    
    # Trim final result
    normalized = normalized.strip()
    
    # Valid if not empty after normalization
    is_valid = len(normalized) > 0
    
    return normalized, is_valid


def normalize_address(
    address_1: Optional[str] = None,
    address_2: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None
) -> Dict[str, Tuple[str, bool]]:
    """
    Normalize address fields:
    1. Move state value from city to state if state is empty
    2. Move suite number from address_1 to address_2 if address_1 is long
    3. Normalize state: "New Jersey" → "NJ", other states → keep as-is (validation will catch non-NJ)
    
    Args:
        address_1: Address line 1
        address_2: Address line 2
        city: City name
        state: State name or abbreviation
        zip_code: ZIP code
    
    Returns:
        {
            'address_1': (normalized, is_valid),
            'address_2': (normalized, is_valid),
            'city': (normalized, is_valid),
            'state': (normalized, is_valid),
            'zip': (normalized, is_valid)
        }
    """
    result = {
        'address_1': (address_1 or "", True),
        'address_2': (address_2 or "", True),
        'city': (city or "", True),
        'state': (state or "", True),
        'zip': (zip_code or "", True)
    }
    
    # Normalize state abbreviations (common ones)
    state_abbreviations = {
        'new jersey': 'NJ',
        'nj': 'NJ',
        'new york': 'NY',
        'ny': 'NY',
        'pennsylvania': 'PA',
        'pa': 'PA',
        'california': 'CA',
        'ca': 'CA',
    }
    
    # Normalize state
    if result['state'][0]:
        state_lower = result['state'][0].lower().strip()
        if state_lower in state_abbreviations:
            result['state'] = (state_abbreviations[state_lower], True)
        else:
            # Keep as-is, validation will catch if not NJ
            result['state'] = (result['state'][0].strip(), True)
    
    # Check if state abbreviation is in city (e.g., "Whiting NJ")
    # Use word boundaries to match only complete words, not substrings within city names
    # This prevents false positives like "Manalapan" (contains "PA"), "Parsippany" (contains "NY"),
    # "Camden" (contains "CA"), "MULLICA HILL" (contains "CA")
    if result['city'][0] and not result['state'][0]:
        city_original = result['city'][0]
        city_lower = city_original.lower()
        for state_name, abbrev in state_abbreviations.items():
            # Only match if state abbreviation or name appears as a separate word (word boundaries)
            abbrev_match = re.search(rf'\b{re.escape(abbrev)}\b', city_lower, re.IGNORECASE)
            state_name_match = re.search(rf'\b{re.escape(state_name)}\b', city_lower, re.IGNORECASE)
            
            if abbrev_match or state_name_match:
                # Extract state from city (preserve original case)
                city_clean = re.sub(rf'\b{re.escape(abbrev)}\b', '', city_original, flags=re.IGNORECASE)
                city_clean = re.sub(rf'\b{re.escape(state_name)}\b', '', city_clean, flags=re.IGNORECASE)
                city_clean = city_clean.strip()
                city_clean = re.sub(r'\s+', ' ', city_clean)  # Clean up extra spaces
                result['city'] = (city_clean, True)
                result['state'] = (abbrev, True)
                break
    
    # Move suite number from address_1 to address_2 if address_1 is long (> 50 chars) or if suite is found
    if result['address_1'][0]:
        address_1_str = result['address_1'][0]
        # Look for suite indicators - match "Suite 100", "Ste 100", "Apt 100", etc.
        suite_pattern = r'\b(suite|ste|apt|apartment|unit)\s+#?\s*(\w+)\b'
        
        match = re.search(suite_pattern, address_1_str, re.IGNORECASE)
        # Extract suite if found AND (address is long OR address_2 is empty)
        if match and (len(address_1_str) > 50 or not result['address_2'][0]):
            suite_text = match.group(0)  # Full match like "Suite 100"
            address_1_clean = re.sub(suite_pattern, '', address_1_str, flags=re.IGNORECASE).strip()
            address_1_clean = re.sub(r'\s+', ' ', address_1_clean)  # Clean up extra spaces
            
            # Move suite to address_2
            address_2_new = suite_text
            if result['address_2'][0]:
                address_2_new = f"{result['address_2'][0]}, {suite_text}"
            
            result['address_1'] = (address_1_clean, True)
            result['address_2'] = (address_2_new, True)
    
    return result


def apply_auto_fix_to_fields(
    extracted_fields: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Apply auto-fix to all applicable fields in extracted_fields.
    
    Args:
        extracted_fields: Dictionary with 'fields' key containing field data
    
    Returns:
        (updated_extracted_fields, auto_fix_results): Tuple of updated fields and fix tracking
        auto_fix_results structure:
        {
            'field_name': {
                'original': 'original value',
                'fixed': 'fixed value',
                'status': 'success' | 'failed'
            }
        }
    """
    if not extracted_fields or not isinstance(extracted_fields, dict):
        return extracted_fields, {}
    
    # Create a copy to avoid modifying the original
    import copy
    updated_fields = copy.deepcopy(extracted_fields)
    
    # Get fields dict
    fields = updated_fields.get('fields', {})
    if not fields:
        return updated_fields, {}
    
    auto_fix_results = {}
    
    # Phone number fields
    phone_fields = ['Requester Phone', 'Provider Phone', 'Facility Provider Phone']
    for field_name in phone_fields:
        if field_name in fields:
            field_data = fields[field_name]
            original_value = field_data.get('value', '') if isinstance(field_data, dict) else str(field_data)
            
            if original_value:
                normalized, is_valid = normalize_phone_number(original_value)
                if normalized != original_value:
                    # Update field value
                    if isinstance(field_data, dict):
                        fields[field_name]['value'] = normalized
                    else:
                        fields[field_name] = {'value': normalized, 'confidence': 1.0, 'field_type': 'STRING'}
                    
                    auto_fix_results[field_name] = {
                        'original': original_value,
                        'fixed': normalized,
                        'status': 'success' if is_valid else 'failed'
                    }
    
    # Fax number fields
    fax_fields = ['Requester Fax', 'Provider Fax', 'Facility Provider Fax']
    for field_name in fax_fields:
        if field_name in fields:
            field_data = fields[field_name]
            original_value = field_data.get('value', '') if isinstance(field_data, dict) else str(field_data)
            
            if original_value:
                normalized, is_valid = normalize_fax_number(original_value)
                if normalized != original_value:
                    # Update field value
                    if isinstance(field_data, dict):
                        fields[field_name]['value'] = normalized
                    else:
                        fields[field_name] = {'value': normalized, 'confidence': 1.0, 'field_type': 'STRING'}
                    
                    auto_fix_results[field_name] = {
                        'original': original_value,
                        'fixed': normalized,
                        'status': 'success' if is_valid else 'failed'
                    }
    
    # Date fields
    date_fields = [
        'Anticipated Date of Service',
        'Submitted Date',
        'Beneficiary DOB',
        'Date Of Birth (YYYY-MM-DD)',
        'Date of Birth'
    ]
    for field_name in date_fields:
        if field_name in fields:
            field_data = fields[field_name]
            original_value = field_data.get('value', '') if isinstance(field_data, dict) else str(field_data)
            
            if original_value:
                normalized, is_valid = normalize_date(original_value)
                if normalized and normalized != original_value:
                    # Update field value
                    if isinstance(field_data, dict):
                        fields[field_name]['value'] = normalized
                    else:
                        fields[field_name] = {'value': normalized, 'confidence': 1.0, 'field_type': 'DATE'}
                    
                    auto_fix_results[field_name] = {
                        'original': original_value,
                        'fixed': normalized,
                        'status': 'success' if is_valid else 'failed'
                    }
    
    # Diagnosis code fields
    diagnosis_fields = ['Diagnosis Codes', 'Diagnosis Code']
    for field_name in diagnosis_fields:
        if field_name in fields:
            field_data = fields[field_name]
            original_value = field_data.get('value', '') if isinstance(field_data, dict) else str(field_data)
            
            if original_value:
                normalized, is_valid = normalize_diagnosis_code(original_value)
                if normalized != original_value:
                    # Update field value
                    if isinstance(field_data, dict):
                        fields[field_name]['value'] = normalized
                    else:
                        fields[field_name] = {'value': normalized, 'confidence': 1.0, 'field_type': 'STRING'}
                    
                    auto_fix_results[field_name] = {
                        'original': original_value,
                        'fixed': normalized,
                        'status': 'success' if is_valid else 'failed'
                    }
    
    # Address fields (normalize together)
    address_1 = fields.get('Rendering/Facility Address Line 1') or fields.get('Facility Provider Address 1')
    address_2 = fields.get('Rendering/Facility Address Line 2') or fields.get('Facility Provider Address 2')
    city = fields.get('Rendering/Facility City') or fields.get('Facility Provider City')
    state = fields.get('Rendering/Facility State') or fields.get('Facility Provider State')
    zip_code = fields.get('Rendering/Facility Zip') or fields.get('Facility Provider Zip')
    
    # Extract values from field data
    def get_field_value(field_name, fields_dict):
        if field_name in fields_dict:
            field_data = fields_dict[field_name]
            return field_data.get('value', '') if isinstance(field_data, dict) else str(field_data)
        return None
    
    address_1_val = get_field_value('Rendering/Facility Address Line 1', fields) or get_field_value('Facility Provider Address 1', fields)
    address_2_val = get_field_value('Rendering/Facility Address Line 2', fields) or get_field_value('Facility Provider Address 2', fields)
    city_val = get_field_value('Rendering/Facility City', fields) or get_field_value('Facility Provider City', fields)
    state_val = get_field_value('Rendering/Facility State', fields) or get_field_value('Facility Provider State', fields)
    zip_val = get_field_value('Rendering/Facility Zip', fields) or get_field_value('Facility Provider Zip', fields)
    
    if address_1_val or city_val or state_val:
        normalized_address = normalize_address(
            address_1=address_1_val,
            address_2=address_2_val,
            city=city_val,
            state=state_val,
            zip_code=zip_val
        )
        
        # Update fields if changed
        address_field_names = [
            ('Rendering/Facility Address Line 1', 'Facility Provider Address 1'),
            ('Rendering/Facility Address Line 2', 'Facility Provider Address 2'),
            ('Rendering/Facility City', 'Facility Provider City'),
            ('Rendering/Facility State', 'Facility Provider State'),
            ('Rendering/Facility Zip', 'Facility Provider Zip')
        ]
        
        for (field_name_1, field_name_2), key in zip(address_field_names, ['address_1', 'address_2', 'city', 'state', 'zip']):
            normalized_val = normalized_address[key][0]
            original_val = address_1_val if key == 'address_1' else (address_2_val if key == 'address_2' else (city_val if key == 'city' else (state_val if key == 'state' else zip_val)))
            
            if normalized_val != (original_val or ""):
                # Update the field
                field_name_to_use = field_name_1 if field_name_1 in fields else field_name_2
                if field_name_to_use:
                    field_data = fields.get(field_name_to_use, {})
                    if isinstance(field_data, dict):
                        fields[field_name_to_use]['value'] = normalized_val
                    else:
                        fields[field_name_to_use] = {'value': normalized_val, 'confidence': 1.0, 'field_type': 'STRING'}
                    
                    auto_fix_results[field_name_to_use] = {
                        'original': original_val or "",
                        'fixed': normalized_val,
                        'status': 'success'
                    }
    
    # Update the fields dict back
    updated_fields['fields'] = fields
    
    return updated_fields, auto_fix_results
