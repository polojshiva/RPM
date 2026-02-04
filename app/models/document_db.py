"""
SQLAlchemy models for service_ops schema (packet_document, letters, ocr_extraction)
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import MetaData
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base

class PacketDocumentDB(Base):
    """
    Maps to service_ops.packet_document table
    Stores documents associated with packets, including OCR extracted fields
    """
    __tablename__ = "packet_document"
    
    packet_document_id = Column(BigInteger, primary_key=True)
    external_id = Column(String(50), unique=True, nullable=False)  # Display ID like DOC-XXXX
    packet_id = Column(BigInteger, ForeignKey("service_ops.packet.packet_id"), nullable=False)
    file_name = Column(String(500), nullable=False)
    document_unique_identifier = Column(String(100), nullable=False)  # Unique identifier from integration layer (for idempotency) - NOT NULL enforced by migration 003
    page_count = Column(Integer, default=0)
    file_size = Column(String(50))
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    ocr_confidence = Column(Integer)  # OCR confidence score (0-100)
    extracted_data = Column(Boolean, default=False)  # Flag indicating extraction completed
    thumbnail_url = Column(String(1000))
    download_url = Column(String(1000))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign keys
    # Note: ForeignKey constraints removed to avoid SQLAlchemy resolution issues with lookup tables
    document_type_id = Column(BigInteger, nullable=False)
    status_type_id = Column(BigInteger, nullable=True)
    
    # OCR extracted fields stored as JSONB
    extracted_fields = Column(JSONB, nullable=True)  # Full OCR JSON payload
    
    # Page tracking and OCR metadata columns (added in migration 002)
    processing_path = Column(Text, nullable=True)  # Blob folder path for split pages
    pages_metadata = Column(JSONB, nullable=True)  # Page-level metadata (see migration for structure)
    coversheet_page_number = Column(Integer, nullable=True)  # Page number containing coversheet (1-indexed)
    part_type = Column(String(20), nullable=True)  # PART_A, PART_B, or UNKNOWN
    ocr_metadata = Column(JSONB, nullable=True)  # OCR processing metadata (confidence, field counts, etc.)
    split_status = Column(String(20), nullable=True, default='NOT_STARTED')  # NOT_STARTED, DONE, FAILED
    ocr_status = Column(String(20), nullable=True, default='NOT_STARTED')  # NOT_STARTED, DONE, FAILED
    
    # Consolidated document workflow (added in migration 004)
    consolidated_blob_path = Column(Text, nullable=True)  # Blob path to consolidated PDF (merged from all input documents)
    
    # Manual review and audit fields (added in migration 006)
    updated_extracted_fields = Column(JSONB, nullable=True)  # Full snapshot of all fields after manual save (with metadata)
    extracted_fields_update_history = Column(JSONB, nullable=True)  # Append-only audit trail of manual updates
    
    # OCR suggestion field (added in migration 007)
    suggested_extracted_fields = Column(JSONB, nullable=True)  # Latest OCR coversheet result from "Mark as Coversheet" rerun (preserves manual edits)
    
    # Approved unit of service fields (added in migration 027)
    approved_unit_of_service_1 = Column(String(255), nullable=True)  # Approved unit of service 1 - entered manually from UI
    approved_unit_of_service_2 = Column(String(255), nullable=True)  # Approved unit of service 2 - entered manually from UI
    approved_unit_of_service_3 = Column(String(255), nullable=True)  # Approved unit of service 3 - entered manually from UI
    
    # Relationship - commented out to avoid circular import issues
    # Can be added back after ensuring proper import order
    # packet = relationship("PacketDB", back_populates="documents")

# Keep old names for backward compatibility (will be deprecated)
DocumentDB = PacketDocumentDB

class LetterDB(Base):
    """
    Maps to service_ops.letter table
    """
    __tablename__ = "letter"
    
    letter_id = Column(BigInteger, primary_key=True)
    external_id = Column(String(50), unique=True, nullable=False)  # Display ID like LTR-XXXX
    packet_id = Column(BigInteger, ForeignKey("service_ops.packet.packet_id"), nullable=False)
    clinical_case_id = Column(BigInteger, ForeignKey("service_ops.clinical_case.clinical_case_id"), nullable=True)
    beneficiary_name = Column(String(255), nullable=False)
    service_type = Column(String(255), nullable=False)
    created_date = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by = Column(String(255), nullable=False)
    template_id = Column(String(50), nullable=False)
    language = Column(String(50), default="English")
    sent_date = Column(DateTime(timezone=True), nullable=True)
    delivered_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign keys
    status_type_id = Column(BigInteger, ForeignKey("service_ops.status_type.status_type_id"), nullable=True)
    letter_type_id = Column(BigInteger, ForeignKey("service_ops.letter_type.letter_type_id"), nullable=True)
    delivery_method_id = Column(BigInteger, ForeignKey("service_ops.delivery_method.delivery_method_id"), nullable=True)

class OCRExtractionDB(Base):
    """
    Legacy table - OCR data should now be stored in packet_document.extracted_fields
    Keeping for backward compatibility
    """
    __tablename__ = "ocr_extractions"
    id = Column(String, primary_key=True)
    packet_id = Column(BigInteger, ForeignKey("service_ops.packet.packet_id"), nullable=False)
    data = Column(JSONB)
    field_issues = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

class DocumentClassificationDB(Base):
    """
    Legacy table - keeping for backward compatibility
    """
    __tablename__ = "document_classifications"
    id = Column(String, primary_key=True)
    packet_id = Column(BigInteger, ForeignKey("service_ops.packet.packet_id"), nullable=False)
    classification = Column(String(100))
    confidence = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
