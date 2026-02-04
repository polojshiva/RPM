"""
SQLAlchemy models for service_ops.send_clinicalops table
ServiceOps → ClinicalOps outbox
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Boolean
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class SendClinicalOpsDB(Base):
    """
    Maps to service_ops.send_clinicalops table
    ServiceOps → ClinicalOps outbox
    Stores UTN_SUCCESS notifications and other messages to ClinicalOps
    """
    __tablename__ = "send_clinicalops"
    __table_args__ = {'schema': 'service_ops'}
    
    message_id = Column(BigInteger, primary_key=True)
    decision_tracking_id = Column(UUID(as_uuid=False), nullable=False)  # Links to packet
    workflow_instance_id = Column(BigInteger, nullable=True)
    payload = Column(JSONB, nullable=False)  # Contains message_type, UTN data, etc.
    message_status_id = Column(Integer, nullable=True)  # FK to service_ops.message_status
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    audit_user = Column(String(100), nullable=True)
    audit_timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    is_picked = Column(Boolean, nullable=True)  # NULL = not reviewed, TRUE = picked successfully, FALSE = picked with errors
    error_reason = Column(String(500), nullable=True)  # Reason for rejection (only when is_picked = FALSE)
    is_looped_back_to_validation = Column(Boolean, default=False)  # Track if rejected record has been looped back to validation
    retry_count = Column(Integer, default=0)  # Number of times this decision_tracking_id has been sent to ClinicalOps

