"""
UTN Event Handlers
Handle UTN_SUCCESS (message_type_id=2) and UTN_FAIL (message_type_id=3) messages
from integration.send_serviceops
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB

logger = logging.getLogger(__name__)


class UtnSuccessHandler:
    """
    Handler for UTN_SUCCESS messages (message_type_id = 2)
    
    Actions:
    1. Parse UTN success payload
    2. Update packet_decision with UTN fields
    3. Trigger letter generation if decision already received
"""
    
    @staticmethod
    async def handle(db: Session, message: Dict[str, Any]) -> None:
        """
        Handle UTN_SUCCESS message
        
        Args:
            db: Database session
            message: Message dictionary with message_id, decision_tracking_id, payload, created_at
        """
        message_id = message['message_id']
        decision_tracking_id = message['decision_tracking_id']
        payload = message['payload']
        
        logger.info(
            f"Processing UTN_SUCCESS message {message_id} | "
            f"decision_tracking_id={decision_tracking_id}"
        )
        
        # 1. Extract UTN data from payload
        utn = payload.get('unique_tracking_number')
        esmd_transaction_id = payload.get('esmd_transaction_id')
        unique_id = payload.get('unique_id')
        destination_type = payload.get('destination_type')
        decision_package = payload.get('decision_package', {})
        
        if not utn:
            raise ValueError(
                f"UTN_SUCCESS message {message_id} missing 'unique_tracking_number' in payload"
            )
        
        # 2. Find packet
        packet = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id == decision_tracking_id
        ).first()
        
        if not packet:
            raise ValueError(
                f"Packet not found for decision_tracking_id={decision_tracking_id}"
            )
        
        # 3. Find active packet_decision (most recent active decision)
        packet_decision = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == packet.packet_id,
            PacketDecisionDB.is_active == True
        ).order_by(PacketDecisionDB.created_at.desc()).first()
        
        if not packet_decision:
            logger.warning(
                f"PacketDecision not found for packet_id={packet.packet_id}. "
                f"UTN_SUCCESS received but no decision record exists. "
                f"This may be a dismissal case (ServiceOps-only)."
            )
            # For dismissal cases, we might not have a packet_decision yet
            # In that case, we'll just log and return (dismissal workflow handles UTN separately)
            return
        
        # 4. Update packet_decision with UTN fields
        packet_decision.utn = utn
        packet_decision.utn_status = 'SUCCESS'
        packet_decision.utn_received_at = datetime.utcnow()
        
        # Update ESMD status if it was SENT
        if packet_decision.esmd_request_status == 'SENT':
            packet_decision.esmd_request_status = 'ACKED'
        
        # Update packet status
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="UTN Received"
        )
        
        db.flush()
        
        logger.info(
            f"Updated packet_decision_id={packet_decision.packet_decision_id} with UTN={utn} | "
            f"esmd_transaction_id={esmd_transaction_id} | "
            f"Status updated to 'UTN Received'"
        )
        
        # 5. Trigger letter generation if decision already received
        # For AFFIRM/NON_AFFIRM: Decision + UTN = prerequisites met
        # For DISMISSAL: No UTN required (letter already generated)
        if packet_decision.decision_outcome in ['AFFIRM', 'NON_AFFIRM']:
            # Check if letter already generated
            if packet_decision.letter_status not in ['READY', 'SENT']:
                # Trigger letter generation
                logger.info(
                    f"UTN received and decision exists for packet_id={packet.packet_id}. "
                    f"Triggering letter generation."
                )
                await UtnSuccessHandler._trigger_letter_generation(
                    db=db,
                    packet=packet,
                    packet_decision=packet_decision
                )
            else:
                logger.info(
                    f"Letter already generated for packet_id={packet.packet_id}, "
                    f"letter_status={packet_decision.letter_status}"
                )
        elif packet_decision.decision_outcome == 'DISMISSAL':
            # Dismissal doesn't require UTN, letter should already be generated
            logger.info(
                f"Dismissal case - UTN received but letter should already be generated. "
                f"Current letter_status={packet_decision.letter_status}"
            )
    
    @staticmethod
    async def _trigger_letter_generation(
        db: Session,
        packet: PacketDB,
        packet_decision: PacketDecisionDB
    ) -> None:
        """
        Trigger letter generation after UTN received
        
        Args:
            db: Database session
            packet: PacketDB record
            packet_decision: PacketDecisionDB record
        """
        from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
        from app.models.document_db import PacketDocumentDB
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        # Get packet document
        packet_document = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not packet_document:
            logger.error(f"No packet_document found for packet_id={packet.packet_id}")
            return
        
        # Determine letter type
        letter_type_map = {
            'AFFIRM': 'affirmation',
            'NON_AFFIRM': 'non-affirmation'
        }
        letter_type = letter_type_map.get(packet_decision.decision_outcome)
        
        if not letter_type:
            logger.error(
                f"Unknown decision_outcome for letter generation: {packet_decision.decision_outcome} | "
                f"packet_id={packet.packet_id}"
            )
            return
        
        # Generate letter
        letter_service = LetterGenerationService(db)
        try:
            letter_metadata = letter_service.generate_letter(
                packet=packet,
                packet_decision=packet_decision,
                packet_document=packet_document,
                letter_type=letter_type
            )
            
            # Update packet_decision and packet status
            
            packet_decision.letter_status = 'READY'
            packet_decision.letter_package = letter_metadata
            packet_decision.letter_generated_at = datetime.utcnow()
            
            # Update packet status to "Generate Decision Letter - Complete"
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Generate Decision Letter - Complete"
            )
            
            db.commit()
            
            logger.info(
                f"Successfully generated {letter_type} letter for packet_id={packet.packet_id} | "
                f"blob_url={letter_metadata.get('blob_url')} | "
                f"Status updated to 'Generate Decision Letter - Complete'"
            )
            
            # Send to Integration outbox
            await UtnSuccessHandler._send_letter_to_integration(db, packet, packet_decision)
            
        except LetterGenerationError as e:
            logger.error(
                f"Letter generation failed for packet_id={packet.packet_id}: {e}",
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
            # Update packet status to indicate letter generation failed
            # Keep status as "Generate Decision Letter - Pending" but with FAILED letter_status
            # This allows UI to show notification and enable manual upload
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Generate Decision Letter - Pending"  # Keep same status, letter_status shows failure
            )
            db.commit()
        except Exception as e:
            logger.error(
                f"Unexpected error during letter generation for packet_id={packet.packet_id}: {e}",
                exc_info=True
            )
            from app.services.workflow_orchestrator import WorkflowOrchestratorService
            packet_decision.letter_status = 'FAILED'
            packet_decision.letter_package = {
                "error": {
                    "code": "UNEXPECTED_ERROR",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
            # Update packet status to indicate letter generation failed
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Generate Decision Letter - Pending"  # Keep same status, letter_status shows failure
            )
            db.commit()
    
    @staticmethod
    async def _send_letter_to_integration(
        db: Session,
        packet: PacketDB,
        packet_decision: PacketDecisionDB
    ) -> None:
        """
        Send letter package to Integration outbox (service_ops.send_integration)
        
        Args:
            db: Database session
            packet: PacketDB record
            packet_decision: PacketDecisionDB record
        """
        from app.models.send_integration_db import SendIntegrationDB
        import json
        import uuid as uuid_lib
        import hashlib
        
        letter_package = packet_decision.letter_package or {}
        letter_medical_docs = packet_decision.letter_medical_docs or []
        
        # Build structured payload with message_type
        structured_payload = {
            "message_type": "LETTER_PACKAGE",
            "decision_tracking_id": str(packet.decision_tracking_id),
            "letter_package": letter_package,
            "medical_documents": letter_medical_docs,
            "packet_id": packet.packet_id,
            "external_id": packet.external_id,
            "letter_type": packet_decision.decision_outcome.lower() if packet_decision.decision_outcome else None,
            "attempt_count": 1,
            "payload_version": 1,
            "correlation_id": str(uuid_lib.uuid4()),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": "SYSTEM"
        }
        
        # Generate payload hash
        payload_json = json.dumps(structured_payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode('utf-8')).hexdigest()
        structured_payload["payload_hash"] = payload_hash
        
        # Insert into service_ops.send_integration
        outbox_record = SendIntegrationDB(
            decision_tracking_id=packet.decision_tracking_id,
            payload=structured_payload,
            message_status_id=1,  # INGESTED - ready for Integration to poll
            correlation_id=uuid_lib.UUID(structured_payload["correlation_id"]),
            attempt_count=1,
            payload_hash=payload_hash,
            payload_version=1,
            audit_user="SYSTEM",
            audit_timestamp=datetime.utcnow()
        )
        db.add(outbox_record)
        db.flush()
        
        packet_decision.letter_sent_to_integration_at = datetime.utcnow()
        packet_decision.letter_status = 'SENT'
        
        # Update packet status
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        from app.services.decisions_service import DecisionsService
        
        # Update to "Send Decision Letter - Pending" first
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
        
        # Update operational decision to DECISION_COMPLETE (final update)
        active_decision = WorkflowOrchestratorService.get_active_decision(db, packet.packet_id)
        if active_decision and active_decision.operational_decision == 'PENDING':
            DecisionsService.update_operational_decision(
                db=db,
                packet_id=packet.packet_id,
                new_operational_decision='DECISION_COMPLETE',
                created_by='SYSTEM'
            )
        
        # Update final status
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Decision Complete"
        )
        
        db.commit()
        
        logger.info(
            f"Sent letter package to service_ops.send_integration | "
            f"message_id={outbox_record.message_id} | "
            f"decision_tracking_id={packet.decision_tracking_id} | "
            f"Status updated to 'Decision Complete' | "
            f"Operational decision updated to DECISION_COMPLETE"
        )


class UtnFailHandler:
    """
    Handler for UTN_FAIL messages (message_type_id = 3)
    
    Actions:
    1. Parse UTN fail payload
    2. Update packet_decision with failure fields
    3. Set requires_utn_fix = true (for UI remediation)
    4. DO NOT write to send_clinicalops (ServiceOps-only remediation)
    """
    
    @staticmethod
    def handle(db: Session, message: Dict[str, Any]) -> None:
        """
        Handle UTN_FAIL message
        
        Args:
            db: Database session
            message: Message dictionary with message_id, decision_tracking_id, payload, created_at
        """
        message_id = message['message_id']
        decision_tracking_id = message['decision_tracking_id']
        payload = message['payload']
        
        logger.info(
            f"Processing UTN_FAIL message {message_id} | "
            f"decision_tracking_id={decision_tracking_id}"
        )
        
        # 1. Extract UTN fail data from payload
        error_code = payload.get('error_code')
        error_description = payload.get('error_description')
        action_required = payload.get('action_required')
        part_type = payload.get('part_type')
        esmd_transaction_id = payload.get('esmd_transaction_id')
        unique_id = payload.get('unique_id')
        provider = payload.get('provider', {})
        beneficiary = payload.get('beneficiary', {})
        procedure_code = payload.get('procedure_code')
        upload_id = payload.get('upload_id')
        
        if not error_code:
            logger.warning(
                f"UTN_FAIL message {message_id} missing 'error_code' in payload"
            )
        
        # 2. Find packet
        packet = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id == decision_tracking_id
        ).first()
        
        if not packet:
            raise ValueError(
                f"Packet not found for decision_tracking_id={decision_tracking_id}"
            )
        
        # 3. Find or create packet_decision
        # For UTN_FAIL, we might not have a decision yet (could be a dismissal case)
        packet_decision = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == packet.packet_id
        ).first()
        
        if not packet_decision:
            logger.warning(
                f"PacketDecision not found for packet_id={packet.packet_id}. "
                f"Creating minimal decision record for UTN_FAIL remediation."
            )
            
            # Create minimal decision record for UTN_FAIL
            from app.models.document_db import PacketDocumentDB
            first_doc = db.query(PacketDocumentDB).filter(
                PacketDocumentDB.packet_id == packet.packet_id
            ).first()
            
            if not first_doc:
                raise ValueError(
                    f"No documents found for packet_id={packet.packet_id}"
                )
            
            packet_decision = PacketDecisionDB(
                packet_id=packet.packet_id,
                packet_document_id=first_doc.packet_document_id,
                decision_type='APPROVE',  # Placeholder - will be updated when decision is made
                decision_outcome=None,  # Unknown at this point
                part_type=part_type,
                letter_owner=None,  # Unknown at this point
                created_by='SYSTEM',
                created_at=datetime.utcnow()
            )
            db.add(packet_decision)
            db.flush()
        
        # 4. Update packet_decision with UTN fail fields
        packet_decision.utn_status = 'FAILED'
        packet_decision.utn_received_at = datetime.utcnow()
        packet_decision.utn_fail_payload = payload  # Store full payload for debugging
        packet_decision.utn_action_required = action_required
        packet_decision.requires_utn_fix = True  # Flag for UI remediation
        
        # Update ESMD status
        if packet_decision.esmd_request_status == 'SENT':
            packet_decision.esmd_request_status = 'FAILED'
        
        packet_decision.esmd_last_error = f"{error_code}: {error_description}"
        
        # Update part_type if provided
        if part_type:
            packet_decision.part_type = part_type
        
        # 5. Loop back to Validation status (remediation workflow)
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        # Packet was already queried at line 394, reuse it
        # packet = db.query(PacketDB).filter(...).first() - already have packet from step 2
        
        if packet:
            # Update status to Validation (loops back)
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Validation",
                validation_status="Pending - Validation"  # Restart validation
            )
            
            logger.info(
                f"UTN_FAIL: Looped packet_id={packet.packet_id} back to Validation status"
            )
        
        db.flush()
        
        logger.info(
            f"Updated packet_decision_id={packet_decision.packet_decision_id} with UTN_FAIL | "
            f"error_code={error_code} | action_required={action_required} | "
            f"Status looped back to Validation"
        )
        
        # 6. DO NOT write to send_clinicalops
        # UTN_FAIL is handled entirely by ServiceOps remediation workflow
        logger.info(
            f"UTN_FAIL for decision_tracking_id={decision_tracking_id} requires ServiceOps remediation. "
            f"Not forwarding to ClinicalOps."
        )

