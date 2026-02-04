"""
SQLAlchemy models for validation_run table
Stores HETS and PECOS validation runs with full request/response payloads
"""
from sqlalchemy import Column, BigInteger, String, Integer, Boolean, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class ValidationRunDB(Base):
    """
    Maps to service_ops.validation_run table
    Stores every HETS and PECOS validation run with full request/response payloads
    """
    __tablename__ = "validation_run"
    
    validation_run_id = Column(BigInteger, primary_key=True)
    packet_id = Column(BigInteger, ForeignKey("service_ops.packet.packet_id", ondelete="CASCADE"), nullable=False)
    packet_document_id = Column(BigInteger, ForeignKey("service_ops.packet_document.packet_document_id", ondelete="CASCADE"), nullable=False)
    validation_type = Column(String(10), nullable=False)  # 'HETS' or 'PECOS'
    request_payload = Column(JSONB, nullable=False)
    response_payload = Column(JSONB, nullable=True)
    response_status_code = Column(Integer, nullable=True)
    response_success = Column(Boolean, nullable=True)
    upstream_request_id = Column(String(255), nullable=True)  # e.g. HETS request_id
    normalized_npi = Column(String(10), nullable=True)  # For PECOS: normalized 10-digit NPI
    duration_ms = Column(Integer, nullable=True)
    correlation_id = Column(UUID(as_uuid=False), nullable=False, server_default="gen_random_uuid()")
    created_by = Column(String(255), nullable=True)  # user email
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    
    # Add check constraint for validation_type
    __table_args__ = (
        CheckConstraint("validation_type IN ('HETS', 'PECOS')", name="check_validation_type"),
    )

