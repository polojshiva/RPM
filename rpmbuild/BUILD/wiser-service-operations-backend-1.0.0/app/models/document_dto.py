"""
Document DTO Models
Matching frontend PacketDocument interface
"""
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Document type enum matching frontend"""
    PA_REQUEST_FORM = "PA Request Form"
    PHYSICIAN_ORDER = "Physician Order"
    FACE_TO_FACE_ENCOUNTER = "Face-to-Face Encounter"
    MEDICAL_RECORDS = "Medical Records"
    CERTIFICATE_OF_MEDICAL_NECESSITY = "Certificate of Medical Necessity"
    LAB_RESULTS = "Lab Results"
    PROGRESS_NOTES = "Progress Notes"
    PRESCRIPTION = "Prescription"
    PRIOR_AUTHORIZATION_LETTER = "Prior Authorization Letter"
    APPEAL_LETTER = "Appeal Letter"
    SUPPORTING_DOCUMENTATION = "Supporting Documentation"
    OTHER = "Other"


class DocumentStatus(str, Enum):
    """Document status enum matching frontend"""
    RECEIVED = "Received"
    PROCESSING = "Processing"
    EXTRACTED = "Extracted"
    FAILED = "Failed"


class PacketDocumentDTO(BaseModel):
    """Packet Document DTO matching frontend PacketDocument interface"""
    id: str = Field(..., description="Unique document identifier")
    packetId: str = Field(..., description="Associated packet ID")
    fileName: str = Field(..., description="Document file name")
    documentType: DocumentType = Field(..., description="Type of document")
    pageCount: int = Field(..., description="Number of pages in document")
    fileSize: str = Field(..., description="File size as string (e.g., '245 KB')")
    uploadedAt: str = Field(..., description="ISO 8601 datetime when document was uploaded")
    status: DocumentStatus = Field(..., description="Current processing status")
    ocrConfidence: Optional[int] = Field(None, description="OCR confidence percentage (0-100)")
    extractedData: Optional[bool] = Field(None, description="Whether data has been extracted")
    extractedFields: Optional[Dict[str, Any]] = Field(None, description="OCR extracted fields JSON from extracted_fields column")
    thumbnailUrl: Optional[str] = Field(None, description="URL to document thumbnail")
    downloadUrl: Optional[str] = Field(None, description="URL to download document")
    
    # Page tracking and OCR metadata fields (added in migration 002)
    processingPath: Optional[str] = Field(None, description="Blob storage folder path where split page files are stored")
    pagesMetadata: Optional[Dict[str, Any]] = Field(None, description="Page-level metadata with blob paths, filenames, checksums, etc.")
    coversheetPageNumber: Optional[int] = Field(None, description="Page number (1-indexed) containing the coversheet")
    partType: Optional[str] = Field(None, description="Document part type: PART_A, PART_B, or UNKNOWN")
    ocrMetadata: Optional[Dict[str, Any]] = Field(None, description="OCR processing metadata: confidence scores, field counts, processing timestamps")
    splitStatus: Optional[str] = Field(None, description="Status of document splitting: NOT_STARTED, DONE, or FAILED")
    ocrStatus: Optional[str] = Field(None, description="Status of OCR processing: NOT_STARTED, DONE, or FAILED")
    
    # Manual review and audit fields (added in migration 006)
    updatedExtractedFields: Optional[Dict[str, Any]] = Field(None, description="Full snapshot of all fields after manual review/update (with metadata)")
    extractedFieldsUpdateHistory: Optional[list] = Field(None, description="Append-only audit trail of all manual updates to extracted fields")
    
    # OCR suggestion field (added in migration 007)
    suggestedExtractedFields: Optional[Dict[str, Any]] = Field(None, description="Latest OCR coversheet result from 'Mark as Coversheet' rerun. Used when manual edits exist to preserve working view while showing OCR suggestions.")
    
    # Approved unit of service fields (added in migration 027)
    approvedUnitOfService1: Optional[str] = Field(None, description="Approved unit of service 1 - entered manually from UI")
    approvedUnitOfService2: Optional[str] = Field(None, description="Approved unit of service 2 - entered manually from UI")
    approvedUnitOfService3: Optional[str] = Field(None, description="Approved unit of service 3 - entered manually from UI")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "DOC-001",
                "packetId": "SVC-2025-001234",
                "fileName": "PA_Request_Form.pdf",
                "documentType": "PA Request Form",
                "pageCount": 2,
                "fileSize": "245 KB",
                "uploadedAt": "2025-12-02T14:30:00Z",
                "status": "Extracted",
                "ocrConfidence": 98,
                "extractedData": True
            }
        }


class DocumentListResponse(BaseModel):
    """Response model for document list endpoint"""
    success: bool
    data: list[PacketDocumentDTO]
    message: Optional[str] = None

