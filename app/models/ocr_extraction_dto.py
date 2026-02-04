"""
OCR Extraction DTOs
Data transfer objects for OCR extraction results and field-level confidence scores
"""
from typing import Optional, Dict, List
from pydantic import BaseModel, Field


class FieldIssue(BaseModel):
    """Field-level OCR issue with confidence score"""
    hasIssue: bool = Field(..., description="Whether this field has an issue")
    reason: str = Field(..., description="Reason for the issue (empty if no issue)")
    confidence: int = Field(..., ge=0, le=100, description="OCR confidence percentage (0-100)")


class ExtractedFieldData(BaseModel):
    """Extracted field value from OCR"""
    value: str = Field(..., description="Extracted field value")
    confidence: int = Field(..., ge=0, le=100, description="OCR confidence for this field")
    hasIssue: bool = Field(..., description="Whether this field has an issue")
    issueReason: str = Field(default="", description="Reason for the issue")


class CoverPageFormData(BaseModel):
    """Extracted form data from OCR matching frontend CoverPageFormData interface"""
    # Medicare Part Selection
    medicarePartType: str = Field(default="B", description="Medicare Part A or B")
    
    # A. Submission Details
    submissionType: str = Field(default="initial", description="Initial or resubmission")
    previousUTN: str = Field(default="", description="Previous UTN for resubmissions")
    submittedDate: str = Field(..., description="Date submitted (ISO 8601)")
    anticipatedDateOfService: str = Field(..., description="Anticipated service date (ISO 8601)")
    
    # Part B specific
    locationOfService: str = Field(default="", description="Location of service for Part B")
    
    # Part A specific
    placeOfService: str = Field(default="", description="Place of service for Part A")
    typeOfBill: str = Field(default="", description="Type of bill for Part A")
    
    # B. Beneficiary Information
    beneficiaryLastName: str = Field(..., description="Beneficiary last name")
    beneficiaryFirstName: str = Field(..., description="Beneficiary first name")
    medicareId: str = Field(..., description="Medicare Beneficiary Identifier (MBI)")
    beneficiaryDob: str = Field(..., description="Beneficiary date of birth (ISO 8601)")
    
    # Procedure Codes (arrays - up to 4)
    procedureCodes: List[str] = Field(default_factory=lambda: ["", "", "", ""], description="Procedure codes array")
    modifiers: List[str] = Field(default_factory=lambda: ["", "", "", ""], description="Modifiers array")
    units: List[str] = Field(default_factory=lambda: ["", "", "", ""], description="Units array")
    diagnosisCodes: List[str] = Field(default_factory=lambda: ["", "", "", ""], description="Diagnosis codes array")
    
    # C. Facility/Rendering Provider
    facilityName: str = Field(..., description="Facility name")
    facilityNpi: str = Field(..., description="Facility NPI")
    facilityCcn: str = Field(default="", description="Facility CCN")
    facilityAddress1: str = Field(..., description="Facility address line 1")
    facilityAddress2: str = Field(default="", description="Facility address line 2")
    facilityCity: str = Field(..., description="Facility city")
    facilityState: str = Field(..., description="Facility state")
    facilityZip: str = Field(..., description="Facility ZIP code")
    
    # D. Physician Info
    physicianName: str = Field(..., description="Physician name")
    physicianNpi: str = Field(..., description="Physician NPI")
    physicianPtan: str = Field(default="", description="Physician PTAN")
    physicianAddress: str = Field(..., description="Physician address")
    physicianCity: str = Field(..., description="Physician city")
    physicianState: str = Field(..., description="Physician state")
    physicianZip: str = Field(..., description="Physician ZIP code")
    
    # E. Requester Information
    requesterName: str = Field(..., description="Requester name")
    requesterPhone: str = Field(..., description="Requester phone")
    requesterEmail: str = Field(..., description="Requester email")
    requesterFax: str = Field(default="", description="Requester fax")
    
    # Diagnosis & Justification
    diagnosisJustification: str = Field(default="", description="Diagnosis justification text")
    
    # Legacy fields for fax delivery
    providerFax: str = Field(default="", description="Provider fax number")


class FieldIssues(BaseModel):
    """Field-level issues with OCR confidence scores"""
    # Medicare Part
    medicarePartType: FieldIssue
    # Submission Details
    submissionType: FieldIssue
    previousUTN: FieldIssue
    submittedDate: FieldIssue
    anticipatedDateOfService: FieldIssue
    locationOfService: FieldIssue
    placeOfService: FieldIssue
    typeOfBill: FieldIssue
    # Beneficiary
    beneficiaryLastName: FieldIssue
    beneficiaryFirstName: FieldIssue
    medicareId: FieldIssue
    beneficiaryDob: FieldIssue
    # Procedure (first row)
    procedureCode: FieldIssue
    modifier: FieldIssue
    units: FieldIssue
    diagnosisCode: FieldIssue
    # Facility
    facilityName: FieldIssue
    facilityNpi: FieldIssue
    facilityCcn: FieldIssue
    facilityAddress1: FieldIssue
    facilityAddress2: FieldIssue
    facilityCity: FieldIssue
    facilityState: FieldIssue
    facilityZip: FieldIssue
    # Physician
    physicianName: FieldIssue
    physicianNpi: FieldIssue
    physicianPtan: FieldIssue
    physicianAddress: FieldIssue
    physicianCity: FieldIssue
    physicianState: FieldIssue
    physicianZip: FieldIssue
    # Requester
    requesterName: FieldIssue
    requesterPhone: FieldIssue
    requesterEmail: FieldIssue
    requesterFax: FieldIssue
    # Other
    diagnosisJustification: FieldIssue
    providerFax: FieldIssue


class DocumentClassification(BaseModel):
    """Document classification prediction from AI"""
    predictedType: str = Field(..., description="Predicted document type")
    confidence: int = Field(..., ge=0, le=100, description="Classification confidence percentage")
    description: str = Field(default="", description="Description of the prediction")


class OCRExtractionResponse(BaseModel):
    """Response model for OCR extraction endpoint"""
    success: bool = Field(..., description="Whether the request was successful")
    data: Optional[CoverPageFormData] = Field(None, description="Extracted form data")
    fieldIssues: Optional[FieldIssues] = Field(None, description="Field-level OCR issues and confidence")
    message: Optional[str] = Field(None, description="Response message")


class DocumentClassificationResponse(BaseModel):
    """Response model for document classification endpoint"""
    success: bool = Field(..., description="Whether the request was successful")
    data: Optional[DocumentClassification] = Field(None, description="Classification prediction")
    message: Optional[str] = Field(None, description="Response message")

