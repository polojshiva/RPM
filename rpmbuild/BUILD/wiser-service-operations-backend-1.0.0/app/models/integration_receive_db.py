"""
SQLAlchemy models for integration.integration_receive_serviceops table
ServiceOps → Integration outbox (ESMD decision payloads)
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class IntegrationReceiveServiceOpsDB(Base):
    """
    Maps to integration.integration_receive_serviceops table
    ServiceOps → Integration outbox
    Stores ESMD decision payloads to be picked up by Integration/ESMD
    """
    __tablename__ = "integration_receive_serviceops"
    __table_args__ = {'schema': 'integration'}
    
    response_id = Column(BigInteger, primary_key=True)
    decision_tracking_id = Column(UUID(as_uuid=False), nullable=False)  # Links to packet
    workflow_id = Column(BigInteger, nullable=True)
    payload = Column(Text, nullable=False)  # JSON payload as TEXT (not JSONB)
    status = Column(String(50), nullable=False, default='PENDING_UPLOAD')
    decision_type = Column(String(20), nullable=True)  # DIRECT_PA / STANDARD_PA
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    audit_user = Column(String(100), nullable=True, default='system')
    audit_timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    
    # UTN workflow fields (added in Stage 1 migration 013)
    correlation_id = Column(UUID(as_uuid=False), nullable=True)
    attempt_count = Column(Integer, nullable=True, default=1)
    resend_of_response_id = Column(BigInteger, nullable=True)
    payload_hash = Column(Text, nullable=True)
    payload_version = Column(Integer, nullable=True, default=1)

