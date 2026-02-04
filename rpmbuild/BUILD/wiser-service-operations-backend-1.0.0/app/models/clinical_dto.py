"""
Clinical DTO Models
Pydantic models matching the frontend clinical case interfaces
"""
from enum import Enum
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


# ============================================
# Enums
# ============================================

class CaseStatus(str, Enum):
    """Clinical case status"""
    PENDING_REVIEW = "Pending Review"
    IN_REVIEW = "In Review"
    IN_PROGRESS = "In Progress"
    MD_REVIEW = "MD Review"
    NEED_MORE_INFO = "Need More Info"
    COMPLETED = "Completed"
    LETTER_SENT = "Letter Sent"


class ReviewType(str, Enum):
    """Clinical review type"""
    DME = "DME"
    HHA = "HHA"
    HOSPICE = "Hospice"


class Priority(str, Enum):
    """Priority level"""
    STANDARD = "Standard"
    MEDIUM = "Medium"
    HIGH = "High"
    EXPEDITED = "Expedited"


class NurseRecommendation(str, Enum):
    """Nurse recommendation"""
    APPROVE = "Approve"
    DENY = "Deny"
    PARTIAL = "Partial"
    NEED_MORE_INFO = "Need More Info"


# ============================================
# Decision Support Answer
# ============================================

class DecisionSupportAnswerDTO(BaseModel):
    """Decision support question/answer"""
    question: str
    answer: str
    critical: Optional[bool] = False


# ============================================
# Clinical Case Item (Dashboard)
# ============================================

class ClinicalCaseItemDTO(BaseModel):
    """Clinical case item for dashboard listing"""
    uniqueId: str
    caseId: str
    patientName: str
    memberId: str
    docId: str
    dateAdded: str
    dateCompleted: Optional[str] = None
    status: CaseStatus
    statusColor: str  # Frontend computed color (e.g., 'orange', 'green', 'blue')
    priority: Priority
    reviewType: ReviewType
    assignedTo: str
    serviceType: str
    hcpcs: str
    nurseRecommendation: Optional[str] = None  # 'Approve', 'Deny', 'Partial', or null
    decision: Optional[str] = None
    daysInReview: int
    expedited: Optional[bool] = False
    letterType: Optional[str] = None
    packetId: str


# ============================================
# Clinical Case Detail (MD Review / Letter Generation)
# ============================================

class CaseDataDTO(BaseModel):
    """Detailed clinical case data for MD review and letter generation"""
    uniqueId: str
    caseId: str
    patientName: str
    memberId: str
    dateOfBirth: Optional[str] = None
    age: Optional[int] = None
    patientAddress: Optional[str] = None  # For letter generation
    serviceType: str
    hcpcs: str
    diagnosisCodes: List[str]
    providerName: str
    providerNPI: str
    providerAddress: Optional[str] = None  # For letter generation
    providerPhone: Optional[str] = None  # For letter generation
    providerFax: Optional[str] = None  # For letter generation
    dateAdded: str
    dateOfService: Optional[str] = None  # For letter generation
    daysInReview: int
    priority: Priority
    expedited: bool = False
    nurseReviewer: str
    nurseReviewDate: str
    nurseRecommendation: Literal['Approve', 'Deny', 'Partial']
    nurseNotes: str
    decisionSupportAnswers: List[DecisionSupportAnswerDTO]
    documentsReviewed: List[str]
    packetId: str
    intakeChannel: Optional[str] = None  # For letter generation
    mdReviewer: Optional[str] = None  # For letter generation
    reviewDate: Optional[str] = None  # For letter generation
    decision: Optional[str] = None  # For letter generation


# ============================================
# MD Review Submission
# ============================================

class MDReviewSubmissionDTO(BaseModel):
    """MD review decision submission"""
    decision: Literal['agree', 'disagree']
    feedback: Optional[str] = None


# ============================================
# Response Models
# ============================================

class ClinicalCaseListResponse(BaseModel):
    """Response for list of clinical cases"""
    success: bool = True
    data: List[ClinicalCaseItemDTO]
    total: int
    message: Optional[str] = None


class ClinicalCaseResponse(BaseModel):
    """Response for single clinical case detail"""
    success: bool = True
    data: CaseDataDTO
    message: Optional[str] = None


class MDReviewResponse(BaseModel):
    """Response for MD review submission"""
    success: bool = True
    data: CaseDataDTO  # Updated case data
    message: Optional[str] = None

