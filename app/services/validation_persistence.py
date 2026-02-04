"""
Validation Persistence Service
Handles saving and retrieving field validation errors from the database.
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_

logger = logging.getLogger(__name__)


def save_field_validation_errors(
    packet_id: int,
    validation_result: Dict[str, Any],
    db_session: Session
) -> Any:  # PacketValidationDB type, avoiding circular import
    """
    Save field validation errors to packet_validation table.
    
    Args:
        packet_id: Packet ID
        validation_result: Validation result from validate_all_fields()
        db_session: Database session
    
    Returns:
        PacketValidationDB instance
    """
    try:
        from app.models.packet_validation_db import PacketValidationDB
        from app.models.document_db import PacketDocumentDB
        
        # Get the first document for this packet (for packet_document_id)
        document = db_session.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet_id
        ).first()
        
        if not document:
            logger.warning(f"No document found for packet_id={packet_id}. Cannot save validation errors.")
            return None
        
        # Deactivate previous active validation records for this packet
        previous_validations = db_session.query(PacketValidationDB).filter(
            and_(
                PacketValidationDB.packet_id == packet_id,
                PacketValidationDB.validation_type == 'FIELD_VALIDATION',
                PacketValidationDB.is_active == True
            )
        ).all()
        
        superseded_by_id = None
        if previous_validations:
            # Create new validation record
            new_validation = PacketValidationDB(
                packet_id=packet_id,
                packet_document_id=document.packet_document_id,
                validation_status='Validation Complete' if not validation_result.get('has_errors') else 'Validation Failed',
                validation_type='FIELD_VALIDATION',
                validation_result={
                    'field_errors': validation_result.get('field_errors', {}),
                    'auto_fix_applied': validation_result.get('auto_fix_applied', {}),
                    'validated_at': validation_result.get('validated_at'),
                    'validated_by': validation_result.get('validated_by', 'system')
                },
                validation_errors=validation_result.get('field_errors', {}),
                is_passed=not validation_result.get('has_errors', False),
                is_active=True,
                validated_at=datetime.now(timezone.utc),
                validated_by=validation_result.get('validated_by', 'system')
            )
            db_session.add(new_validation)
            db_session.flush()  # Get the ID
            
            superseded_by_id = new_validation.packet_validation_id
            
            # Deactivate previous validations and link them
            for prev_validation in previous_validations:
                prev_validation.is_active = False
                prev_validation.superseded_by = superseded_by_id
                new_validation.supersedes = prev_validation.packet_validation_id
        
        else:
            # First validation for this packet
            new_validation = PacketValidationDB(
                packet_id=packet_id,
                packet_document_id=document.packet_document_id,
                validation_status='Validation Complete' if not validation_result.get('has_errors') else 'Validation Failed',
                validation_type='FIELD_VALIDATION',
                validation_result={
                    'field_errors': validation_result.get('field_errors', {}),
                    'auto_fix_applied': validation_result.get('auto_fix_applied', {}),
                    'validated_at': validation_result.get('validated_at'),
                    'validated_by': validation_result.get('validated_by', 'system')
                },
                validation_errors=validation_result.get('field_errors', {}),
                is_passed=not validation_result.get('has_errors', False),
                is_active=True,
                validated_at=datetime.now(timezone.utc),
                validated_by=validation_result.get('validated_by', 'system')
            )
            db_session.add(new_validation)
        
        return new_validation
        
    except Exception as e:
        logger.error(f"Error saving field validation errors for packet_id={packet_id}: {str(e)}")
        raise


def update_packet_validation_flag(
    packet_id: int,
    has_errors: bool,
    db_session: Session
) -> bool:
    """
    Update packet.has_field_validation_errors flag.
    
    Args:
        packet_id: Packet ID
        has_errors: True if validation errors exist
        db_session: Database session
    
    Returns:
        True if updated, False otherwise
    """
    try:
        from app.models.packet_db import PacketDB
        
        packet = db_session.query(PacketDB).filter(
            PacketDB.packet_id == packet_id
        ).first()
        
        if not packet:
            logger.warning(f"Packet not found: packet_id={packet_id}")
            return False
        
        # Update flag
        packet.has_field_validation_errors = has_errors
        packet.updated_at = datetime.now(timezone.utc)
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating packet validation flag for packet_id={packet_id}: {str(e)}")
        raise


def get_field_validation_errors(
    packet_id: int,
    db_session: Session
) -> Optional[Dict[str, Any]]:
    """
    Get field validation errors for a packet.
    
    Args:
        packet_id: Packet ID
        db_session: Database session
    
    Returns:
        Validation result dict or None if not found
    """
    try:
        from app.models.packet_validation_db import PacketValidationDB
        
        validation = db_session.query(PacketValidationDB).filter(
            and_(
                PacketValidationDB.packet_id == packet_id,
                PacketValidationDB.validation_type == 'FIELD_VALIDATION',
                PacketValidationDB.is_active == True
            )
        ).order_by(PacketValidationDB.validated_at.desc()).first()
        
        if not validation:
            return None
        
        # Extract field errors from validation_errors JSONB
        field_errors = validation.validation_errors or {}
        
        # Extract auto-fix results from validation_result JSONB
        validation_result = validation.validation_result or {}
        auto_fix_applied = validation_result.get('auto_fix_applied', {})
        
        return {
            'field_errors': field_errors,
            'auto_fix_applied': auto_fix_applied,
            'has_errors': not validation.is_passed if validation.is_passed is not None else len(field_errors) > 0,
            'validated_at': validation.validated_at.isoformat() if validation.validated_at else None,
            'validated_by': validation.validated_by
        }
        
    except Exception as e:
        logger.error(f"Error getting field validation errors for packet_id={packet_id}: {str(e)}")
        return None
