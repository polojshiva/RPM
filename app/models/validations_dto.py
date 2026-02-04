"""
Validations DTO Models
Pydantic models for HETS and PECOS validation requests/responses
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class ProviderInfo(BaseModel):
    """Provider information for HETS validation"""
    npi: str = Field(..., description="Provider NPI (10 digits)")
    
    @field_validator('npi')
    @classmethod
    def validate_npi(cls, v: str) -> str:
        """Validate NPI is 10 digits"""
        npi_clean = ''.join(filter(str.isdigit, str(v)))
        if len(npi_clean) != 10:
            raise ValueError("NPI must be exactly 10 digits")
        return npi_clean


class PatientInfo(BaseModel):
    """Patient information for HETS validation"""
    mbi: str = Field(..., description="Medicare Beneficiary Identifier")
    dob: str = Field(..., description="Date of birth (ISO format: YYYY-MM-DD)")
    lastName: str = Field(..., description="Patient last name")
    firstName: str = Field(..., description="Patient first name")
    
    @field_validator('mbi')
    @classmethod
    def validate_mbi(cls, v: str) -> str:
        """Validate MBI is non-empty"""
        if not v or not v.strip():
            raise ValueError("MBI cannot be empty")
        return v.strip().upper()
    
    @field_validator('dob')
    @classmethod
    def validate_dob(cls, v: str) -> str:
        """Validate and normalize DOB to ISO format (YYYY-MM-DD)"""
        if not v or not v.strip():
            raise ValueError("DOB cannot be empty")
        
        v_clean = v.strip()
        
        # Try to parse various date formats and convert to ISO
        from datetime import datetime
        
        # Common date formats to try
        date_formats = [
            '%Y-%m-%d',      # ISO format: 1999-12-11
            '%m/%d/%Y',      # US format: 12/11/1999
            '%d/%m/%Y',      # European format: 11/12/1999
            '%m-%d-%Y',      # US with dashes: 12-11-1999
            '%d-%m-%Y',      # European with dashes: 11-12-1999
            '%Y/%m/%d',      # Alternative ISO: 1999/12/11
        ]
        
        parsed_date = None
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(v_clean, fmt)
                break
            except ValueError:
                continue
        
        if parsed_date is None:
            raise ValueError(f"DOB must be in a valid date format (e.g., YYYY-MM-DD, MM/DD/YYYY). Received: {v_clean}")
        
        # Validate reasonable date range
        if not (1900 <= parsed_date.year <= 2100):
            raise ValueError(f"DOB year must be between 1900 and 2100. Received: {parsed_date.year}")
        
        # Return in ISO format (YYYY-MM-DD)
        return parsed_date.strftime('%Y-%m-%d')
    
    @field_validator('lastName', 'firstName')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate name is non-empty"""
        if not v or not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()


class HetsValidationRequest(BaseModel):
    """Request model for HETS validation"""
    payer: str = Field(..., description="Payer name (e.g., 'medicare')")
    provider: ProviderInfo = Field(..., description="Provider information")
    patient: PatientInfo = Field(..., description="Patient information")
    criteria: Optional[str] = Field(None, description="Validation criteria (e.g., 'Test' or 'Production') - defaults to 'Production' if not provided")
    dateOfService: str = Field(..., description="Date of service (string format as provided)")
    
    @field_validator('payer')
    @classmethod
    def validate_payer(cls, v: str) -> str:
        """Validate payer field is non-empty"""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()
    
    @field_validator('criteria')
    @classmethod
    def validate_criteria(cls, v: Optional[str]) -> Optional[str]:
        """Validate criteria field if provided"""
        if v is not None and (not v or not v.strip()):
            raise ValueError("Criteria cannot be empty if provided")
        return v.strip() if v else None
    
    @field_validator('dateOfService')
    @classmethod
    def validate_date_of_service(cls, v: str) -> str:
        """
        Validate and normalize dateOfService to YYYY-MM-DD format (as required by HETS API).
        Accepts various date formats from OCR (MM/DD/YYYY, YYYY-MM-DD, etc.) and normalizes to YYYY-MM-DD.
        Preserves the actual date value - only formats it for API compatibility.
        """
        if not v or not v.strip():
            raise ValueError("dateOfService cannot be empty")
        
        v_clean = v.strip()
        
        # Try to parse various date formats and convert to YYYY-MM-DD
        from datetime import datetime
        
        # Common date formats from OCR
        date_formats = [
            '%Y-%m-%d',      # ISO format: 2026-02-15
            '%m/%d/%Y',      # US format: 02/15/2026 (most common from OCR)
            '%d/%m/%Y',      # European format: 15/02/2026
            '%m-%d-%Y',      # US with dashes: 02-15-2026
            '%d-%m-%Y',      # European with dashes: 15-02-2026
            '%Y/%m/%d',      # Alternative ISO: 2026/02/15
            '%Y%m%d',        # Compact format: 20260215
        ]
        
        parsed_date = None
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(v_clean, fmt)
                break
            except ValueError:
                continue
        
        if parsed_date is None:
            # If we can't parse it, return as-is (let API handle validation)
            # But log a warning
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not parse dateOfService format: {v_clean}, sending as-is")
            return v_clean
        
        # Validate reasonable date range
        if not (1900 <= parsed_date.year <= 2100):
            raise ValueError(f"dateOfService year must be between 1900 and 2100. Received: {parsed_date.year}")
        
        # Return in YYYY-MM-DD format (required by HETS API)
        return parsed_date.strftime('%Y-%m-%d')


class HetsValidationResponse(BaseModel):
    """Response model for HETS validation (passthrough - accepts any JSON)"""
    # We don't know the exact structure, so we accept any dict
    # The UI will render the raw JSON
    model_config = {"extra": "allow"}
    
    # Common fields that might exist (optional)
    success: Optional[bool] = None
    request_id: Optional[str] = None
    eligible: Optional[bool] = None
    error: Optional[str] = None
    message: Optional[str] = None


class PecosValidationResponse(BaseModel):
    """Response model for PECOS validation (passthrough - accepts any JSON)"""
    # We don't know the exact structure, so we accept any dict
    # The UI will render the raw JSON
    model_config = {"extra": "allow"}
    
    # Common fields that might exist (optional)
    success: Optional[bool] = None
    enrolled: Optional[bool] = None
    provider_name: Optional[str] = None
    name: Optional[str] = None
    npi: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None

