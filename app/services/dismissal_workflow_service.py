"""
Dismissal Workflow Service
ServiceOps-only dismissal workflow: generates letter and ESMD payload
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.models.send_integration_db import SendIntegrationDB
import json
import uuid as uuid_lib
import hashlib

logger = logging.getLogger(__name__)


class DismissalWorkflowService:
    """
    ServiceOps-only dismissal workflow
    
    Handles:
    1. Dismissal letter generation
    2. ESMD payload generation (dismissal decision)
    3. Writing to integration outbox
    4. Updating packet_decision with letter metadata
    """
    
    @staticmethod
    def generate_dismissal_letter(
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        packet_document: PacketDocumentDB,
        db: Session
    ) -> Dict[str, Any]:
        """
        Generate dismissal letter via LetterGen API
        
        If LetterGen is not configured, returns a placeholder letter metadata
        to allow the workflow to continue (useful for local development/testing).
        
        Args:
            packet: PacketDB record
            packet_decision: PacketDecisionDB record with dismissal details
            packet_document: PacketDocumentDB record
            db: Database session
            
        Returns:
            Dictionary with letter metadata from LetterGen API:
            {
                "blob_url": "...",
                "filename": "...",
                "file_size_bytes": ...,
                "template_used": "...",
                "generated_at": "...",
                "inbound_json_blob_url": "...",
                "inbound_metadata_blob_url": "..."
            }
            Or placeholder metadata if LetterGen is not configured.
        """
        from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
        from app.config.settings import settings
        
        logger.info(
            f"Generating dismissal letter via LetterGen API for packet_id={packet.packet_id} | "
            f"denial_reason={packet_decision.denial_reason}"
        )
        
        # Check if LetterGen is configured
        if not settings.lettergen_base_url:
            logger.warning(
                f"LETTERGEN_BASE_URL not configured. Using placeholder letter metadata for packet_id={packet.packet_id}. "
                f"This allows the dismissal workflow to continue, but no actual letter will be generated."
            )
            
            # Return placeholder letter metadata
            return {
                "blob_url": None,
                "filename": f"dismissal_letter_{packet.external_id}_placeholder.pdf",
                "file_size_bytes": 0,
                "template_used": "dismissal_placeholder",
                "generated_at": datetime.utcnow().isoformat(),
                "inbound_json_blob_url": None,
                "inbound_metadata_blob_url": None,
                "placeholder": True,
                "note": "Letter generation skipped - LETTERGEN_BASE_URL not configured"
            }
        
        # Generate letter via LetterGen API
        letter_service = LetterGenerationService(db)
        try:
            letter_metadata = letter_service.generate_letter(
                packet=packet,
                packet_decision=packet_decision,
                packet_document=packet_document,
                letter_type='dismissal'
            )
            
            logger.info(
                f"Successfully generated dismissal letter for packet_id={packet.packet_id} | "
                f"blob_url={letter_metadata.get('blob_url')}"
            )
            
            return letter_metadata
            
        except LetterGenerationError as e:
            logger.warning(
                f"LetterGen API error during dismissal letter generation for packet_id={packet.packet_id}: {e}. "
                f"Returning PENDING status to allow dismissal workflow to continue. Letter can be uploaded manually."
            )
            # Return PENDING status instead of raising - allows dismissal to proceed
            return {
                "blob_url": None,
                "filename": f"dismissal_letter_{packet.external_id}_pending.pdf",
                "file_size_bytes": 0,
                "template_used": "dismissal_pending",
                "generated_at": datetime.utcnow().isoformat(),
                "inbound_json_blob_url": None,
                "inbound_metadata_blob_url": None,
                "pending": True,
                "letter_status": "PENDING",
                "error": {
                    "code": "LETTER_GENERATION_ERROR",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                },
                "note": f"Letter generation failed: {str(e)}. Letter can be uploaded manually."
            }
        except Exception as e:
            logger.warning(
                f"Unexpected error during dismissal letter generation for packet_id={packet.packet_id}: {e}. "
                f"Returning PENDING status to allow dismissal workflow to continue. Letter can be uploaded manually.",
                exc_info=True
            )
            # Return PENDING status instead of raising - allows dismissal to proceed
            return {
                "blob_url": None,
                "filename": f"dismissal_letter_{packet.external_id}_pending.pdf",
                "file_size_bytes": 0,
                "template_used": "dismissal_pending",
                "generated_at": datetime.utcnow().isoformat(),
                "inbound_json_blob_url": None,
                "inbound_metadata_blob_url": None,
                "pending": True,
                "letter_status": "PENDING",
                "error": {
                    "code": "UNEXPECTED_ERROR",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                },
                "note": f"Letter generation failed: {str(e)}. Letter can be uploaded manually."
            }
    
    @staticmethod
    def _format_denial_reason(denial_reason: str, denial_details: Optional[Dict[str, Any]]) -> str:
        """Format denial reason and details into human-readable text"""
        if not denial_details:
            denial_details = {}
        
        if denial_reason == 'MISSING_FIELDS':
            missing_fields = denial_details.get('missingFields', [])
            if missing_fields:
                return f"Missing required fields: {', '.join(missing_fields)}"
            return "Missing required fields"
        
        elif denial_reason == 'INVALID_PECOS':
            explanation = denial_details.get('explanation', '')
            pecos_ref = denial_details.get('pecosReference', '')
            if pecos_ref:
                return f"Invalid PECOS response: {explanation} (Reference: {pecos_ref})"
            return f"Invalid PECOS response: {explanation}"
        
        elif denial_reason == 'INVALID_HETS':
            explanation = denial_details.get('explanation', '')
            hets_id = denial_details.get('hetsRequestId', '')
            if hets_id:
                return f"Invalid HETS response: {explanation} (Request ID: {hets_id})"
            return f"Invalid HETS response: {explanation}"
        
        elif denial_reason == 'PROCEDURE_NOT_SUPPORTED':
            procedure_code = denial_details.get('procedureCode', '')
            return f"Procedure code {procedure_code} is not supported"
        
        elif denial_reason == 'NO_MEDICAL_RECORDS':
            reason = denial_details.get('reason', '')
            return f"No medical records provided: {reason}"
        
        elif denial_reason == 'OTHER':
            reason = denial_details.get('reason', '')
            return reason if reason else "Other reason (see notes)"
        
        return "Dismissal reason not specified"
    
    @staticmethod
    def _generate_letter_template(
        packet: PacketDB,
        provider_address_str: str,
        beneficiary_dob: str,
        diagnosis_codes: list,
        denial_reason_text: str,
        date: datetime
    ) -> str:
        """Generate dismissal letter content from template"""
        
        date_str = date.strftime("%B %d, %Y")
        
        letter = f"""[Organization Letterhead]

PRIOR AUTHORIZATION DISMISSAL

Date: {date_str}
Case ID: {packet.external_id}

To: {packet.provider_name}
    {provider_address_str if provider_address_str else 'Address not available'}
    Fax: {packet.provider_fax or 'N/A'}

Re: Prior Authorization Request - DISMISSED
    Patient: {packet.beneficiary_name}
    Member ID: {packet.beneficiary_mbi}
    Service: {packet.service_type}
    HCPCS: {packet.hcpcs or 'N/A'}

Dear Provider,

After careful review of the submitted documentation, we regret to inform you that the prior authorization request for the above-referenced patient has been DISMISSED.

SERVICE DETAILS:
- HCPCS Code: {packet.hcpcs or 'N/A'}
- Service Description: {packet.service_type}
- Diagnosis Code(s): {', '.join(diagnosis_codes) if diagnosis_codes else 'N/A'}
- Date of Service Requested: {beneficiary_dob or 'N/A'}

REASON FOR DISMISSAL:
{denial_reason_text}

DOCUMENTATION REVIEWED:
- Prior Authorization Request Form
- Clinical notes and medical records
- Supporting documentation

NEXT STEPS - APPEAL RIGHTS:
You have the right to appeal this determination. To initiate an appeal:

1. Submit additional documentation addressing the deficiencies noted above
2. Include a written statement explaining why the service meets medical necessity criteria
3. Reference Case ID {packet.external_id} in all correspondence
4. Submit within 60 days of this notice

Appeals should be submitted to:
WISeR Clinical Appeals
P.O. Box XXXXX
Newark, NJ 07102
Fax: 1-800-XXX-XXXX

ADDITIONAL INFORMATION:
You may resubmit a new prior authorization request if additional documentation becomes available that addresses the deficiencies noted above.

If you have questions regarding this determination, please contact our clinical review department at 1-800-XXX-XXXX, reference Case ID {packet.external_id}.

Sincerely,

ServiceOps Review Team
WISeR Program

This determination was made in accordance with CMS guidelines and applicable Local Coverage Determinations.
"""
        return letter
    
    @staticmethod
    def process_dismissal(
        db: Session,
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        created_by: str
    ) -> Dict[str, Any]:
        """
        Process dismissal workflow end-to-end:
        1. Generate dismissal letter
        2. Generate ESMD payload
        3. Write to integration outbox
        4. Update packet_decision
        
        Args:
            db: Database session
            packet: PacketDB record
            packet_decision: PacketDecisionDB record (already created)
            created_by: User who created the dismissal
            
        Returns:
            Dictionary with letter metadata and outbox message_id
        """
        logger.info(
            f"Processing dismissal workflow for packet_id={packet.packet_id} | "
            f"decision_id={packet_decision.packet_decision_id}"
        )
        
        # Get packet document
        packet_document = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not packet_document:
            raise ValueError(f"No packet_document found for packet_id={packet.packet_id}")
        
        # 1. Update packet status to "Generate Decision Letter - Pending"
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Generate Decision Letter - Pending"
        )
        
        # 2. Generate dismissal letter
        letter_metadata = DismissalWorkflowService.generate_dismissal_letter(
            packet=packet,
            packet_decision=packet_decision,
            packet_document=packet_document,
            db=db
        )
        
        # 3. Set decision outcome for dismissal (no ESMD payload for dismissals)
        # Dismissals are early-stage rejections and do NOT go through ESMD integration
        # ESMD payloads are only for AFFIRM/NON_AFFIRM decisions after clinical review
        packet_decision.decision_outcome = 'DISMISSAL'
        packet_decision.decision_subtype = None  # Dismissal doesn't have DIRECT_PA/STANDARD_PA
        packet_decision.part_type = packet_document.part_type or 'B'  # Default to B
        
        # Dismissals do NOT generate ESMD payloads - they are handled differently
        # No ESMD payload generation or send_integration write for dismissals
        logger.info(
            f"Skipping ESMD payload generation for dismissal packet_id={packet.packet_id}. "
            f"Dismissals do not go through ESMD integration."
        )
        
        # 4. Update packet_decision (no ESMD fields for dismissals)
        packet_decision.esmd_request_status = None  # No ESMD for dismissals
        packet_decision.esmd_request_payload = None  # No ESMD payload
        packet_decision.esmd_attempt_count = None
        packet_decision.esmd_last_sent_at = None
        
        # 5. Store letter metadata
        packet_decision.letter_owner = 'SERVICE_OPS'
        
        # Determine letter status based on metadata
        # If letter_metadata has "pending" or "placeholder" flag, set status to PENDING
        # Otherwise, set to READY (successfully generated)
        if letter_metadata.get('pending') or letter_metadata.get('placeholder'):
            packet_decision.letter_status = 'PENDING'
            logger.info(
                f"Letter status set to PENDING for packet_id={packet.packet_id}. "
                f"Letter can be uploaded manually via upload endpoint."
            )
        else:
            packet_decision.letter_status = 'READY'
        
        packet_decision.letter_package = letter_metadata  # Store full LetterGen API response or placeholder
        packet_decision.letter_generated_at = datetime.utcnow()
        
        # Update packet status based on letter status
        if packet_decision.letter_status == 'PENDING':
            # Keep status as "Generate Decision Letter - Pending" if letter is pending
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Generate Decision Letter - Pending"
            )
            logger.info(
                f"Packet status kept as 'Generate Decision Letter - Pending' for packet_id={packet.packet_id}. "
                f"Waiting for manual letter upload."
            )
        else:
            # Update to "Generate Decision Letter - Complete" if letter is ready
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Generate Decision Letter - Complete"
            )
        
        # No ESMD payload history for dismissals
        packet_decision.esmd_request_payload_history = None
        
        # 6. Send letter to Integration outbox ONLY if letter is READY (not PENDING)
        letter_outbox_record = None
        if packet_decision.letter_status == 'READY':
            letter_structured_payload = {
                "message_type": "LETTER_PACKAGE",
                "decision_tracking_id": str(packet.decision_tracking_id),
                "letter_package": letter_metadata,
                "medical_documents": [],
                "packet_id": packet.packet_id,
                "external_id": packet.external_id,
                "letter_type": "dismissal",
                "attempt_count": 1,
                "payload_version": 1,
                "correlation_id": str(uuid_lib.uuid4()),
                "created_at": datetime.utcnow().isoformat(),
                "created_by": created_by
            }
            
            # Generate payload hash for letter
            letter_payload_json = json.dumps(letter_structured_payload, sort_keys=True)
            letter_payload_hash = hashlib.sha256(letter_payload_json.encode('utf-8')).hexdigest()
            letter_structured_payload["payload_hash"] = letter_payload_hash
            
            letter_outbox_record = SendIntegrationDB(
                decision_tracking_id=packet.decision_tracking_id,
                payload=letter_structured_payload,
                message_status_id=1,  # INGESTED - ready for Integration to poll
                correlation_id=uuid_lib.UUID(letter_structured_payload["correlation_id"]),
                attempt_count=1,
                payload_hash=letter_payload_hash,
                payload_version=1,
                audit_user=created_by,
                audit_timestamp=datetime.utcnow()
            )
            db.add(letter_outbox_record)
            db.flush()
            
            packet_decision.letter_sent_to_integration_at = datetime.utcnow()
            packet_decision.letter_status = 'SENT'
            
            # Update packet status to "Send Decision Letter - Pending" first
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Send Decision Letter - Pending"
            )
            
            # Then update to "Send Decision Letter - Complete"
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Send Decision Letter - Complete"
            )
            
            # Update operational decision to DISMISSAL_COMPLETE
            from app.services.decisions_service import DecisionsService
            
            DecisionsService.update_operational_decision(
                db=db,
                packet_id=packet.packet_id,
                new_operational_decision='DISMISSAL_COMPLETE',
                created_by=created_by
            )
            
            # Update final status
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Dismissal Complete"
            )
            
            db.commit()
            db.refresh(letter_outbox_record)
            
            logger.info(
                f"Dismissal workflow completed for packet_id={packet.packet_id} | "
                f"letter_message_id={letter_outbox_record.message_id} | "
                f"letter_generated=True | "
                f"Status updated to 'Dismissal Complete' | "
                f"Operational decision updated to DISMISSAL_COMPLETE | "
                f"No ESMD payload generated (dismissals do not go through ESMD)"
            )
        else:
            # Letter is PENDING - update status to Dismissal (waiting for letter upload)
            from app.services.decisions_service import DecisionsService
            
            DecisionsService.update_operational_decision(
                db=db,
                packet_id=packet.packet_id,
                new_operational_decision='DISMISSAL',
                created_by=created_by
            )
            
            # Update status to "Dismissal" (not complete yet - waiting for letter)
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Dismissal"
            )
            
            db.commit()
            
            logger.info(
                f"Dismissal workflow completed (letter pending) for packet_id={packet.packet_id} | "
                f"letter_status=PENDING | "
                f"Status updated to 'Dismissal' | "
                f"Operational decision updated to DISMISSAL | "
                f"Waiting for manual letter upload"
            )
        
        return {
            "letter_metadata": letter_metadata,
            "letter_outbox_message_id": letter_outbox_record.message_id if letter_outbox_record else None,
            "letter_status": packet_decision.letter_status,
            "esmd_payload": None  # No ESMD payload for dismissals
        }

