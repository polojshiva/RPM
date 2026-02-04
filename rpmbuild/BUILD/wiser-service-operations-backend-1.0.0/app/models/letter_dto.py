"""
Letter DTO Models
Matching frontend DismissalLetter interface
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DismissalReason(str, Enum):
    """Dismissal reason enum matching frontend"""
    MISSING_DOCUMENTS = "missing_documents"
    MEMBER_ELIGIBILITY_FAILED = "member_eligibility_failed"
    PROVIDER_NPI_VALIDATION_FAILED = "provider_npi_validation_failed"


class DismissalLetterStatus(str, Enum):
    """Dismissal letter status enum matching frontend"""
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SENT = "sent"


class ProviderDeliveryMethod(str, Enum):
    """Provider delivery method enum"""
    FAX = "fax"
    PORTAL = "portal"
    MAIL = "mail"


class ProviderAddressDTO(BaseModel):
    """Provider address DTO"""
    street: str
    city: str
    state: str
    zip: str


class DismissalLetterDTO(BaseModel):
    """Dismissal Letter DTO matching frontend DismissalLetter interface"""
    id: str = Field(..., description="Unique letter identifier")
    packetId: str = Field(..., description="Associated packet ID")
    templateId: str = Field(..., description="Template identifier used")
    templateName: str = Field(..., description="Human-readable template name")
    dismissalReason: DismissalReason = Field(..., description="Reason for dismissal")
    dismissalReasonDisplay: str = Field(..., description="Human-readable dismissal reason")
    generatedAt: str = Field(..., description="ISO 8601 datetime when letter was generated")
    generatedBy: str = Field(..., description="System or user who generated the letter")
    providerName: str = Field(..., description="Provider name")
    providerNpi: str = Field(..., description="Provider NPI")
    providerFax: Optional[str] = Field(None, description="Provider fax number")
    providerAddress: Optional[ProviderAddressDTO] = Field(None, description="Provider mailing address")
    beneficiaryName: str = Field(..., description="Beneficiary name")
    beneficiaryMbi: str = Field(..., description="Beneficiary MBI")
    serviceType: str = Field(..., description="Service type")
    letterContent: str = Field(..., description="Full letter content text")
    missingDocuments: Optional[list[str]] = Field(None, description="List of missing documents (if applicable)")
    validationErrors: Optional[list[str]] = Field(None, description="List of validation errors (if applicable)")
    status: DismissalLetterStatus = Field(..., description="Current letter status")
    sentAt: Optional[str] = Field(None, description="ISO 8601 datetime when letter was sent")
    sentBy: Optional[str] = Field(None, description="User who sent the letter")
    deliveryMethod: Optional[ProviderDeliveryMethod] = Field(None, description="Delivery method used")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "DL-001",
                "packetId": "SVC-2025-001250",
                "templateId": "DISM-TPL-001",
                "templateName": "Missing Documentation Notice",
                "dismissalReason": "missing_documents",
                "dismissalReasonDisplay": "Missing Required Documents",
                "generatedAt": "2025-12-17T14:00:00Z",
                "generatedBy": "Letter Generation System v2.1",
                "providerName": "Downtown Medical Center",
                "providerNpi": "1112223334",
                "providerFax": "(555) 111-2222",
                "providerAddress": {
                    "street": "100 Medical Plaza Dr",
                    "city": "Houston",
                    "state": "TX",
                    "zip": "77001"
                },
                "beneficiaryName": "Michael Chen",
                "beneficiaryMbi": "1WX2YZ3AB45",
                "serviceType": "DME - Power Wheelchair",
                "letterContent": "Dear Downtown Medical Center...",
                "missingDocuments": [
                    "Physician's Order/Prescription",
                    "Face-to-Face Encounter Documentation"
                ],
                "status": "pending_review"
            }
        }


class LetterListResponse(BaseModel):
    """Response model for letter list endpoint"""
    success: bool
    data: list[DismissalLetterDTO]
    message: Optional[str] = None


class LetterResponse(BaseModel):
    """Response model for single letter endpoint"""
    success: bool
    data: DismissalLetterDTO
    message: Optional[str] = None


class LetterUpdate(BaseModel):
    """Model for updating a dismissal letter"""
    status: Optional[DismissalLetterStatus] = Field(None, description="New letter status")
    letterContent: Optional[str] = Field(None, description="Updated letter content")
    deliveryMethod: Optional[ProviderDeliveryMethod] = Field(None, description="Delivery method")
    providerFax: Optional[str] = Field(None, description="Updated provider fax number")
    sentBy: Optional[str] = Field(None, description="User who sent the letter")
    notes: Optional[str] = Field(None, max_length=2000, description="Additional notes or comments")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "approved",
                "deliveryMethod": "fax",
                "providerFax": "(555) 123-4567",
                "sentBy": "john.doe@example.com"
            }
        }

