"""
Channel Type Enum
Defines the three channel types for multi-channel processing
"""
from enum import IntEnum


class ChannelType(IntEnum):
    """
    Channel type identifiers for service ops processing
    
    Values:
        GENZEON_PORTAL = 1: Genzeon Portal - Skip OCR, extract from payload.ocr
        GENZEON_FAX = 2: Genzeon Fax - Full OCR workflow
        ESMD = 3: ESMD - Full OCR workflow (default)
    """
    GENZEON_PORTAL = 1
    GENZEON_FAX = 2
    ESMD = 3






