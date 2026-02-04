"""
Decisions Service
Handles persisting approve and dismissal decisions to database
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text
import uuid

from app.models.packet_decision_db import PacketDecisionDB
from app.services.validations_persistence import ValidationsPersistenceService

logger = logging.getLogger(__name__)


class DecisionsService:
    """
    Service for persisting approve and dismissal decisions
    """
    
    @staticmethod
    def create_approve_decision(
        db: Session,
        packet_id: int,
        packet_document_id: int,
        notes: Optional[str] = None,
        correlation_id: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> PacketDecisionDB:
        """
        Create an approve decision record
        
        Args:
            db: Database session
            packet_id: Internal packet ID (BIGINT)
            packet_document_id: Internal document ID (BIGINT)
            notes: Optional approval notes
            correlation_id: UUID for idempotency (generated if not provided)
            created_by: User email from auth context
            
        Returns:
            PacketDecisionDB instance (already committed to DB)
        """
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())
        
        # Get last validation run IDs
        linked_runs = ValidationsPersistenceService.get_last_validation_run_ids(
            db, packet_document_id
        )
        
        # Check for existing decision with same correlation_id (idempotency)
        if correlation_id:
            existing_by_correlation = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet_id,
                PacketDecisionDB.correlation_id == correlation_id,
                PacketDecisionDB.decision_type == 'APPROVE'
            ).first()
            
            if existing_by_correlation:
                logger.info(
                    f"Found existing APPROVE decision with correlation_id={correlation_id}. "
                    f"Returning existing decision (idempotent)."
                )
                return existing_by_correlation
        
        # Deactivate any existing active decisions for this packet
        # Use SELECT FOR UPDATE to prevent race conditions
        # Handle missing decision_subtype column gracefully (migration may not be applied yet)
        try:
            existing_decisions = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet_id,
                PacketDecisionDB.is_active == True
            ).with_for_update().all()  # Lock rows during transaction to prevent race conditions
            
            for existing in existing_decisions:
                existing.is_active = False
        except ProgrammingError as e:
            # Handle missing column gracefully (decision_subtype may not exist in production yet)
            if 'decision_subtype' in str(e) or 'UndefinedColumn' in str(e):
                logger.warning(
                    f"decision_subtype column not found in packet_decision table. "
                    f"Using raw SQL to deactivate decisions. Error: {e}"
                )
                # Use raw SQL to deactivate existing decisions (avoids column reference)
                db.execute(text("""
                    UPDATE service_ops.packet_decision
                    SET is_active = false
                    WHERE packet_id = :packet_id AND is_active = true
                """), {"packet_id": packet_id})
                db.flush()
            else:
                raise
        
        decision = PacketDecisionDB(
            packet_id=packet_id,
            packet_document_id=packet_document_id,
            decision_type='APPROVE',
            denial_reason=None,
            denial_details=None,
            notes=notes,
            linked_validation_run_ids=linked_runs,
            correlation_id=correlation_id,
            created_by=created_by,
            operational_decision='PENDING',  # Stays PENDING until final stage
            clinical_decision='PENDING',  # Will be updated by ClinicalOps
            is_active=True,
            supersedes=existing_decisions[0].packet_decision_id if existing_decisions else None
        )
        
        # Link superseded decisions
        if existing_decisions:
            for existing in existing_decisions:
                existing.superseded_by = decision.packet_decision_id
        
        db.add(decision)
        db.commit()
        db.refresh(decision)
        
        logger.info(
            f"Persisted APPROVE decision: "
            f"packet_decision_id={decision.packet_decision_id}, "
            f"packet_document_id={packet_document_id}, "
            f"correlation_id={correlation_id}, "
            f"linked_runs={linked_runs}"
        )
        
        return decision
    
    @staticmethod
    def create_dismissal_decision(
        db: Session,
        packet_id: int,
        packet_document_id: int,
        denial_reason: str,
        denial_details: Dict[str, Any],
        notes: Optional[str] = None,
        correlation_id: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> PacketDecisionDB:
        """
        Create a dismissal decision record
        
        Args:
            db: Database session
            packet_id: Internal packet ID (BIGINT)
            packet_document_id: Internal document ID (BIGINT)
            denial_reason: One of: 'MISSING_FIELDS', 'INVALID_PECOS', 'INVALID_HETS', 
                          'PROCEDURE_NOT_SUPPORTED', 'NO_MEDICAL_RECORDS', 'OTHER'
            denial_details: Reason-specific structured data (dict)
            notes: Optional dismissal notes
            correlation_id: UUID for idempotency (generated if not provided)
            created_by: User email from auth context
            
        Returns:
            PacketDecisionDB instance (already committed to DB)
        """
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())
        
        # Get last validation run IDs
        linked_runs = ValidationsPersistenceService.get_last_validation_run_ids(
            db, packet_document_id
        )
        
        # Check for existing decision with same correlation_id (idempotency)
        if correlation_id:
            existing_by_correlation = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet_id,
                PacketDecisionDB.correlation_id == correlation_id,
                PacketDecisionDB.decision_type == 'DISMISSAL'
            ).first()
            
            if existing_by_correlation:
                logger.info(
                    f"Found existing DISMISSAL decision with correlation_id={correlation_id}. "
                    f"Returning existing decision (idempotent)."
                )
                return existing_by_correlation
        
        # Deactivate any existing active decisions for this packet
        # Use SELECT FOR UPDATE to prevent race conditions
        # Handle missing decision_subtype column gracefully (migration may not be applied yet)
        try:
            existing_decisions = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet_id,
                PacketDecisionDB.is_active == True
            ).with_for_update().all()  # Lock rows during transaction to prevent race conditions
            
            for existing in existing_decisions:
                existing.is_active = False
        except ProgrammingError as e:
            # Handle missing column gracefully (decision_subtype may not exist in production yet)
            if 'decision_subtype' in str(e) or 'UndefinedColumn' in str(e):
                logger.warning(
                    f"decision_subtype column not found in packet_decision table. "
                    f"Using raw SQL to deactivate decisions. Error: {e}"
                )
                # Use raw SQL to deactivate existing decisions (avoids column reference)
                db.execute(text("""
                    UPDATE service_ops.packet_decision
                    SET is_active = false
                    WHERE packet_id = :packet_id AND is_active = true
                """), {"packet_id": packet_id})
                db.flush()
            else:
                raise
        
        decision = PacketDecisionDB(
            packet_id=packet_id,
            packet_document_id=packet_document_id,
            decision_type='DISMISSAL',
            denial_reason=denial_reason,
            denial_details=denial_details,
            notes=notes,
            linked_validation_run_ids=linked_runs,
            correlation_id=correlation_id,
            created_by=created_by,
            operational_decision='DISMISSAL',  # Set to DISMISSAL immediately
            clinical_decision='PENDING',  # Never sent to ClinicalOps
            is_active=True,
            supersedes=existing_decisions[0].packet_decision_id if existing_decisions else None
        )
        
        # Link superseded decisions
        if existing_decisions:
            for existing in existing_decisions:
                existing.superseded_by = decision.packet_decision_id
        
        db.add(decision)
        db.commit()
        db.refresh(decision)
        
        logger.info(
            f"Persisted DISMISSAL decision: "
            f"packet_decision_id={decision.packet_decision_id}, "
            f"packet_document_id={packet_document_id}, "
            f"denial_reason={denial_reason}, "
            f"correlation_id={correlation_id}, "
            f"linked_runs={linked_runs}"
        )
        
        return decision
    
    @staticmethod
    def update_operational_decision(
        db: Session,
        packet_id: int,
        new_operational_decision: str,  # 'DECISION_COMPLETE' or 'DISMISSAL_COMPLETE'
        created_by: Optional[str] = None
    ) -> PacketDecisionDB:
        """
        Update operational decision (creates new decision record for audit trail)
        
        Args:
            db: Database session
            packet_id: Internal packet ID
            new_operational_decision: New operational decision value
            created_by: User email from auth context
            
        Returns:
            New PacketDecisionDB instance (already committed)
        """
        # Get current active decision
        # Use SELECT FOR UPDATE to prevent race conditions
        # Handle missing decision_subtype column gracefully (migration may not be applied yet)
        try:
            current_decision = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet_id,
                PacketDecisionDB.is_active == True
            ).with_for_update().first()  # Lock row during transaction to prevent race conditions
        except ProgrammingError as e:
            # Handle missing column gracefully (decision_subtype may not exist in production yet)
            if 'decision_subtype' in str(e) or 'UndefinedColumn' in str(e):
                logger.warning(
                    f"decision_subtype column not found in packet_decision table. "
                    f"Using raw SQL to get active decision. Error: {e}"
                )
                # Use raw SQL to get active decision with FOR UPDATE (avoids column reference)
                result = db.execute(text("""
                    SELECT packet_decision_id, packet_document_id, decision_type, denial_reason,
                           denial_details, notes, linked_validation_run_ids, correlation_id,
                           operational_decision, clinical_decision
                    FROM service_ops.packet_decision
                    WHERE packet_id = :packet_id AND is_active = true
                    LIMIT 1
                    FOR UPDATE
                """), {"packet_id": packet_id}).first()
                
                if not result:
                    raise ValueError(f"No active decision found for packet_id={packet_id}")
                
                # Create a minimal object with the fields we need
                class MinimalDecision:
                    def __init__(self, row):
                        self.packet_decision_id = row[0]
                        self.packet_document_id = row[1]
                        self.decision_type = row[2]
                        self.denial_reason = row[3]
                        self.denial_details = row[4]
                        self.notes = row[5]
                        self.linked_validation_run_ids = row[6]
                        self.correlation_id = row[7]
                        self.operational_decision = row[8]
                        self.clinical_decision = row[9]
                        self.is_active = True
                
                current_decision = MinimalDecision(result)
            else:
                raise
        
        if not current_decision:
            raise ValueError(f"No active decision found for packet_id={packet_id}")
        
        # Deactivate current decision
        try:
            current_decision.is_active = False
        except AttributeError:
            # If using MinimalDecision, use raw SQL to deactivate
            db.execute(text("""
                UPDATE service_ops.packet_decision
                SET is_active = false
                WHERE packet_id = :packet_id AND is_active = true
            """), {"packet_id": packet_id})
            db.flush()
        
        # Create new decision record
        new_decision = PacketDecisionDB(
            packet_id=packet_id,
            packet_document_id=current_decision.packet_document_id,
            decision_type=current_decision.decision_type,
            denial_reason=current_decision.denial_reason,
            denial_details=current_decision.denial_details,
            notes=current_decision.notes,
            linked_validation_run_ids=current_decision.linked_validation_run_ids,
            correlation_id=str(uuid.uuid4()),
            created_by=created_by,
            operational_decision=new_operational_decision,
            clinical_decision=current_decision.clinical_decision,  # Preserve clinical decision
            is_active=True,
            supersedes=current_decision.packet_decision_id,
            # Copy UTN workflow fields
            decision_subtype=current_decision.decision_subtype,
            decision_outcome=current_decision.decision_outcome,
            part_type=current_decision.part_type,
            esmd_request_status=current_decision.esmd_request_status,
            esmd_request_payload=current_decision.esmd_request_payload,
            utn=current_decision.utn,
            utn_status=current_decision.utn_status,
            letter_owner=current_decision.letter_owner,
            letter_status=current_decision.letter_status,
            letter_package=current_decision.letter_package
        )
        
        # Link superseded decision
        current_decision.superseded_by = new_decision.packet_decision_id
        
        db.add(new_decision)
        db.commit()
        db.refresh(new_decision)
        
        logger.info(
            f"Updated operational decision: "
            f"packet_id={packet_id}, "
            f"old={current_decision.operational_decision}, "
            f"new={new_operational_decision}"
        )
        
        return new_decision
    
    @staticmethod
    def update_clinical_decision(
        db: Session,
        packet_id: int,
        new_clinical_decision: str,  # 'AFFIRM' or 'NON_AFFIRM'
        decision_subtype: Optional[str] = None,  # 'DIRECT_PA' or 'STANDARD_PA'
        part_type: Optional[str] = None,  # 'A' or 'B'
        decision_outcome: Optional[str] = None,  # 'AFFIRM' or 'NON_AFFIRM'
        created_by: Optional[str] = None
    ) -> PacketDecisionDB:
        """
        Update clinical decision (creates new decision record for audit trail)
        
        Args:
            db: Database session
            packet_id: Internal packet ID
            new_clinical_decision: New clinical decision value ('AFFIRM' or 'NON_AFFIRM')
            decision_subtype: DIRECT_PA or STANDARD_PA
            part_type: A or B
            decision_outcome: AFFIRM or NON_AFFIRM
            created_by: User email from auth context
            
        Returns:
            New PacketDecisionDB instance (already committed)
        """
        # Get current active decision
        # Use SELECT FOR UPDATE to prevent race conditions
        # Handle missing decision_subtype column gracefully (migration may not be applied yet)
        try:
            current_decision = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet_id,
                PacketDecisionDB.is_active == True
            ).with_for_update().first()  # Lock row during transaction to prevent race conditions
        except ProgrammingError as e:
            # Handle missing column gracefully (decision_subtype may not exist in production yet)
            if 'decision_subtype' in str(e) or 'UndefinedColumn' in str(e):
                logger.warning(
                    f"decision_subtype column not found in packet_decision table. "
                    f"Using raw SQL to get active decision. Error: {e}"
                )
                # Use raw SQL to get active decision with FOR UPDATE (avoids column reference)
                result = db.execute(text("""
                    SELECT packet_decision_id, packet_document_id, decision_type, denial_reason,
                           denial_details, notes, linked_validation_run_ids, correlation_id,
                           operational_decision, clinical_decision
                    FROM service_ops.packet_decision
                    WHERE packet_id = :packet_id AND is_active = true
                    LIMIT 1
                    FOR UPDATE
                """), {"packet_id": packet_id}).first()
                
                if not result:
                    raise ValueError(f"No active decision found for packet_id={packet_id}")
                
                # Create a minimal object with the fields we need
                class MinimalDecision:
                    def __init__(self, row):
                        self.packet_decision_id = row[0]
                        self.packet_document_id = row[1]
                        self.decision_type = row[2]
                        self.denial_reason = row[3]
                        self.denial_details = row[4]
                        self.notes = row[5]
                        self.linked_validation_run_ids = row[6]
                        self.correlation_id = row[7]
                        self.operational_decision = row[8]
                        self.clinical_decision = row[9]
                        self.is_active = True
                        self.decision_subtype = None  # Not available from raw query
                
                current_decision = MinimalDecision(result)
            else:
                raise
        
        if not current_decision:
            raise ValueError(f"No active decision found for packet_id={packet_id}")
        
        # Deactivate current decision
        try:
            current_decision.is_active = False
        except AttributeError:
            # If using MinimalDecision, use raw SQL to deactivate
            db.execute(text("""
                UPDATE service_ops.packet_decision
                SET is_active = false
                WHERE packet_id = :packet_id AND is_active = true
            """), {"packet_id": packet_id})
            db.flush()
        
        # Create new decision record
        # Handle decision_subtype - use provided value or None if column doesn't exist
        decision_subtype_value = decision_subtype
        if not decision_subtype_value:
            try:
                decision_subtype_value = current_decision.decision_subtype
            except AttributeError:
                # Column doesn't exist or using MinimalDecision
                decision_subtype_value = None
        
        new_decision = PacketDecisionDB(
            packet_id=packet_id,
            packet_document_id=current_decision.packet_document_id,
            decision_type=current_decision.decision_type,
            denial_reason=current_decision.denial_reason,
            denial_details=current_decision.denial_details,
            notes=current_decision.notes,
            linked_validation_run_ids=current_decision.linked_validation_run_ids,
            correlation_id=str(uuid.uuid4()),
            created_by=created_by,
            operational_decision=current_decision.operational_decision,  # Preserve operational decision
            clinical_decision=new_clinical_decision,
            is_active=True,
            supersedes=current_decision.packet_decision_id,
            decision_subtype=decision_subtype_value,
            decision_outcome=decision_outcome or new_clinical_decision,
            part_type=part_type or current_decision.part_type,
            # Copy other fields
            esmd_request_status=current_decision.esmd_request_status,
            esmd_request_payload=current_decision.esmd_request_payload,
            utn=current_decision.utn,
            utn_status=current_decision.utn_status,
            letter_owner=current_decision.letter_owner,
            letter_status=current_decision.letter_status
        )
        
        # Link superseded decision
        current_decision.superseded_by = new_decision.packet_decision_id
        
        db.add(new_decision)
        db.commit()
        db.refresh(new_decision)
        
        logger.info(
            f"Updated clinical decision: "
            f"packet_id={packet_id}, "
            f"old={current_decision.clinical_decision}, "
            f"new={new_clinical_decision}"
        )
        
        return new_decision

