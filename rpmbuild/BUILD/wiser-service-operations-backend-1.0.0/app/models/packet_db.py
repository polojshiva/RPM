"""
SQLAlchemy models and DB session for service_ops schema (packets)
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Boolean, Text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.schema import MetaData
from datetime import datetime

# Use a custom schema for service_ops
Base = declarative_base(metadata=MetaData(schema="service_ops"))

class PacketDB(Base):
    __tablename__ = "packet"  # Changed from "packets" to match database

    packet_id = Column(BigInteger, primary_key=True)  # Primary key is bigserial
    external_id = Column(String(50), unique=True, nullable=False)  # Display ID like SVC-YYYY-XXXXXX
    decision_tracking_id = Column(UUID(as_uuid=False), unique=True, nullable=False)  # UUID from integration.send_serviceops - used for idempotency
    case_id = Column(String(50))  # Reserved for future internal use, not populated with decision_tracking_id
    beneficiary_name = Column(String(255), nullable=False)
    beneficiary_mbi = Column(String(50), nullable=False)
    provider_name = Column(String(255), nullable=False)
    provider_npi = Column(String(20), nullable=False)
    provider_fax = Column(String(20))
    service_type = Column(String(255), nullable=False)
    hcpcs = Column(String(20))
    procedure_code_1 = Column(String(20), nullable=True)  # Individual procedure code 1
    procedure_code_2 = Column(String(20), nullable=True)  # Individual procedure code 2
    procedure_code_3 = Column(String(20), nullable=True)  # Individual procedure code 3
    submission_type = Column(String(50), nullable=True)  # Expedited or Standard (from OCR)
    detailed_status = Column(String(255), nullable=False, server_default='Pending - New')
    validation_status = Column(Text, nullable=False, server_default='Pending - Validation')
    clinical_status = Column(String(255))
    delivery_status = Column(String(255))
    received_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    page_count = Column(Integer, default=0)
    completeness = Column(Integer, default=0)
    assigned_to = Column(String(255))
    closed_date = Column(DateTime(timezone=True))
    review_type = Column(String(50))
    intake_complete = Column(Boolean, default=False)
    validation_complete = Column(Boolean, default=False)
    clinical_review_complete = Column(Boolean, default=False)
    delivery_complete = Column(Boolean, default=False)
    letter_delivered = Column(DateTime(timezone=True))
    has_field_validation_errors = Column(Boolean, default=False, nullable=False)  # Field validation error flag
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign keys (nullable for now, can be populated later)
    # Note: ForeignKey constraints removed to avoid SQLAlchemy resolution issues with lookup tables
    # Database-level foreign keys still exist and are enforced
    status_type_id = Column(BigInteger, nullable=True)
    priority_level_id = Column(BigInteger, nullable=True)
    channel_type_id = Column(BigInteger, nullable=True)
    sla_status_type_id = Column(BigInteger, nullable=True)
    dismissal_reason_id = Column(BigInteger, nullable=True)
    
    # Relationships - commented out to avoid circular import issues
    # Can be added back after ensuring proper import order
    # documents = relationship("PacketDocumentDB", back_populates="packet", cascade="all, delete-orphan")
