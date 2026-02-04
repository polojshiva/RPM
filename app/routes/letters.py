"""
Letter Generation Routes
Endpoints for letter generation, retry, and status
"""
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.services.db import get_db
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
from app.models.user import User, UserRole
from app.auth.dependencies import get_current_user, require_roles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/packets", tags=["letters"])


@router.post("/{packet_id}/letters/retry")
async def retry_letter_generation(
    packet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR, UserRole.REVIEWER])),
):
    """
    Retry failed letter generation
    
    Validates that letter_status == 'FAILED' and retries letter generation
    """
    # Get packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Get active packet_decision
    packet_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).order_by(PacketDecisionDB.created_at.desc()).first()
    
    if not packet_decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet decision not found"
        )
    
    # Validate letter_status is FAILED
    if packet_decision.letter_status != 'FAILED':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Letter status is '{packet_decision.letter_status}', not 'FAILED'. Only failed letters can be retried."
        )
    
    # Get packet document
    packet_document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id
    ).first()
    
    if not packet_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet document not found"
        )
    
    # Determine letter type
    letter_type_map = {
        'AFFIRM': 'affirmation',
        'NON_AFFIRM': 'non-affirmation',
        'DISMISSAL': 'dismissal'
    }
    letter_type = letter_type_map.get(packet_decision.decision_outcome)
    
    if not letter_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown decision_outcome: {packet_decision.decision_outcome}"
        )
    
    # Retry letter generation
    letter_service = LetterGenerationService(db)
    try:
        letter_metadata = letter_service.generate_letter(
            packet=packet,
            packet_decision=packet_decision,
            packet_document=packet_document,
            letter_type=letter_type
        )
        
        # Update packet_decision
        packet_decision.letter_status = 'READY'
        packet_decision.letter_package = letter_metadata
        packet_decision.letter_generated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(
            f"Successfully retried letter generation for packet_id={packet.packet_id} | "
            f"blob_url={letter_metadata.get('blob_url')}"
        )
        
        return {
            "success": True,
            "message": "Letter generation retried successfully",
            "letter_status": "READY",
            "letter_metadata": letter_metadata
        }
        
    except LetterGenerationError as e:
        logger.error(
            f"Letter generation retry failed for packet_id={packet.packet_id}: {e}",
            exc_info=True
        )
        packet_decision.letter_status = 'FAILED'
        packet_decision.letter_package = {
            "error": {
                "code": "LETTER_GENERATION_ERROR",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Letter generation failed: {str(e)}"
        )
    except Exception as e:
        logger.error(
            f"Unexpected error during letter generation retry for packet_id={packet.packet_id}: {e}",
            exc_info=True
        )
        packet_decision.letter_status = 'FAILED'
        packet_decision.letter_package = {
            "error": {
                "code": "UNEXPECTED_ERROR",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )


@router.post("/{packet_id}/letters/reprocess")
async def reprocess_letter_by_urls(
    packet_id: str,
    inbound_json_blob_url: str,
    inbound_metadata_blob_url: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR])),
):
    """
    Reprocess letter generation using recovery endpoint
    
    Requires inbound_json_blob_url and inbound_metadata_blob_url from previous attempt
    """
    # Get packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Get active packet_decision
    packet_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).order_by(PacketDecisionDB.created_at.desc()).first()
    
    if not packet_decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet decision not found"
        )
    
    # Reprocess via LetterGen recovery endpoint
    letter_service = LetterGenerationService(db)
    try:
        letter_metadata = letter_service.reprocess_by_urls(
            inbound_json_blob_url=inbound_json_blob_url,
            inbound_metadata_blob_url=inbound_metadata_blob_url
        )
        
        # Update packet_decision
        packet_decision.letter_status = 'READY'
        packet_decision.letter_package = letter_metadata
        packet_decision.letter_generated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(
            f"Successfully reprocessed letter for packet_id={packet.packet_id} | "
            f"blob_url={letter_metadata.get('blob_url')}"
        )
        
        return {
            "success": True,
            "message": "Letter reprocessed successfully",
            "letter_status": "READY",
            "letter_metadata": letter_metadata
        }
        
    except LetterGenerationError as e:
        logger.error(
            f"Letter reprocessing failed for packet_id={packet.packet_id}: {e}",
            exc_info=True
        )
        packet_decision.letter_status = 'FAILED'
        packet_decision.letter_package = {
            "error": {
                "code": "LETTER_REPROCESS_ERROR",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Letter reprocessing failed: {str(e)}"
        )


@router.get("/{packet_id}/letters/status")
async def get_letter_status(
    packet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.COORDINATOR, UserRole.REVIEWER])),
):
    """
    Get current letter status and metadata
    """
    # Get packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Get active packet_decision
    packet_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).order_by(PacketDecisionDB.created_at.desc()).first()
    
    if not packet_decision:
        return {
            "letter_status": "NONE",
            "letter_package": None,
            "letter_generated_at": None,
            "error": None
        }
    
    # Extract error from letter_package if present
    error = None
    letter_package = packet_decision.letter_package or {}
    if isinstance(letter_package, dict) and 'error' in letter_package:
        error = letter_package['error']
    
    return {
        "letter_status": packet_decision.letter_status or "NONE",
        "letter_package": letter_package,
        "letter_generated_at": packet_decision.letter_generated_at.isoformat() if packet_decision.letter_generated_at else None,
        "letter_sent_to_integration_at": packet_decision.letter_sent_to_integration_at.isoformat() if packet_decision.letter_sent_to_integration_at else None,
        "error": error
    }
