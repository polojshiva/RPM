"""
ClinicalOps Outbox Service
Handles sending messages from ServiceOps to ClinicalOps via service_ops.send_clinicalops table
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.send_clinicalops_db import SendClinicalOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_validation_db import PacketValidationDB
from app.services.blob_storage import BlobStorageClient
from app.config.settings import settings

logger = logging.getLogger(__name__)


class ClinicalOpsOutboxService:
    """
    Service for sending messages to ClinicalOps outbox (service_ops.send_clinicalops)
    """
    
    @staticmethod
    def send_case_ready_for_review(
        db: Session,
        packet: PacketDB,
        packet_document: PacketDocumentDB,
        created_by: Optional[str] = None
    ) -> SendClinicalOpsDB:
        """
        Send CASE_READY_FOR_REVIEW message to ClinicalOps
        
        This is called when ServiceOps approves a packet and sends it to ClinicalOps for review.
        
        Args:
            db: Database session
            packet: PacketDB instance
            packet_document: PacketDocumentDB instance (primary document)
            created_by: User email who triggered the action
            
        Returns:
            SendClinicalOpsDB instance (already committed)
        
        Raises:
            ValueError: If packet has field validation errors
        """
        # Check for field validation errors before allowing submission
        if hasattr(packet, 'has_field_validation_errors') and packet.has_field_validation_errors:
            # Get detailed error messages for better error reporting
            from app.services.validation_persistence import get_field_validation_errors
            validation_data = get_field_validation_errors(packet.packet_id, db)
            field_errors = validation_data.get('field_errors', {}) if validation_data else {}
            
            error_summary = []
            for field, errors in field_errors.items():
                error_summary.append(f"{field}: {', '.join(errors)}")
            
            error_message = (
                f"Cannot submit to ClinicalOps: Field validation errors exist. "
                f"Please fix errors first. Errors: {'; '.join(error_summary)}"
            )
            
            logger.error(
                f"Blocked ClinicalOps submission for packet {packet.external_id}: {error_message}"
            )
            
            raise ValueError(error_message)
        # Get validation summary (HETS and PECOS)
        hets_validation = db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == packet.packet_id,
            PacketValidationDB.validation_type == 'HETS',
            PacketValidationDB.is_active == True,
            PacketValidationDB.is_passed.isnot(None)
        ).order_by(PacketValidationDB.validated_at.desc()).first()
        
        pecos_validation = db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == packet.packet_id,
            PacketValidationDB.validation_type == 'PECOS',
            PacketValidationDB.is_active == True,
            PacketValidationDB.is_passed.isnot(None)
        ).order_by(PacketValidationDB.validated_at.desc()).first()
        
        # Build validation summary
        validation_summary = {
            "hets": {
                "is_passed": hets_validation.is_passed if hets_validation else None,
                "validation_status": hets_validation.validation_status if hets_validation else None,
                "validated_by": hets_validation.validated_by if hets_validation else None,
                "validated_at": hets_validation.validated_at.isoformat() if hets_validation and hets_validation.validated_at else None
            } if hets_validation else None,
            "pecos": {
                "is_passed": pecos_validation.is_passed if pecos_validation else None,
                "validation_status": pecos_validation.validation_status if pecos_validation else None,
                "validated_by": pecos_validation.validated_by if pecos_validation else None,
                "validated_at": pecos_validation.validated_at.isoformat() if pecos_validation and pecos_validation.validated_at else None
            } if pecos_validation else None
        }
        
        # Get extracted fields (prioritize updated_extracted_fields over extracted_fields)
        extracted_fields = packet_document.updated_extracted_fields or packet_document.extracted_fields or {}
        
        # Resolve consolidated blob path to URL if available
        consolidated_blob_url = None
        consolidated_blob_path = None
        if packet_document.consolidated_blob_path:
            try:
                blob_client = BlobStorageClient(
                    storage_account_url=settings.storage_account_url,
                    container_name=settings.processing_container_name,
                    connection_string=settings.azure_storage_connection_string
                )
                consolidated_blob_url = blob_client.resolve_blob_url(
                    packet_document.consolidated_blob_path,
                    container_name=settings.processing_container_name
                )
                consolidated_blob_path = packet_document.consolidated_blob_path
            except Exception as e:
                logger.warning(
                    f"Failed to resolve consolidated blob URL for packet_id={packet.packet_id}: {e}"
                )
                # Still include the path even if URL resolution fails
                consolidated_blob_path = packet_document.consolidated_blob_path
        
        # Build payload
        payload = {
            "message_type": "CASE_READY_FOR_REVIEW",
            "decision_tracking_id": str(packet.decision_tracking_id),
            "packet_id": packet.external_id,
            "case_id": packet.case_id,  # Portal packet_id or ESMD transaction_id
            "packet_data": {
                "beneficiary_name": packet.beneficiary_name,
                "beneficiary_mbi": packet.beneficiary_mbi,
                "provider_name": packet.provider_name,
                "provider_npi": packet.provider_npi,
                "provider_fax": packet.provider_fax,
                "service_type": packet.service_type,
                "hcpcs": packet.hcpcs,
                "submission_type": packet.submission_type,
                "received_date": packet.received_date.isoformat() if packet.received_date else None,
                "due_date": packet.due_date.isoformat() if packet.due_date else None,
                "channel_type_id": packet.channel_type_id  # 1=Portal, 2=Fax, 3=ESMD
            },
            "validation_summary": validation_summary,
            "extracted_fields": extracted_fields,
            "document_metadata": {
                "document_id": packet_document.external_id,
                "document_type_id": packet_document.document_type_id,
                "file_name": packet_document.file_name,
                "page_count": packet_document.page_count,
                "coversheet_page_number": packet_document.coversheet_page_number,
                "part_type": packet_document.part_type,
                "consolidated_blob_path": consolidated_blob_path,  # Relative blob path
                "consolidated_blob_url": consolidated_blob_url  # Full absolute URL
            },
            "sent_at": datetime.utcnow().isoformat(),
            "sent_by": created_by
        }
        
        # Check if this is a retry (previous record was rejected)
        # Find the most recent rejected record for this decision_tracking_id
        previous_rejected = db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.decision_tracking_id == str(packet.decision_tracking_id),
            SendClinicalOpsDB.is_picked == False,
            SendClinicalOpsDB.is_deleted == False
        ).order_by(SendClinicalOpsDB.created_at.desc()).first()
        
        retry_count = 0
        if previous_rejected:
            retry_count = (previous_rejected.retry_count or 0) + 1
            
            # Check max retries (prevent infinite loops)
            MAX_RETRIES = 3
            if retry_count > MAX_RETRIES:
                raise ValueError(
                    f"Maximum retry count ({MAX_RETRIES}) exceeded for "
                    f"decision_tracking_id={packet.decision_tracking_id}. "
                    f"Please dismiss this packet instead of resending to ClinicalOps."
                )
            
            logger.info(
                f"Retry attempt {retry_count} for decision_tracking_id={packet.decision_tracking_id}. "
                f"Previous rejection reason: {previous_rejected.error_reason}"
            )
        
        # Set message_status_id based on service_ops.message_status table:
        # 1 = INGESTED (message ready for ClinicalOps to consume)
        # 2 = VALIDATED
        # 3 = SENT
        # 4 = ERROR
        # For new outbox messages, use INGESTED (1) - ready for ClinicalOps to poll and consume
        message_status_id = 1  # INGESTED - message ready for ClinicalOps
        
        # Create outbox record
        outbox_record = SendClinicalOpsDB(
            decision_tracking_id=str(packet.decision_tracking_id),
            payload=payload,
            message_status_id=message_status_id,
            audit_user=created_by,
            audit_timestamp=datetime.utcnow(),
            retry_count=retry_count,
            is_picked=None,  # Reset to NULL for new attempt
            error_reason=None,  # Clear previous error
            is_looped_back_to_validation=False  # Reset for new attempt
        )
        
        db.add(outbox_record)
        db.flush()  # Get message_id
        
        logger.info(
            f"Created CASE_READY_FOR_REVIEW message for ClinicalOps: "
            f"message_id={outbox_record.message_id}, "
            f"decision_tracking_id={packet.decision_tracking_id}, "
            f"packet_id={packet.external_id}"
        )
        
        return outbox_record

