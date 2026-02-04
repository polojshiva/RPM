"""
ClinicalOps Rejection Processor
Processes rejected ClinicalOps records and loops them back to ServiceOps validation phase
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.models.send_clinicalops_db import SendClinicalOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.services.workflow_orchestrator import WorkflowOrchestratorService

logger = logging.getLogger(__name__)


class ClinicalOpsRejectionProcessor:
    """
    Processes rejected ClinicalOps records and loops them back to validation
    """
    
    @staticmethod
    def process_rejected_records(db: Session, batch_size: int = 10) -> int:
        """
        Process rejected records and loop them back to validation
        
        This method:
        1. Queries for records where is_picked = false with error_reason
        2. Finds corresponding packets
        3. Updates packet status to "Intake Validation"
        4. Creates validation record with error_reason
        5. Marks record as processed to avoid reprocessing
        
        Args:
            db: Database session
            batch_size: Maximum number of records to process in one batch
            
        Returns:
            Number of records successfully processed
        """
        # Query rejected records that haven't been looped back yet
        rejected_records = db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.is_picked == False,
            SendClinicalOpsDB.is_deleted == False,
            SendClinicalOpsDB.error_reason.isnot(None),
            SendClinicalOpsDB.is_looped_back_to_validation == False
        ).limit(batch_size).all()
        
        if not rejected_records:
            logger.debug("No rejected records found to process")
            return 0
        
        logger.info(f"Found {len(rejected_records)} rejected records to process")
        
        processed_count = 0
        
        for record in rejected_records:
            try:
                # Find packet by decision_tracking_id
                packet = db.query(PacketDB).filter(
                    PacketDB.decision_tracking_id == record.decision_tracking_id
                ).first()
                
                if not packet:
                    logger.warning(
                        f"Packet not found for rejected record: "
                        f"message_id={record.message_id}, "
                        f"decision_tracking_id={record.decision_tracking_id}"
                    )
                    # Mark as processed to avoid retrying
                    record.is_looped_back_to_validation = True
                    db.flush()
                    continue
                
                # Get packet document (primary document)
                document = db.query(PacketDocumentDB).filter(
                    PacketDocumentDB.packet_id == packet.packet_id
                ).order_by(PacketDocumentDB.packet_document_id.asc()).first()  # Get first document
                
                if not document:
                    logger.warning(
                        f"Document not found for packet_id={packet.packet_id}, "
                        f"decision_tracking_id={record.decision_tracking_id}"
                    )
                    record.is_looped_back_to_validation = True
                    db.flush()
                    continue
                
                # Loop back to validation phase
                WorkflowOrchestratorService.update_packet_status(
                    db=db,
                    packet=packet,
                    new_status="Intake Validation",
                    validation_status="Pending - Validation",
                    release_lock=True  # Release lock so anyone can pick it up
                )
                
                # Create validation record with error reason for audit trail
                WorkflowOrchestratorService.create_validation_record(
                    db=db,
                    packet_id=packet.packet_id,
                    packet_document_id=document.packet_document_id,
                    validation_status="Pending - Validation",
                    validation_type="CLINICAL_OPS_REJECTION",
                    validation_errors={"error_reason": record.error_reason},
                    is_passed=False,
                    update_reason=f"ClinicalOps rejected: {record.error_reason}",
                    validated_by="clinical_ops_system"
                )
                
                # Mark as processed (to avoid infinite loop)
                record.is_looped_back_to_validation = True
                
                processed_count += 1
                
                logger.info(
                    f"Looped rejected record back to validation: "
                    f"message_id={record.message_id}, "
                    f"packet_id={packet.packet_id}, "
                    f"packet_external_id={packet.external_id}, "
                    f"error_reason={record.error_reason}"
                )
                
            except Exception as e:
                logger.error(
                    f"Error processing rejected record message_id={record.message_id}, "
                    f"decision_tracking_id={record.decision_tracking_id}: {e}",
                    exc_info=True
                )
                # Don't mark as processed on error - will retry next time
                # Rollback this record's changes but continue with others
                db.rollback()
                # Re-query the record to get fresh state
                record = db.query(SendClinicalOpsDB).filter(
                    SendClinicalOpsDB.message_id == record.message_id
                ).first()
                if not record:
                    break  # Record was deleted, exit loop
        
        # Commit all successful changes
        if processed_count > 0:
            db.commit()
            logger.info(f"Successfully processed {processed_count} rejected records")
        
        return processed_count
    
    @staticmethod
    def get_rejected_records_count(db: Session) -> int:
        """
        Get count of rejected records that need to be processed
        
        Args:
            db: Database session
            
        Returns:
            Number of unprocessed rejected records
        """
        count = db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.is_picked == False,
            SendClinicalOpsDB.is_deleted == False,
            SendClinicalOpsDB.error_reason.isnot(None),
            SendClinicalOpsDB.is_looped_back_to_validation == False
        ).count()
        
        return count
