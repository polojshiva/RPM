"""
SQLAlchemy models for packet_validation table
Stores validation audit trail with new record for each validation update
"""
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class PacketValidationDB(Base):
    """
    Maps to service_ops.packet_validation table
    Stores validation audit trail - new record for each validation update
    """
    __tablename__ = "packet_validation"
    
    packet_validation_id = Column(BigInteger, primary_key=True)
    packet_id = Column(BigInteger, ForeignKey("service_ops.packet.packet_id", ondelete="CASCADE"), nullable=False)
    packet_document_id = Column(BigInteger, ForeignKey("service_ops.packet_document.packet_document_id", ondelete="CASCADE"), nullable=False)
    
    validation_status = Column(Text, nullable=False)  # Pending - Validation, Validation In Progress, etc.
    validation_type = Column(Text, nullable=True)  # HETS, PECOS, FIELD_VALIDATION, MANUAL_REVIEW, FINAL
    validation_result = Column(JSONB, nullable=True)  # Validation output data
    validation_errors = Column(JSONB, nullable=True)  # Any errors found
    is_passed = Column(Boolean, nullable=True)  # TRUE if validation passed
    is_active = Column(Boolean, nullable=False, server_default='true')  # TRUE for current validation state
    
    # Audit trail links
    supersedes = Column(BigInteger, ForeignKey("service_ops.packet_validation.packet_validation_id", ondelete="SET NULL"), nullable=True)
    superseded_by = Column(BigInteger, ForeignKey("service_ops.packet_validation.packet_validation_id", ondelete="SET NULL"), nullable=True)
    
    update_reason = Column(Text, nullable=True)  # Why validation was updated/corrected
    validated_by = Column(Text, nullable=True)  # User who performed/updated validation
    validated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    
    # Add check constraints
    __table_args__ = (
        CheckConstraint(
            "validation_status IN ('Pending - Validation', 'Validation In Progress', 'Pending - Manual Review', 'Validation Updated', 'Validation Complete', 'Validation Failed')",
            name="check_validation_status"
        ),
    )

