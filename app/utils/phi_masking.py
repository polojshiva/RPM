"""
PHI Masking Utilities
Automatically redacts Protected Health Information in logs and error messages
"""
import re
from typing import Any, Dict


# Patterns for PHI detection
PHI_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "ssn_no_dash": re.compile(r"\b\d{9}\b"),
    "dob": re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    "phone": re.compile(r"\b\(\d{3}\)\s*\d{3}-\d{4}\b"),
    "phone_simple": re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "mrn": re.compile(r"\bMRN\d+\b", re.IGNORECASE),
}

# Field names that likely contain PHI
PHI_FIELD_NAMES = {
    "patient_name",
    "patientname",
    "patient_dob",
    "patientdob",
    "patient_mrn",
    "patientmrn",
    "patient_phone",
    "patientphone",
    "patient_email",
    "patientemail",
    "ssn",
    "social_security",
    "date_of_birth",
    "dob",
    "medical_record",
}


def mask_phi(text: str) -> str:
    """
    Mask PHI patterns in a string.

    Args:
        text: String that may contain PHI

    Returns:
        String with PHI patterns replaced with masks
    """
    if not text:
        return text

    result = text

    # Apply pattern-based masking
    result = PHI_PATTERNS["ssn"].sub("***-**-****", result)
    result = PHI_PATTERNS["dob"].sub("****-**-**", result)
    result = PHI_PATTERNS["phone"].sub("(***) ***-****", result)
    result = PHI_PATTERNS["phone_simple"].sub("***-***-****", result)
    result = PHI_PATTERNS["email"].sub("***@***.***", result)
    result = PHI_PATTERNS["mrn"].sub("MRN******", result)

    return result


def mask_phi_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mask PHI fields in a dictionary.

    Args:
        data: Dictionary that may contain PHI fields

    Returns:
        Dictionary with PHI fields masked
    """
    if not data:
        return data

    masked = {}

    for key, value in data.items():
        # Check if field name suggests PHI
        if key.lower() in PHI_FIELD_NAMES:
            masked[key] = "***MASKED***"
        elif isinstance(value, str):
            masked[key] = mask_phi(value)
        elif isinstance(value, dict):
            masked[key] = mask_phi_dict(value)
        elif isinstance(value, list):
            masked[key] = [
                mask_phi_dict(item) if isinstance(item, dict) else mask_phi(str(item)) if isinstance(item, str) else item
                for item in value
            ]
        else:
            masked[key] = value

    return masked


def mask_error_message(message: str) -> str:
    """
    Mask any PHI in error messages before returning to client.

    Args:
        message: Error message that may contain PHI

    Returns:
        Sanitized error message
    """
    return mask_phi(message)
