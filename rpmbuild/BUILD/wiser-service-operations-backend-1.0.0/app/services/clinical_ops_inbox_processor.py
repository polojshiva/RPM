"""
ClinicalOps Inbox Processor
Polls service_ops.send_serviceops for Phase 1 records (clinical decision made)
Automatically triggers JSON Generator Phase 2, then processes generated payloads

Flow:
1. Polls for Phase 1 records (clinical_ops_decision_json IS NOT NULL, json_sent_to_integration IS NULL)
2. Calls JSON Generator Phase 2 endpoint
3. Processes Phase 2 results (json_sent_to_integration IS NOT NULL)
"""
import asyncio
import logging
import uuid
import httpx
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_decision_db import PacketDecisionDB
from app.config import settings

logger = logging.getLogger(__name__)


class ClinicalOpsInboxProcessor:
    """
    Background service that polls service_ops.send_serviceops
    
    Flow:
    1. Polls for Phase 1 records (clinical_ops_decision_json IS NOT NULL, json_sent_to_integration IS NULL)
    2. Calls JSON Generator Phase 2 endpoint
    3. Processes Phase 2 results (json_sent_to_integration IS NOT NULL)
    
    All workers run the processor. Database-level locking prevents duplicate processing.
    """
    
    def __init__(self):
        self.is_running = False
        self.poll_task: Optional[asyncio.Task] = None
        self.worker_id = f"clinical-ops-worker-{uuid.uuid4()}"
        self.poll_interval_seconds = getattr(settings, 'clinical_ops_poll_interval_seconds', 120)  # Default 120s (2 min)
        self.batch_size = getattr(settings, 'clinical_ops_poll_batch_size', 10)  # Default 10 (clinical ops is lighter load than integration inbox)
        self.processing_delay_seconds = getattr(settings, 'clinical_ops_processing_delay_seconds', 5.0)  # Delay between messages
        self.json_generator_url = getattr(settings, 'json_generator_base_url', None)
    
    async def start(self):
        """Start the ClinicalOps inbox processor background task"""
        if self.is_running:
            logger.warning("ClinicalOps inbox processor is already running")
            return
        
        if not getattr(settings, 'clinical_ops_poller_enabled', True):
            logger.info("ClinicalOps inbox processor is disabled in settings")
            return
        
        if not self.json_generator_url:
            logger.warning("JSON_GENERATOR_BASE_URL not configured - Phase 2 triggering will fail")
        
        self.is_running = True
        self.poll_task = asyncio.create_task(self._poll_loop())
        
        # Add exception handler to prevent unhandled exceptions from crashing the worker
        def handle_task_exception(task: asyncio.Task):
            """Handle unhandled exceptions in background task"""
            try:
                task.result()  # This will raise the exception if task failed
            except asyncio.CancelledError:
                # Task was cancelled - this is expected during shutdown
                pass
            except Exception as e:
                logger.error(
                    f"CRITICAL: Unhandled exception in ClinicalOps inbox processor task: {e}. "
                    f"Processor will stop but worker will continue running.",
                    exc_info=True
                )
                # Mark as not running so it doesn't try to process more
                self.is_running = False
        
        self.poll_task.add_done_callback(handle_task_exception)
        
        logger.info(
            f"✅ ClinicalOps inbox processor started (interval: {self.poll_interval_seconds}s, "
            f"batch_size: {self.batch_size}, json_generator_url: {self.json_generator_url}, "
            f"worker_id={self.worker_id})"
        )
    
    async def stop(self):
        """Stop the ClinicalOps inbox processor background task"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        
        logger.info("ClinicalOps inbox processor stopped")
    
    async def _poll_loop(self):
        """Main polling loop"""
        while self.is_running:
            try:
                await self._poll_and_process()
                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ClinicalOps inbox polling loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval_seconds)
    
    async def _poll_and_process(self):
        """Poll for new messages and process them"""
        # CRITICAL: Check connection pool before processing
        from app.services.connection_pool_monitor import should_throttle_background, log_pool_status, get_pool_usage
        log_pool_status()
        
        pool_usage = get_pool_usage()
        should_throttle = should_throttle_background()
        
        if should_throttle:
            # Pool is critical - but still process at least 1 record to prevent accumulation
            # Reduce batch size to 1 when pool is critical
            logger.warning(
                f"Connection pool CRITICAL ({pool_usage['usage_percent']:.1%}) - "
                f"reducing batch size to 1 to prevent record accumulation. "
                f"Will process at least 1 record this cycle."
            )
            # Continue but with reduced batch size (handled below)
        else:
            # Pool is healthy - use normal batch size
            pass
        
        db = SessionLocal()
        try:
            # Adjust batch size if pool is critical
            effective_batch_size = self.batch_size
            if should_throttle:
                effective_batch_size = 1  # Process only 1 record when pool is critical
                logger.info(f"Pool critical - processing only 1 record this cycle (normal batch: {self.batch_size})")
            
            # CRITICAL: Run blocking database query in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            messages = await loop.run_in_executor(
                None,
                self._poll_new_messages,
                db,
                effective_batch_size
            )
            
            if not messages:
                return
            
            logger.info(f"Found {len(messages)} new ClinicalOps message(s) (batch_size={effective_batch_size})")
            
            # CRITICAL: Process messages SEQUENTIALLY with delays to prevent connection pool exhaustion
            # This ensures we don't hold multiple DB connections simultaneously
            # BULLETPROOF: Track max created_at and message_id ONLY for consecutive successes
            # Stop tracking at first failure so watermark doesn't skip failed messages
            max_created_at = None
            max_message_id = 0
            first_failure_idx = None
            for idx, message in enumerate(messages):
                try:
                    # Process message (holds DB connection during processing)
                    await self._process_message(db, message)
                    
                    # BULLETPROOF: Only track max if we haven't hit a failure yet
                    # This ensures watermark only advances to last consecutive success
                    if first_failure_idx is None:
                        message_created_at = message['created_at']
                        if max_created_at is None or message_created_at > max_created_at:
                            max_created_at = message_created_at
                            max_message_id = message['message_id']
                        elif message_created_at == max_created_at and message['message_id'] > max_message_id:
                            max_message_id = message['message_id']
                    
                    # CRITICAL: Delay between messages to:
                    # 1. Release DB connection back to pool
                    # 2. Allow auth/user requests to get connections
                    # 3. Prevent overwhelming JSON Generator service
                    if idx < len(messages) - 1:  # Don't delay after last message
                        logger.debug(f"Delaying {self.processing_delay_seconds}s before next message...")
                        await asyncio.sleep(self.processing_delay_seconds)
                        
                except Exception as e:
                    logger.error(
                        f"Error processing ClinicalOps message {message['message_id']}: {e}",
                        exc_info=True
                    )
                    
                    # Rollback the transaction (wrap in try/except so failed rollback doesn't crash)
                    loop = asyncio.get_event_loop()
                    try:
                        await loop.run_in_executor(None, db.rollback)
                    except Exception as rollback_error:
                        logger.warning(
                            f"Failed to rollback transaction after error: {rollback_error}. "
                            f"This may indicate a connection issue."
                        )
                    
                    # Detect connection/SSL errors
                    error_str = str(e).lower()
                    is_connection_error = False
                    
                    # Check for SSL connection closed errors
                    if "ssl connection" in error_str and "closed" in error_str:
                        is_connection_error = True
                    # Check for connection closed/unexpectedly errors
                    elif "connection" in error_str and ("closed" in error_str or "unexpectedly" in error_str):
                        is_connection_error = True
                    # Check for OperationalError with connection/SSL issues
                    elif isinstance(e, OperationalError) and ("connection" in error_str or "ssl" in error_str):
                        is_connection_error = True
                    
                    if is_connection_error:
                        # Connection error: close session and stop batch processing
                        # Failed and remaining messages will be retried next cycle with fresh connection
                        logger.warning(
                            f"Connection/SSL error detected for message {message['message_id']}. "
                            f"Closing DB session and stopping batch. "
                            f"Failed message and remaining {len(messages) - idx - 1} message(s) will be retried next cycle."
                        )
                        
                        # Close session in try/except (may already be closed or in invalid state)
                        try:
                            db.close()
                        except Exception as close_error:
                            logger.warning(
                                f"Error closing DB session after connection error: {close_error}. "
                                f"Session may already be closed."
                            )
                        
                        # Break out of loop - do not process more messages with this broken session
                        break
                    else:
                        # Not a connection error: mark as failed and continue with same session
                        await loop.run_in_executor(None, self._mark_message_failed, db, message['message_id'], str(e))
                        
                        # BULLETPROOF: Record first failure index - stop tracking max after this
                        if first_failure_idx is None:
                            first_failure_idx = idx
                            logger.warning(
                                f"First failure in batch at index {idx} (message_id={message['message_id']}). "
                                f"Watermark will only advance to last consecutive success (before this failure). "
                                f"Failed message will be retried in next cycle."
                            )
                        
                        # Delay even on error to prevent rapid retry loops
                        if idx < len(messages) - 1:
                            await asyncio.sleep(self.processing_delay_seconds)
            
            # BULLETPROOF: Update watermark only if we have successful messages
            # Watermark advances only to last consecutive success (stops at first failure)
            if max_created_at and first_failure_idx is None:
                # All messages succeeded - advance watermark normally
                await loop.run_in_executor(
                    None,
                    self._update_watermark,
                    db,
                    max_created_at,
                    max_message_id
                )
                await loop.run_in_executor(None, db.commit)
                logger.info(f"Updated watermark: created_at={max_created_at}, message_id={max_message_id}")
            elif max_created_at:
                # Some messages succeeded before first failure - advance watermark to last success
                await loop.run_in_executor(
                    None,
                    self._update_watermark,
                    db,
                    max_created_at,
                    max_message_id
                )
                await loop.run_in_executor(None, db.commit)
                logger.info(
                    f"Updated watermark to last consecutive success: created_at={max_created_at}, "
                    f"message_id={max_message_id} (stopped at first failure at index {first_failure_idx})"
                )
            else:
                # All messages failed - don't advance watermark
                logger.warning(
                    f"All messages in batch failed. Watermark not advanced. "
                    f"Messages will be retried in next cycle."
                )
        except asyncio.CancelledError:
            # Handle graceful shutdown - don't close session if operation was cancelled
            logger.debug("Poll operation cancelled during shutdown")
            try:
                db.rollback()
            except Exception:
                pass  # Ignore errors during rollback on cancellation
            raise  # Re-raise to allow proper cancellation handling
        except Exception as e:
            # Log error but don't re-raise (allows finally to run)
            logger.error(f"Error in ClinicalOps inbox polling loop: {e}", exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass  # Ignore errors during rollback
        finally:
            # Safely close the session - handle cases where session is already closed or in invalid state
            # This can happen during shutdown when operations are cancelled or connection is in progress
            try:
                db.close()
            except Exception as close_error:
                # Ignore errors when closing session (e.g., session already closed, connection in progress)
                # This is non-critical and can happen during graceful shutdown
                logger.debug(f"Error closing database session (ignored during shutdown): {close_error}")
    
    def _poll_new_messages(self, db: Session, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Poll for new messages from service_ops.send_serviceops
        
        BULLETPROOF STRATEGY:
        - Only poll for messages where clinical_ops_decision_json has A/N decision_indicator
        - AND clinical_decision_applied_at IS NULL (decision not yet applied)
        - Use SELECT FOR UPDATE SKIP LOCKED for row-level locking (prevents duplicate processing)
        - Always apply decision first (even for Phase 2 rows), then handle Phase 2 if applicable
        
        Uses same watermark strategy as integration inbox:
        - Tracks both last_created_at and last_message_id
        - Handles edge cases where messages have same timestamp
        
        Returns:
            List of message dictionaries with message_id, decision_tracking_id, payload, created_at, json_sent_to_integration, clinical_ops_decision_json
        """
        try:
            # Get watermark (last processed created_at and message_id)
            watermark_result = db.execute(
                text("""
                    SELECT last_created_at, last_message_id
                    FROM service_ops.clinical_ops_poll_watermark
                    WHERE id = 1
                """)
            ).fetchone()
            
            if watermark_result:
                last_created_at = watermark_result[0]
                last_message_id = watermark_result[1]
            else:
                # Default to epoch if no watermark exists
                last_created_at = datetime(1970, 1, 1)
                last_message_id = 0
            
            # Check if clinical_ops_decision_json column exists
            column_exists = db.execute(
                text("""
                    SELECT EXISTS (
                        SELECT 1 
                        FROM information_schema.columns 
                        WHERE table_schema = 'service_ops' 
                        AND table_name = 'send_serviceops' 
                        AND column_name = 'clinical_ops_decision_json'
                    )
                """)
            ).scalar()
            
            # Check if clinical_decision_applied_at column exists
            applied_at_column_exists = db.execute(
                text("""
                    SELECT EXISTS (
                        SELECT 1 
                        FROM information_schema.columns 
                        WHERE table_schema = 'service_ops' 
                        AND table_name = 'send_serviceops' 
                        AND column_name = 'clinical_decision_applied_at'
                    )
                """)
            ).scalar()
            
            # BULLETPROOF: Poll for messages with unapplied decisions (A or N)
            if column_exists:
                if applied_at_column_exists:
                    # New bulletproof query: only unapplied decisions with A/N indicator
                    query = text("""
                        SELECT 
                            message_id,
                            decision_tracking_id,
                            payload,
                            created_at,
                            json_sent_to_integration,
                            clinical_ops_decision_json
                        FROM service_ops.send_serviceops
                        WHERE is_deleted = false
                            AND (
                                created_at > :last_created_at
                                OR (created_at = :last_created_at AND message_id > :last_message_id)
                            )
                            AND clinical_ops_decision_json IS NOT NULL
                            AND clinical_ops_decision_json->>'decision_indicator' IN ('A', 'N')
                            AND clinical_decision_applied_at IS NULL
                        ORDER BY created_at ASC, message_id ASC
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    """)
                else:
                    # Fallback: column doesn't exist yet, use old logic but filter for A/N
                    query = text("""
                        SELECT 
                            message_id,
                            decision_tracking_id,
                            payload,
                            created_at,
                            json_sent_to_integration,
                            clinical_ops_decision_json
                        FROM service_ops.send_serviceops
                        WHERE is_deleted = false
                            AND (
                                created_at > :last_created_at
                                OR (created_at = :last_created_at AND message_id > :last_message_id)
                            )
                            AND clinical_ops_decision_json IS NOT NULL
                            AND clinical_ops_decision_json->>'decision_indicator' IN ('A', 'N')
                            AND (
                                -- Phase 1: Clinical decision made, but payload not generated yet
                                (json_sent_to_integration IS NULL OR json_sent_to_integration = false)
                                OR
                                -- Phase 2: Payload already generated, but decision may not be applied yet
                                (json_sent_to_integration = true)
                            )
                        ORDER BY created_at ASC, message_id ASC
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    """)
            else:
                # Column doesn't exist yet - fallback to Phase 2 only
                logger.warning(
                    "clinical_ops_decision_json column does not exist yet. "
                    "Only processing Phase 2 records (json_sent_to_integration IS NOT NULL). "
                    "Phase 1 detection will be available after column is added."
                )
                query = text("""
                    SELECT 
                        message_id,
                        decision_tracking_id,
                        payload,
                        created_at,
                        json_sent_to_integration,
                        NULL as clinical_ops_decision_json
                    FROM service_ops.send_serviceops
                    WHERE is_deleted = false
                        AND (
                            created_at > :last_created_at
                            OR (created_at = :last_created_at AND message_id > :last_message_id)
                        )
                        AND json_sent_to_integration IS NOT NULL
                    ORDER BY created_at ASC, message_id ASC
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                """)
            
            # Use limit parameter if provided, otherwise use batch_size
            effective_limit = limit if limit is not None else self.batch_size
            
            result = db.execute(
                query,
                {
                    'last_created_at': last_created_at,
                    'last_message_id': last_message_id,
                    'batch_size': effective_limit
                }
            ).fetchall()
            
            messages = []
            for row in result:
                messages.append({
                    'message_id': row[0],
                    'decision_tracking_id': str(row[1]),
                    'payload': row[2],
                    'created_at': row[3],
                    'json_sent_to_integration': row[4],
                    'clinical_ops_decision_json': row[5]
                })
            
            return messages
        except Exception as e:
            logger.error(f"Error polling ClinicalOps messages: {e}", exc_info=True)
            return []
    
    async def _process_message(self, db: Session, message: Dict[str, Any]):
        """
        Process a single message from send_serviceops
        
        BULLETPROOF STRATEGY:
        1. ALWAYS apply decision first if clinical_ops_decision_json has A/N (even for Phase 2 rows)
           - This ensures decision is written even if Phase 1 was skipped
           - Idempotent: if already applied, skip update
        2. Set clinical_decision_applied_at after successful commit
        3. Then handle Phase 2 (JSON Generator, payload processing) as best-effort
        
        Args:
            db: Database session
            message: Message dictionary with message_id, decision_tracking_id, payload, created_at, json_sent_to_integration, clinical_ops_decision_json
        """
        message_id = message['message_id']
        decision_tracking_id = message['decision_tracking_id']
        json_sent_to_integration = message.get('json_sent_to_integration')
        clinical_ops_decision_json = message.get('clinical_ops_decision_json')
        
        logger.info(
            f"Processing message {message_id} | "
            f"decision_tracking_id={decision_tracking_id} | "
            f"has_clinical_ops_decision={clinical_ops_decision_json is not None} | "
            f"json_sent_to_integration={json_sent_to_integration}"
        )
        
        # BULLETPROOF STEP 1: ALWAYS apply decision if JSON has A/N
        # This works for both Phase 1 and Phase 2 rows
        # If decision was already applied (idempotent), this is a no-op
        decision_applied = False
        if clinical_ops_decision_json is not None:
            decision_indicator = clinical_ops_decision_json.get('decision_indicator', '')
            if decision_indicator in ['A', 'N']:
                logger.info(
                    f"Applying clinical decision for {decision_tracking_id} (decision_indicator={decision_indicator}). "
                    f"This applies to both Phase 1 and Phase 2 rows to ensure decision is always written."
                )
                
                # Apply decision (idempotent - will skip if already applied)
                await self._handle_clinical_decision(db, message, clinical_ops_decision_json)
                
                # Commit decision immediately
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, db.commit)
                logger.info(
                    f"Clinical decision committed for {decision_tracking_id}. "
                    f"Decision is now persisted in packet_decision."
                )
                
                # Mark decision as applied
                await loop.run_in_executor(None, self._mark_decision_applied, db, message_id)
                decision_applied = True
        
        # BULLETPROOF STEP 2: Handle Phase 1 (trigger JSON Generator) or Phase 2 (process payload)
        # Phase 1: json_sent_to_integration is NULL or false
        if clinical_ops_decision_json is not None and json_sent_to_integration is not True:
            logger.info(
                f"Phase 1 record detected for {decision_tracking_id}. "
                f"Decision applied. Now triggering JSON Generator Phase 2 (best-effort)..."
            )
            
            # Trigger JSON Generator Phase 2 (best-effort)
            try:
                success = await self._call_json_generator_phase2(decision_tracking_id)
                
                if success:
                    logger.info(
                        f"JSON Generator Phase 2 called successfully for {decision_tracking_id}. "
                        f"Generated payload will be written by JSON Generator in next cycle."
                    )
                else:
                    logger.warning(
                        f"JSON Generator Phase 2 failed for {decision_tracking_id}. "
                        f"Decision is already saved. Phase 2 can be retried later if needed."
                    )
            except Exception as phase2_error:
                # Phase 2 failure should NOT affect decision application
                logger.error(
                    f"Phase 2 error for {decision_tracking_id} (decision already saved): {phase2_error}",
                    exc_info=True
                )
                # Do NOT re-raise - decision is already applied and committed
            
            # Phase 1 complete - return (decision already applied and marked)
            return
        
        # PHASE 2: Generated payload ready to process
        # Phase 2 records have json_sent_to_integration = true
        # Decision should already be applied (from Step 1 above), but if it wasn't, we applied it
        if json_sent_to_integration is True:
            logger.info(
                f"Phase 2 record detected for {decision_tracking_id}. "
                f"Updating ESMD tracking from generated payload..."
            )
            
            # Update ESMD tracking from generated payload (decision already updated in Phase 1)
            await self._handle_generated_payload(db, message)
            
            # Mark message as processed
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._mark_message_processed, db, message_id)
            
            await loop.run_in_executor(None, db.commit)
            logger.info(f"Successfully processed Phase 2 payload message {message_id}")
            return
        
        # Unknown state - log warning
        # This could be:
        # - Phase 1 record but json_sent_to_integration is True (shouldn't happen)
        # - Phase 2 record but clinical_ops_decision_json is None (legacy record)
        # - Both NULL (shouldn't be in query results)
        logger.warning(
            f"Message {message_id} has unexpected state: "
            f"clinical_ops_decision_json={clinical_ops_decision_json is not None}, "
            f"json_sent_to_integration={json_sent_to_integration}. Skipping."
        )
    
    async def _handle_clinical_decision(
        self, 
        db: Session, 
        message: Dict[str, Any], 
        clinical_ops_decision_json: Dict[str, Any]
    ):
        """
        Handle Phase 1: Extract decision from clinical_ops_decision_json and update packet_decision
        
        Expected clinical_ops_decision_json structure (from production):
        {
            "source": "clinical_ops_ddms",
            "claim_id": 3677,
            "timestamp": "2026-01-29T15:41:28.103411",
            "decision_status": "Approved",
            "decision_indicator": "A",  // "A" = AFFIRM, "N" = NON_AFFIRM
            "failed_reason_data": null,
            "decision_tracking_id": "81a22ab4-36ba-4b14-9ee8-38942c67d4f9"
        }
        
        Actions:
        1. Validate packet exists
        2. Extract decision_indicator from clinical_ops_decision_json
        3. Update packet_decision with clinical decision
        4. Update packet status
        """
        decision_tracking_id = message['decision_tracking_id']
        
        # 1. Validate packet exists
        packet = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id == decision_tracking_id
        ).first()
        
        if not packet:
            raise ValueError(
                f"Packet not found for decision_tracking_id={decision_tracking_id}"
            )
        
        # 2. Extract decision indicator
        decision_indicator = clinical_ops_decision_json.get('decision_indicator', '')
        if decision_indicator not in ['A', 'N']:
            raise ValueError(
                f"Invalid decision_indicator '{decision_indicator}' in clinical_ops_decision_json. "
                f"Must be 'A' (AFFIRM) or 'N' (NON_AFFIRM)."
            )
        
        decision_outcome = 'AFFIRM' if decision_indicator == 'A' else 'NON_AFFIRM'
        
        # 3. Get document for part_type
        from app.models.document_db import PacketDocumentDB
        from app.services.decisions_service import DecisionsService
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        first_doc = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not first_doc:
            raise ValueError(
                f"No documents found for packet_id={packet.packet_id}"
            )
        
        # Get part_type from document (main source - should already exist from OCR processing)
        # If missing, log warning but don't fail - Phase 2 will handle it or derive from payload
        part_type = first_doc.part_type
        if not part_type or part_type not in ['A', 'B']:
            logger.warning(
                f"Packet document part_type is missing or invalid ('{part_type}') for {decision_tracking_id}. "
                f"Phase 1 will proceed without part_type. Phase 2 will attempt to derive it from payload."
            )
            part_type = None  # Set to None - Phase 2 will handle derivation
        
        # 4. Get current active decision
        current_decision = WorkflowOrchestratorService.get_active_decision(db, packet.packet_id)
        
        if not current_decision:
            # Create initial decision if none exists
            current_decision = DecisionsService.create_approve_decision(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=first_doc.packet_document_id,
                created_by='CLINICAL_OPS'
            )
        
        # 5. Idempotency check: Skip update if current decision already has same clinical_decision and decision_outcome
        # This prevents duplicate decision records when Phase 1 is retried (e.g., when Phase 2 fails)
        current_clinical_decision = getattr(current_decision, 'clinical_decision', None)
        current_decision_outcome = getattr(current_decision, 'decision_outcome', None)
        
        # Normalize values for comparison (handle None, PENDING, etc.)
        normalized_current_clinical = (current_clinical_decision or '').strip().upper()
        normalized_current_outcome = (current_decision_outcome or '').strip().upper()
        normalized_payload_clinical = (decision_outcome or '').strip().upper()
        normalized_payload_outcome = (decision_outcome or '').strip().upper()
        
        # Check if current decision already matches payload (idempotent retry)
        if (normalized_current_clinical == normalized_payload_clinical and 
            normalized_current_outcome == normalized_payload_outcome and
            normalized_payload_clinical in ['AFFIRM', 'NON_AFFIRM']):  # Only skip if it's a valid decision (not PENDING)
            logger.info(
                f"Idempotent retry detected for {decision_tracking_id}: "
                f"Current decision already has clinical_decision={current_clinical_decision}, "
                f"decision_outcome={current_decision_outcome}. Skipping update_clinical_decision to prevent duplicate record."
            )
            # Reuse existing decision instead of creating new one
            packet_decision = current_decision
        else:
            # Update clinical decision (creates new record for audit trail)
            # part_type can be None - Phase 2 will derive it from payload if needed
            packet_decision = DecisionsService.update_clinical_decision(
                db=db,
                packet_id=packet.packet_id,
                new_clinical_decision=decision_outcome,  # AFFIRM or NON_AFFIRM
                decision_subtype='DIRECT_PA',  # Will be determined in Phase 2 from payload
                part_type=part_type,  # Can be None - Phase 2 will handle
                decision_outcome=decision_outcome,
                created_by='CLINICAL_OPS'
            )
        
        # 6. Update packet status
        # Use "Clinical Decision Received" (allowed by check_detailed_status constraint)
        # Payload generation is handled in Phase 2 (JSON Generator)
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Clinical Decision Received"
        )
        
        logger.info(
            f"Updated clinical decision from Clinical Ops for {decision_tracking_id} | "
            f"decision_outcome={decision_outcome} | part_type={part_type}"
        )
    
    async def _call_json_generator_phase2(self, decision_tracking_id: str) -> bool:
        """
        Call JSON Generator Phase 2 endpoint to generate payload with retry logic.
        
        Args:
            decision_tracking_id: The decision tracking ID
            
        Returns:
            True if successful, False otherwise
        """
        if not self.json_generator_url:
            logger.warning("JSON_GENERATOR_BASE_URL not configured, cannot call Phase 2")
            return False
        
        endpoint = f"{self.json_generator_url}/api/v1/decision/generate_payload_json"
        
        # Get timeout and retry configuration
        timeout_seconds = getattr(settings, 'json_generator_timeout_seconds', 180)
        connect_timeout_seconds = getattr(settings, 'json_generator_connect_timeout_seconds', 30)
        max_retries = getattr(settings, 'json_generator_max_retries', 3)
        retry_base_seconds = getattr(settings, 'json_generator_retry_base_seconds', 2.0)
        
        # Use httpx.Timeout with separate connect and read timeouts for better control
        timeout = httpx.Timeout(
            connect=connect_timeout_seconds,  # Time to establish connection
            read=timeout_seconds,  # Time to read response
            write=30.0,  # Time to write request
            pool=30.0  # Time to get connection from pool
        )
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                logger.debug(
                    f"Calling JSON Generator Phase 2: {endpoint} | "
                    f"decision_tracking_id={decision_tracking_id} | "
                    f"Attempt {attempt + 1}/{max_retries}"
                )
                
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        endpoint,
                        json={"decision_tracking_id": decision_tracking_id},
                        headers={"Content-Type": "application/json"}
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    logger.info(
                        f"Successfully called JSON Generator Phase 2 for decision_tracking_id={decision_tracking_id} | "
                        f"status={result.get('status')}"
                    )
                    return True
                    
            except httpx.ConnectTimeout as e:
                last_exception = e
                logger.warning(
                    f"JSON Generator Phase 2 connection timeout for decision_tracking_id={decision_tracking_id} | "
                    f"Attempt {attempt + 1}/{max_retries}: {str(e)}"
                )
            except httpx.ReadTimeout as e:
                last_exception = e
                logger.warning(
                    f"JSON Generator Phase 2 read timeout for decision_tracking_id={decision_tracking_id} | "
                    f"Attempt {attempt + 1}/{max_retries}: {str(e)}"
                )
            except httpx.TimeoutException as e:
                last_exception = e
                logger.warning(
                    f"JSON Generator Phase 2 timeout for decision_tracking_id={decision_tracking_id} | "
                    f"Attempt {attempt + 1}/{max_retries}: {str(e)}"
                )
            except httpx.RequestError as e:
                last_exception = e
                logger.warning(
                    f"JSON Generator Phase 2 request error for decision_tracking_id={decision_tracking_id} | "
                    f"Attempt {attempt + 1}/{max_retries}: {str(e)}"
                )
            except httpx.HTTPStatusError as e:
                # Check if it's a retryable error (5xx server errors)
                if e.response.status_code >= 500:
                    last_exception = e
                    logger.warning(
                        f"JSON Generator Phase 2 server error ({e.response.status_code}) for decision_tracking_id={decision_tracking_id} | "
                        f"Attempt {attempt + 1}/{max_retries}: {e.response.text[:200]}"
                    )
                else:
                    # 4xx client errors - don't retry
                    logger.error(
                        f"JSON Generator Phase 2 returned client error for decision_tracking_id={decision_tracking_id}: "
                        f"status={e.response.status_code}, response={e.response.text[:200]}"
                    )
                    return False
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"JSON Generator Phase 2 unexpected error for decision_tracking_id={decision_tracking_id} | "
                    f"Attempt {attempt + 1}/{max_retries}: {str(e)}"
                )
            
            # Exponential backoff before retry (except on last attempt)
            if attempt < max_retries - 1:
                delay = retry_base_seconds * (2 ** attempt)
                logger.info(
                    f"Retrying JSON Generator Phase 2 for decision_tracking_id={decision_tracking_id} "
                    f"after {delay}s (exponential backoff)..."
                )
                await asyncio.sleep(delay)
        
        # All retries exhausted
        logger.error(
            f"Failed to call JSON Generator Phase 2 for decision_tracking_id={decision_tracking_id} "
            f"after {max_retries} attempts: {str(last_exception)}"
        )
        return False
    
    def _extract_decision_from_generated_payload(self, generated_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract decision data from JSON Generator's generated payload
        
        Expected payload structure (from production data):
        {
            "procedures": [
                {
                    "procedureCode": "64483",
                    "decisionIndicator": "A",
                    "mrCountUnitOfService": "1",
                    "modifier": "50",
                    "reviewCodes": [],
                    "programCodes": [],
                    "placeOfService": "22"
                }
            ],
            "partType": "A" or "B" or "" (empty string),
            "esmdTransactionId": "" (empty for Direct PA),
            "documentation": [] (medical documents/letter paths)
        }
        
        Args:
            generated_payload: The generated payload from JSON Generator (direct from send_serviceops.payload)
            
        Returns:
            Dict containing decision_outcome, decision_subtype, part_type, procedures, medical_documents, etc.
        """
        if not isinstance(generated_payload, dict):
            raise ValueError(f"Generated payload must be a dict, got {type(generated_payload)}")
        
        # Extract procedures (required)
        procedures = generated_payload.get('procedures', [])
        if not procedures or not isinstance(procedures, list) or len(procedures) == 0:
            available_keys = list(generated_payload.keys())
            raise ValueError(
                f"Generated payload missing procedures array. "
                f"Available keys: {available_keys}"
            )
        
        # Get decision indicator from first procedure (all should be same)
        decision_indicator = procedures[0].get('decisionIndicator', '')
        if decision_indicator not in ['A', 'N']:
            raise ValueError(f"Invalid decisionIndicator '{decision_indicator}' in generated payload")
        
        decision_outcome = 'AFFIRM' if decision_indicator == 'A' else 'NON_AFFIRM'
        
        # Extract part type (can be empty string in production - derive from packet if needed)
        part_type = generated_payload.get('partType', '').strip().upper()
        # If partType is empty, we'll derive it from the packet later, but for now allow empty
        # The validation will happen when we have the packet context
        
        # Determine if Direct PA or Standard PA based on esmdTransactionId
        esmd_transaction_id = generated_payload.get('esmdTransactionId', '').strip()
        is_direct_pa = not bool(esmd_transaction_id)  # No esmdTransactionId = Direct PA
        decision_subtype = 'DIRECT_PA' if is_direct_pa else 'STANDARD_PA'
        
        # Extract procedures (convert to our internal format)
        procedures_array = []
        for proc in procedures:
            procedures_array.append({
                'procedure_code': proc.get('procedureCode', ''),
                'decision_indicator': proc.get('decisionIndicator', ''),
                'mr_count_unit_of_service': proc.get('mrCountUnitOfService', '1'),
                'modifier': proc.get('modifier', ''),
                'review_codes': proc.get('reviewCodes', []),
                'program_codes': proc.get('programCodes', []),
                'place_of_service': proc.get('placeOfService', '')  # Part B only
            })
        
        # Extract documentation (letter paths) - can be empty array
        documentation = generated_payload.get('documentation', [])
        if not isinstance(documentation, list):
            documentation = []
        
        return {
            'decision_outcome': decision_outcome,
            'decision_subtype': decision_subtype,
            'part_type': part_type,  # Can be empty - will be validated/derived from packet
            'procedures': procedures_array,
            'medical_documents': documentation,
            'esmd_transaction_id': esmd_transaction_id,
            'is_direct_pa': is_direct_pa
        }
    
    async def _handle_generated_payload(self, db: Session, message: Dict[str, Any]):
        """
        Handle Phase 2: Update ESMD tracking from generated payload
        
        Note: Clinical decision is already updated in Phase 1 from clinical_ops_decision_json.
        This phase only updates:
        - ESMD tracking (status, payload storage, attempt count)
        - Decision subtype (DIRECT_PA vs STANDARD_PA) from payload
        - Medical documents from payload
        - Packet status
        
        JSON Generator already wrote to send_integration, so we don't generate ESMD payload here.
        """
        decision_tracking_id = message['decision_tracking_id']
        generated_payload = message['payload']
        json_sent_to_integration = message.get('json_sent_to_integration')
        
        # 1. Validate packet exists
        packet = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id == decision_tracking_id
        ).first()
        
        if not packet:
            raise ValueError(
                f"Packet not found for decision_tracking_id={decision_tracking_id}"
            )
        
        # 2. Get current active decision (should exist from Phase 1)
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        packet_decision = WorkflowOrchestratorService.get_active_decision(db, packet.packet_id)
        
        if not packet_decision:
            raise ValueError(
                f"No active decision found for packet_id={packet.packet_id}. "
                f"Phase 1 should have created the decision first."
            )
        
        # 3. Extract minimal data from payload (only what we need for tracking)
        # Note: We store the full payload below, so we extract these fields now for convenience
        # Extract medical documents (letter paths)
        documentation = generated_payload.get('documentation', []) if isinstance(generated_payload, dict) else []
        if not isinstance(documentation, list):
            documentation = []
        
        # Determine if Direct PA or Standard PA based on esmdTransactionId in payload
        # This is the authoritative source since JSON Generator determines it during payload generation
        esmd_transaction_id = generated_payload.get('esmdTransactionId', '').strip() if isinstance(generated_payload, dict) else ''
        is_direct_pa = not bool(esmd_transaction_id)
        decision_subtype = 'DIRECT_PA' if is_direct_pa else 'STANDARD_PA'
        
        # 4. Update decision subtype and medical documents (if changed)
        if packet_decision.decision_subtype != decision_subtype:
            packet_decision.decision_subtype = decision_subtype
            logger.info(
                f"Updated decision_subtype to '{decision_subtype}' for {decision_tracking_id} "
                f"(from generated payload: esmdTransactionId={'empty' if is_direct_pa else esmd_transaction_id})"
            )
        
        packet_decision.letter_medical_docs = documentation
        
        # Update ESMD tracking (payload already sent to integration by JSON Generator)
        # Check explicitly for True/False (not just truthy/falsy) to handle None correctly
        if json_sent_to_integration is True:
            packet_decision.esmd_request_status = 'SENT'
            packet_decision.esmd_last_sent_at = message['created_at']
        elif json_sent_to_integration is False:
            packet_decision.esmd_request_status = 'FAILED'
            logger.warning(
                f"JSON Generator failed to send payload to integration for {decision_tracking_id}"
            )
        else:
            # Shouldn't happen (query filters for IS NOT NULL), but handle gracefully
            logger.warning(
                f"Unexpected json_sent_to_integration value for {decision_tracking_id}: "
                f"{json_sent_to_integration}. Treating as FAILED."
            )
            packet_decision.esmd_request_status = 'FAILED'
        
        packet_decision.esmd_request_payload = generated_payload  # Store as JSONB
        packet_decision.esmd_attempt_count = 1
        
        # Initialize payload history
        packet_decision.esmd_request_payload_history = [{
            "attempt": 1,
            "sent_at": message['created_at'].isoformat() if hasattr(message['created_at'], 'isoformat') else str(message['created_at']),
            "status": "SENT" if json_sent_to_integration is True else "FAILED",
            "message_id": message['message_id']
        }]
        
        # Update letter tracking fields
        packet_decision.letter_owner = 'SERVICE_OPS'
        packet_decision.letter_status = 'PENDING'  # Waiting for UTN for AFFIRM/NON_AFFIRM
        
        # Update packet status
        if json_sent_to_integration is True:
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Pending - UTN"
            )
        else:
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Generate Decision Letter - Pending"
            )
            logger.warning(
                f"Workflow stopped due to JSON Generator failure for {decision_tracking_id}"
            )
            return
        
        logger.info(
            f"Updated ESMD tracking from generated payload for {decision_tracking_id} | "
            f"decision_subtype={decision_subtype} | json_sent_to_integration={json_sent_to_integration}"
        )
        
        # Get first document for letter generation (if needed)
        first_doc = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        # 4. Check if letter generation prerequisites are met
        # For AFFIRM/NON_AFFIRM: Need UTN_SUCCESS
        # For DISMISSAL: Generate immediately (no UTN required)
        if packet_decision.decision_outcome in ['AFFIRM', 'NON_AFFIRM']:
            if packet_decision.utn_status == 'SUCCESS':
                # UTN already received, trigger letter generation
                if first_doc:
                    logger.info(
                        f"Decision received and UTN already available for packet_id={packet.packet_id}. "
                        f"Triggering letter generation."
                    )
                    await self._trigger_letter_generation(db, packet, packet_decision, first_doc)
                else:
                    logger.warning(
                        f"No document found for packet_id={packet.packet_id}. Skipping letter generation."
                    )
            else:
                # Wait for UTN_SUCCESS handler to trigger letter generation
                logger.info(
                    f"Decision received for packet_id={packet.packet_id}, waiting for UTN_SUCCESS. "
                    f"Letter generation will be triggered when UTN is received."
                )
        elif packet_decision.decision_outcome == 'DISMISSAL':
            # Dismissal: generate letter immediately (no UTN required)
            if first_doc:
                logger.info(
                    f"Dismissal decision received for packet_id={packet.packet_id}. "
                    f"Triggering letter generation immediately (no UTN required)."
                )
                await self._trigger_letter_generation(db, packet, packet_decision, first_doc)
            else:
                logger.warning(
                    f"No document found for packet_id={packet.packet_id}. Skipping letter generation."
                )
        else:
            # Unknown or missing decision_outcome
            logger.warning(
                f"Unknown or missing decision_outcome for packet_id={packet.packet_id}: "
                f"{packet_decision.decision_outcome}. Skipping letter generation."
            )
    
    async def _trigger_letter_generation(
        self,
        db: Session,
        packet: PacketDB,
        packet_decision: PacketDecisionDB,
        packet_document: PacketDocumentDB
    ) -> None:
        """
        Trigger letter generation via LetterGenerationService
        
        Args:
            db: Database session
            packet: PacketDB record
            packet_decision: PacketDecisionDB record
            packet_document: PacketDocumentDB record
        """
        from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
        
        # Determine letter type
        letter_type_map = {
            'AFFIRM': 'affirmation',
            'NON_AFFIRM': 'non-affirmation',
            'DISMISSAL': 'dismissal'
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
            
            # Update packet_decision
            packet_decision.letter_status = 'READY'
            packet_decision.letter_package = letter_metadata
            packet_decision.letter_generated_at = datetime.utcnow()
            
            db.commit()
            
            logger.info(
                f"Successfully generated {letter_type} letter for packet_id={packet.packet_id} | "
                f"blob_url={letter_metadata.get('blob_url')}"
            )
            
            # Send to Integration outbox
            await self._send_letter_to_integration(db, packet, packet_decision)
            
        except LetterGenerationError as e:
            logger.error(
                f"Letter generation failed for packet_id={packet.packet_id}: {e}",
                exc_info=True
            )
            # Store error in letter_package
            packet_decision.letter_status = 'FAILED'
            packet_decision.letter_package = {
                "error": {
                    "code": "LETTER_GENERATION_ERROR",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
            # Update packet status to indicate letter generation failed
            from app.services.workflow_orchestrator import WorkflowOrchestratorService
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
            packet_decision.letter_status = 'FAILED'
            packet_decision.letter_package = {
                "error": {
                    "code": "UNEXPECTED_ERROR",
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
            # Update packet status to indicate letter generation failed
            from app.services.workflow_orchestrator import WorkflowOrchestratorService
            WorkflowOrchestratorService.update_packet_status(
                db=db,
                packet=packet,
                new_status="Generate Decision Letter - Pending"  # Keep same status, letter_status shows failure
            )
            db.commit()
    
    async def _send_letter_to_integration(
        self,
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
        payload_hash = self._hash_payload(payload_json)
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
        db.commit()
        
        logger.info(
            f"Sent letter package to service_ops.send_integration | "
            f"message_id={outbox_record.message_id} | "
            f"decision_tracking_id={packet.decision_tracking_id}"
        )
    
    def _update_watermark(self, db: Session, max_created_at: datetime, max_message_id: int):
        """
        Update polling watermark after processing a batch (same strategy as integration inbox)
        
        Uses GREATEST() to ensure watermark always moves forward, even with concurrent updates.
        This makes it reliable and safe for multi-worker scenarios.
        
        Args:
            max_created_at: Maximum created_at timestamp from processed batch
            max_message_id: Maximum message_id from processed batch
        """
        try:
            db.execute(
                text("""
                    INSERT INTO service_ops.clinical_ops_poll_watermark (
                        id,
                        last_created_at,
                        last_message_id,
                        updated_at
                    )
                    VALUES (1, :max_created_at, :max_message_id, NOW())
                    ON CONFLICT (id) 
                    DO UPDATE SET 
                        last_created_at = GREATEST(
                            service_ops.clinical_ops_poll_watermark.last_created_at,
                            EXCLUDED.last_created_at
                        ),
                        last_message_id = GREATEST(
                            service_ops.clinical_ops_poll_watermark.last_message_id,
                            EXCLUDED.last_message_id
                        ),
                        updated_at = NOW()
                """),
                {
                    'max_created_at': max_created_at,
                    'max_message_id': max_message_id
                }
            )
        except Exception as e:
            logger.error(f"Error updating ClinicalOps watermark: {e}", exc_info=True)
            # Don't fail the whole operation if watermark update fails
    
    def _mark_message_processed(self, db: Session, message_id: int):
        """Mark message as processed (update status if needed)"""
        # For now, we just track via watermark
        # If needed, we can update message_status_id or add a processed_at timestamp
        pass
    
    def _mark_decision_applied(self, db: Session, message_id: int):
        """
        Mark that clinical decision has been successfully applied to packet_decision.
        Sets clinical_decision_applied_at = NOW() for the message.
        
        This is the source of truth for "has this decision been written to packet_decision?"
        Used by poll query to only process unapplied decisions.
        
        Args:
            db: Database session
            message_id: Message ID to mark as applied
        """
        try:
            # Check if column exists
            column_exists = db.execute(
                text("""
                    SELECT EXISTS (
                        SELECT 1 
                        FROM information_schema.columns 
                        WHERE table_schema = 'service_ops' 
                        AND table_name = 'send_serviceops' 
                        AND column_name = 'clinical_decision_applied_at'
                    )
                """)
            ).scalar()
            
            if not column_exists:
                logger.debug(
                    f"clinical_decision_applied_at column does not exist yet. "
                    f"Skipping mark for message_id={message_id}."
                )
                return
            
            # Set clinical_decision_applied_at = NOW()
            result = db.execute(
                text("""
                    UPDATE service_ops.send_serviceops
                    SET clinical_decision_applied_at = NOW()
                    WHERE message_id = :message_id
                """),
                {'message_id': message_id}
            )
            
            if result.rowcount > 0:
                logger.debug(f"Marked clinical decision as applied for message_id={message_id}")
            else:
                logger.warning(f"Message {message_id} not found when trying to mark decision as applied")
        except Exception as e:
            logger.error(
                f"Error marking decision as applied for message_id={message_id}: {e}",
                exc_info=True
            )
            # Don't re-raise - this is best-effort tracking
    
    def _mark_message_failed(self, db: Session, message_id: int, error_message: str):
        """Mark message as failed"""
        logger.error(f"Marking ClinicalOps message {message_id} as failed: {error_message}")
        # For now, just log - can add retry logic later if needed
        # Note: clinical_decision_applied_at remains NULL, so message will be retried
        pass
    
    def _hash_payload(self, payload_json: str) -> str:
        """Generate SHA-256 hash of payload for audit"""
        import hashlib
        return hashlib.sha256(payload_json.encode('utf-8')).hexdigest()

