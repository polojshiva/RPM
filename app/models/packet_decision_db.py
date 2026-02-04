"""
SQLAlchemy models for packet_decision table
Stores approve and dismissal decisions with denial reason + details
Extended for UTN workflow: ESMD/UTN/letter tracking
"""
from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, CheckConstraint, Integer, Boolean
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class PacketDecisionDB(Base):
    """
    Maps to service_ops.packet_decision table
    Stores approve and dismissal decisions for packets/documents
    Extended for UTN workflow with ESMD/UTN/letter state tracking
    """
    __tablename__ = "packet_decision"
    
    # Primary key and foreign keys
    packet_decision_id = Column(BigInteger, primary_key=True)
    packet_id = Column(BigInteger, ForeignKey("service_ops.packet.packet_id", ondelete="CASCADE"), nullable=False)
    packet_document_id = Column(BigInteger, ForeignKey("service_ops.packet_document.packet_document_id", ondelete="CASCADE"), nullable=False)
    
    # Original decision fields
    decision_type = Column(String(20), nullable=False)  # 'APPROVE' or 'DISMISSAL'
    denial_reason = Column(String(50), nullable=True)  # For DISMISSAL: reason code
    denial_details = Column(JSONB, nullable=True)  # Reason-specific structured data
    notes = Column(Text, nullable=True)
    linked_validation_run_ids = Column(JSONB, nullable=True)  # { "hets": <id>|null, "pecos": <id>|null }
    correlation_id = Column(UUID(as_uuid=False), nullable=False, server_default="gen_random_uuid()")
    created_by = Column(String(255), nullable=True)  # user email
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    
    # ============================================================================
    # New Workflow Decision Fields
    # ============================================================================
    
    # Operational decision (ServiceOps)
    operational_decision = Column(Text, nullable=False, server_default='PENDING')  # PENDING, DISMISSAL, DISMISSAL_COMPLETE, DECISION_COMPLETE
    
    # Clinical decision (ClinicalOps)
    clinical_decision = Column(Text, nullable=False, server_default='PENDING')  # PENDING, AFFIRM, NON_AFFIRM
    
    # Audit trail fields
    is_active = Column(Boolean, nullable=False, server_default='true')  # TRUE for current decision
    supersedes = Column(BigInteger, ForeignKey("service_ops.packet_decision.packet_decision_id", ondelete="SET NULL"), nullable=True)  # FK to previous decision
    superseded_by = Column(BigInteger, ForeignKey("service_ops.packet_decision.packet_decision_id", ondelete="SET NULL"), nullable=True)  # FK to next decision
    
    # ============================================================================
    # UTN Workflow Fields (added in migration 012)
    # ============================================================================
    
    # Decision context
    decision_subtype = Column(Text, nullable=True)  # DIRECT_PA / STANDARD_PA
    decision_outcome = Column(Text, nullable=True)  # AFFIRM / NON_AFFIRM / DISMISSAL
    part_type = Column(Text, nullable=True)  # A / B
    
    # ESMD request tracking
    esmd_request_status = Column(Text, nullable=True, default='NOT_SENT')  # NOT_SENT / SENT / ACKED / FAILED / RESEND_REQUIRED
    esmd_request_payload = Column(JSONB, nullable=True)  # Last payload sent
    esmd_request_payload_history = Column(JSONB, nullable=True, default='[]')  # Array of prior payloads
    esmd_attempt_count = Column(Integer, nullable=True, default=0)
    esmd_last_sent_at = Column(DateTime(timezone=True), nullable=True)
    esmd_last_error = Column(Text, nullable=True)
    
    # UTN tracking
    utn = Column(Text, nullable=True)  # Unique Tracking Number
    utn_status = Column(Text, nullable=True, default='NONE')  # NONE / SUCCESS / FAILED
    utn_received_at = Column(DateTime(timezone=True), nullable=True)
    utn_fail_payload = Column(JSONB, nullable=True)  # Full UTN_FAIL payload
    utn_action_required = Column(Text, nullable=True)  # Action required message
    requires_utn_fix = Column(Boolean, nullable=True, default=False)  # Flag for UI remediation
    
    # Letter tracking
    letter_owner = Column(Text, nullable=True)  # CLINICAL_OPS / SERVICE_OPS
    letter_status = Column(Text, nullable=True, default='NONE')  # NONE / PENDING / READY / SENT
    letter_package = Column(JSONB, nullable=True)  # Letter package metadata
    letter_medical_docs = Column(JSONB, nullable=True, default='[]')  # Array of doc URLs/paths
    letter_generated_at = Column(DateTime(timezone=True), nullable=True)
    letter_sent_to_integration_at = Column(DateTime(timezone=True), nullable=True)
    
    # Add check constraints
    __table_args__ = (
        CheckConstraint("decision_type IN ('APPROVE', 'DISMISSAL')", name="check_decision_type"),
        CheckConstraint(
            "denial_reason IS NULL OR denial_reason IN ('MISSING_FIELDS', 'INVALID_PECOS', 'INVALID_HETS', 'PROCEDURE_NOT_SUPPORTED', 'NO_MEDICAL_RECORDS', 'OTHER')",
            name="check_denial_reason"
        ),
    )

