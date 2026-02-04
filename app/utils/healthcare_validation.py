"""
Healthcare Validation Utilities
Validates NPI, ICD-10, and CPT codes according to CMS standards
"""
import re
from typing import Tuple


def validate_npi(npi: str) -> Tuple[bool, str]:
    """
    Validate NPI (National Provider Identifier) using Luhn algorithm.
    NPI is a 10-digit number where the check digit is calculated using
    the CMS Luhn algorithm with prefix 80840.

    Returns: (is_valid, error_message)
    """
    if not npi:
        return False, "NPI is required"

    # Must be exactly 10 digits
    if not re.match(r"^\d{10}$", npi):
        return False, "NPI must be exactly 10 digits"

    # Apply Luhn algorithm with 80840 prefix
    prefixed = "80840" + npi
    digits = [int(d) for d in prefixed]

    # Luhn checksum calculation
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            doubled = digit * 2
            checksum += doubled if doubled < 10 else doubled - 9
        else:
            checksum += digit

    if checksum % 10 != 0:
        return False, "Invalid NPI checksum"

    return True, ""


def validate_icd10(code: str) -> Tuple[bool, str]:
    """
    Validate ICD-10 diagnosis code format.
    Format: Letter + 2 digits + optional decimal + up to 4 alphanumeric

    Returns: (is_valid, error_message)
    """
    if not code:
        return False, "ICD-10 code is required"

    # ICD-10 pattern: A-T or V-Z, followed by 2 digits, optional decimal with 1-4 alphanumeric
    pattern = r"^[A-TV-Z][0-9]{2}(\.[A-Z0-9]{1,4})?$"

    if not re.match(pattern, code.upper()):
        return False, "Invalid ICD-10 code format"

    return True, ""


def validate_cpt(code: str) -> Tuple[bool, str]:
    """
    Validate CPT (Current Procedural Terminology) code format.
    Format: 5 digits OR 4 digits + letter

    Returns: (is_valid, error_message)
    """
    if not code:
        return False, "CPT code is required"

    # CPT pattern: 5 digits or 4 digits + letter
    pattern = r"^(\d{5}|\d{4}[A-Z])$"

    if not re.match(pattern, code.upper()):
        return False, "Invalid CPT code format"

    return True, ""


def generate_valid_npi() -> str:
    """
    Generate a valid NPI for testing purposes.
    Uses the Luhn algorithm with 80840 prefix.
    """
    import random

    # Generate 9 random digits
    base_digits = [random.randint(0, 9) for _ in range(9)]

    # Prefix with 80840 for Luhn calculation
    prefixed = "80840" + "".join(map(str, base_digits))
    digits = [int(d) for d in prefixed]

    # Calculate Luhn checksum for first 14 digits
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = digit * 2
            checksum += doubled if doubled < 10 else doubled - 9
        else:
            checksum += digit

    # Calculate check digit
    check_digit = (10 - (checksum % 10)) % 10

    # Return 10-digit NPI (9 base + check digit)
    return "".join(map(str, base_digits)) + str(check_digit)
