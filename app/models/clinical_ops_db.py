"""
SQLAlchemy models for ClinicalOps inbox (service_ops.send_serviceops)
Stores messages from ClinicalOps that need to be processed by ServiceOps
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Boolean
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class ClinicalOpsInboxDB(Base):
    """
    Maps to service_ops.send_serviceops table
    This is the ClinicalOps → ServiceOps inbox table
    Stores generated payloads from JSON Generator (with json_sent_to_integration flag)
    """
    __tablename__ = "send_serviceops"
    __table_args__ = {'schema': 'service_ops'}
    
    message_id = Column(BigInteger, primary_key=True)
    decision_tracking_id = Column(UUID(as_uuid=False), nullable=False)  # Links to packet
    workflow_instance_id = Column(BigInteger, nullable=True)
    payload = Column(JSONB, nullable=False)  # Contains generated payload from JSON Generator
    clinical_ops_decision_json = Column(JSONB, nullable=True)  # Phase 1: Clinical decision data stored by JSON Generator
    message_status_id = Column(Integer, nullable=True)  # FK to service_ops.message_status
    json_sent_to_integration = Column(Boolean, nullable=True)  # NULL = not generated payload, TRUE = sent, FALSE = failed
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    audit_user = Column(String(100), nullable=True)
    audit_timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)

