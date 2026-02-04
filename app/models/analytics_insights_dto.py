"""
Analytics Insights DTO Models
Pydantic models matching the frontend AnalyticsInsights interface
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ============================================
# Time Range Enum
# ============================================

TimeRange = Literal["24h", "7d", "30d"]


# ============================================
# Core Metrics
# ============================================

class MetricsDTO(BaseModel):
    """Core metrics for analytics insights"""
    totalProcessed: int
    avgProcessingTime: int  # in minutes
    manualReviewRate: float  # percentage
    dismissalRate: float  # percentage
    successRate: float  # percentage
    slaCompliance: float  # percentage


# ============================================
# Phase Performance
# ============================================

class PhasePerformanceDTO(BaseModel):
    """Performance metrics for a single phase"""
    phase: str
    current: float  # in days
    target: float  # in days
    trend: List[float]  # trend data points
    color: Literal["amber", "purple", "orange", "blue"]


# ============================================
# Channel Performance
# ============================================

class ChannelPerformanceDTO(BaseModel):
    """Performance metrics for a delivery channel"""
    channel: str
    avgTime: int  # in minutes
    volume: int  # number of cases
    successRate: float  # percentage


# ============================================
# SLA Data
# ============================================

class SLAPhaseDTO(BaseModel):
    """SLA compliance for a single phase"""
    phase: str
    compliance: float  # percentage
    target: float  # percentage


class SLADataDTO(BaseModel):
    """SLA compliance tracking data"""
    overall: float  # percentage
    byPhase: List[SLAPhaseDTO]
    trend: List[float]  # trend data points


# ============================================
# Aging Buckets
# ============================================

class AgingBucketDTO(BaseModel):
    """Aging distribution bucket"""
    bucket: str  # e.g., "0-4h", "4-8h", "8-24h", "1-2d", "2-4d", "4+d"
    count: int
    percentage: float


# ============================================
# Dismissal Reasons
# ============================================

class DismissalReasonDTO(BaseModel):
    """Dismissal reason breakdown"""
    reason: str
    count: int
    percentage: float


# ============================================
# Provider Performance
# ============================================

class ProviderPerformanceDTO(BaseModel):
    """Provider performance metrics"""
    provider: str
    totalCases: int
    dismissalRate: float  # percentage
    avgTime: float  # in days


# ============================================
# Service Code Analysis
# ============================================

class ServiceCodeDTO(BaseModel):
    """Service code analysis metrics"""
    code: str  # HCPCS code
    description: str
    count: int
    avgTime: float  # in days
    dismissalRate: float  # percentage


# ============================================
# Main Insights DTO
# ============================================

class AnalyticsInsightsDTO(BaseModel):
    """Complete analytics insights data"""
    metrics: MetricsDTO
    volumeTrend: List[int]  # volume trend data points
    phasePerformance: List[PhasePerformanceDTO]
    channels: List[ChannelPerformanceDTO]
    slaData: SLADataDTO
    agingBuckets: List[AgingBucketDTO]
    dismissalReasons: List[DismissalReasonDTO]
    providers: List[ProviderPerformanceDTO]
    serviceCodes: List[ServiceCodeDTO]


# ============================================
# Response Model
# ============================================

class AnalyticsInsightsResponse(BaseModel):
    """Response for analytics insights endpoint"""
    success: bool = True
    data: AnalyticsInsightsDTO
    message: Optional[str] = None

