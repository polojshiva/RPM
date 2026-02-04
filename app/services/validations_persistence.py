"""
Validations Persistence Service
Handles persisting HETS and PECOS validation runs to database
"""
import time
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
import uuid

from app.models.validation_run_db import ValidationRunDB

logger = logging.getLogger(__name__)


class ValidationsPersistenceService:
    """
    Service for persisting validation runs to database
    """
    
    @staticmethod
    def create_validation_run(
        db: Session,
        packet_id: int,
        packet_document_id: int,
        validation_type: str,  # 'HETS' or 'PECOS'
        request_payload: Dict[str, Any],
        response_payload: Optional[Dict[str, Any]] = None,
        response_status_code: Optional[int] = None,
        response_success: Optional[bool] = None,
        upstream_request_id: Optional[str] = None,
        normalized_npi: Optional[str] = None,
        duration_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> ValidationRunDB:
        """
        Create a validation run record in database
        
        Args:
            db: Database session
            packet_id: Internal packet ID (BIGINT)
            packet_document_id: Internal document ID (BIGINT)
            validation_type: 'HETS' or 'PECOS'
            request_payload: Full request payload (dict, will be stored as JSONB)
            response_payload: Full response payload (dict, will be stored as JSONB)
            response_status_code: HTTP status code from upstream service
            response_success: Whether upstream service returned success
            upstream_request_id: Upstream service request ID (e.g. HETS request_id)
            normalized_npi: For PECOS: normalized 10-digit NPI
            duration_ms: Request duration in milliseconds
            correlation_id: UUID for idempotency (generated if not provided)
            created_by: User email from auth context
            
        Returns:
            ValidationRunDB instance (already committed to DB)
        """
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())
        
        validation_run = ValidationRunDB(
            packet_id=packet_id,
            packet_document_id=packet_document_id,
            validation_type=validation_type,
            request_payload=request_payload,
            response_payload=response_payload,
            response_status_code=response_status_code,
            response_success=response_success,
            upstream_request_id=upstream_request_id,
            normalized_npi=normalized_npi,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            created_by=created_by
        )
        
        db.add(validation_run)
        db.commit()
        db.refresh(validation_run)
        
        logger.info(
            f"Persisted {validation_type} validation run: "
            f"validation_run_id={validation_run.validation_run_id}, "
            f"packet_document_id={packet_document_id}, "
            f"correlation_id={correlation_id}, "
            f"duration_ms={duration_ms}"
        )
        
        return validation_run
    
    @staticmethod
    def get_last_validation_run_ids(
        db: Session,
        packet_document_id: int
    ) -> Dict[str, Optional[int]]:
        """
        Get the IDs of the last HETS and PECOS validation runs for a document
        
        Args:
            db: Database session
            packet_document_id: Internal document ID (BIGINT)
            
        Returns:
            Dict with keys 'hets' and 'pecos', values are validation_run_id (int) or None
        """
        result = {
            'hets': None,
            'pecos': None
        }
        
        # Get last HETS run
        hets_run = db.query(ValidationRunDB).filter(
            ValidationRunDB.packet_document_id == packet_document_id,
            ValidationRunDB.validation_type == 'HETS'
        ).order_by(desc(ValidationRunDB.created_at)).first()
        
        if hets_run:
            result['hets'] = hets_run.validation_run_id
        
        # Get last PECOS run
        pecos_run = db.query(ValidationRunDB).filter(
            ValidationRunDB.packet_document_id == packet_document_id,
            ValidationRunDB.validation_type == 'PECOS'
        ).order_by(desc(ValidationRunDB.created_at)).first()
        
        if pecos_run:
            result['pecos'] = pecos_run.validation_run_id
        
        return result

