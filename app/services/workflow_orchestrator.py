"""
Workflow Orchestrator Service
Central service to handle status transitions based on workflow rules
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.packet_validation_db import PacketValidationDB

logger = logging.getLogger(__name__)


class WorkflowOrchestratorService:
    """
    Central service for managing workflow status transitions
    Ensures status, validation_status, and decisions are always in sync
    """
    
    @staticmethod
    def update_packet_status(
        db: Session,
        packet: PacketDB,
        new_status: str,
        validation_status: Optional[str] = None,
        release_lock: bool = False
    ) -> None:
        """
        Update packet status with validation
        
        Args:
            db: Database session
            packet: PacketDB instance
            new_status: New detailed_status value
            validation_status: Optional new validation_status (if None, keeps current)
            release_lock: If True, sets assigned_to = None
        """
        packet.detailed_status = new_status
        
        if validation_status:
            packet.validation_status = validation_status
        
        if release_lock:
            packet.assigned_to = None
        
        packet.updated_at = datetime.now(timezone.utc)
        db.flush()
        
        logger.info(
            f"Updated packet status: "
            f"packet_id={packet.packet_id}, "
            f"status={new_status}, "
            f"validation_status={validation_status or packet.validation_status}"
        )
    
    @staticmethod
    def create_validation_record(
        db: Session,
        packet_id: int,
        packet_document_id: int,
        validation_status: str,
        validation_type: Optional[str] = None,
        validation_result: Optional[dict] = None,
        validation_errors: Optional[dict] = None,
        is_passed: Optional[bool] = None,
        update_reason: Optional[str] = None,
        validated_by: Optional[str] = None
    ) -> PacketValidationDB:
        """
        Create new validation record (audit trail)
        
        Args:
            db: Database session
            packet_id: Internal packet ID
            packet_document_id: Internal document ID
            validation_status: New validation status
            validation_type: Type of validation (HETS, PECOS, etc.)
            validation_result: Validation output data
            validation_errors: Any errors found
            is_passed: TRUE if validation passed
            update_reason: Why validation was updated
            validated_by: User who performed validation
            
        Returns:
            New PacketValidationDB instance
        """
        # Deactivate existing active validation records for this packet and validation_type
        # Only deactivate records of the same type (HETS/PECOS) to avoid affecting other validations
        filter_conditions = [
            PacketValidationDB.packet_id == packet_id,
            PacketValidationDB.is_active == True
        ]
        if validation_type:
            filter_conditions.append(PacketValidationDB.validation_type == validation_type)
        
        existing_validations = db.query(PacketValidationDB).filter(*filter_conditions).all()
        
        for existing in existing_validations:
            existing.is_active = False
        
        # Create new validation record
        new_validation = PacketValidationDB(
            packet_id=packet_id,
            packet_document_id=packet_document_id,
            validation_status=validation_status,
            validation_type=validation_type,
            validation_result=validation_result,
            validation_errors=validation_errors,
            is_passed=is_passed,
            is_active=True,
            supersedes=existing_validations[0].packet_validation_id if existing_validations else None,
            update_reason=update_reason,
            validated_by=validated_by,
            validated_at=datetime.now(timezone.utc)
        )
        
        # Link superseded validations
        if existing_validations:
            for existing in existing_validations:
                existing.superseded_by = new_validation.packet_validation_id
        
        db.add(new_validation)
        db.flush()
        
        logger.info(
            f"Created validation record: "
            f"packet_id={packet_id}, "
            f"validation_status={validation_status}, "
            f"validation_type={validation_type}"
        )
        
        return new_validation
    
    @staticmethod
    def get_active_decision(db: Session, packet_id: int) -> Optional[PacketDecisionDB]:
        """Get current active decision for a packet"""
        return db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == packet_id,
            PacketDecisionDB.is_active == True
        ).first()
    
    @staticmethod
    def get_active_validation(db: Session, packet_id: int) -> Optional[PacketValidationDB]:
        """Get current active validation for a packet"""
        return db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == packet_id,
            PacketValidationDB.is_active == True
        ).first()

