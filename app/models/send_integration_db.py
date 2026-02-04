"""
SQLAlchemy models for service_ops.send_integration table
ServiceOps → Integration outbox
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class SendIntegrationDB(Base):
    """
    Maps to service_ops.send_integration table
    ServiceOps → Integration outbox
    Stores ESMD payloads and letter packages for Integration service to consume
    """
    __tablename__ = "send_integration"
    __table_args__ = {'schema': 'service_ops'}
    
    message_id = Column(BigInteger, primary_key=True)
    decision_tracking_id = Column(UUID(as_uuid=False), nullable=False)  # Links to packet
    workflow_instance_id = Column(BigInteger, nullable=True)
    payload = Column(JSONB, nullable=False)  # Contains message_type, ESMD payload, or letter package
    message_status_id = Column(Integer, nullable=True)  # FK to service_ops.message_status
    correlation_id = Column(UUID(as_uuid=False), nullable=True)  # For tracking resends
    attempt_count = Column(Integer, nullable=True, default=1)  # Number of attempts
    resend_of_message_id = Column(BigInteger, nullable=True)  # FK to previous message_id
    payload_hash = Column(Text, nullable=True)  # SHA-256 hash
    payload_version = Column(Integer, nullable=True, default=1)  # Payload version
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    audit_user = Column(String(100), nullable=True)
    audit_timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)

