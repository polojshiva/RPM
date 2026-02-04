"""
Message Poller Service
Polls integration.send_serviceops for new messages and processes them
Uses IntegrationInboxService for idempotent processing
"""
import asyncio
import logging
import uuid
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.services.db import SessionLocal
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.services.payload_parser import PayloadParser
from app.services.document_processor import DocumentProcessor, DocumentProcessorError
from app.services.integration_inbox import IntegrationInboxService
from app.services.status_update_service import StatusUpdateService
from app.services.stuck_job_reclaimer import StuckJobReclaimer
from app.config import settings

logger = logging.getLogger(__name__)


class MessagePollerService:
    """
    Background service that polls integration.send_serviceops for new messages
    and triggers processing (OCR, packet creation, etc.)
    Uses IntegrationInboxService for idempotent message processing
    
    All workers run the poller. Job claiming uses FOR UPDATE SKIP LOCKED to prevent duplicates.
    """
    
    def __init__(self):
        self.is_running = False
        self.poll_task: Optional[asyncio.Task] = None
        self.worker_id = f"worker-{uuid.uuid4()}"
        # Don't create inbox_service here - create fresh instance for each operation
        self.status_update_service = StatusUpdateService()
        self.stuck_job_reclaimer = StuckJobReclaimer(
            stale_lock_minutes=10,
            max_attempts=5,
            status_update_service=self.status_update_service
        )
    
    async def start(self):
        """Start the message poller background task"""
        if self.is_running:
            logger.warning("Message poller is already running")
            return
        
        if not settings.message_poller_enabled:
            logger.info("Message poller is disabled in settings")
            return
        
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
                    f"CRITICAL: Unhandled exception in message poller task: {e}. "
                    f"Poller will stop but worker will continue running.",
                    exc_info=True
                )
                # Mark as not running so it doesn't try to process more
                self.is_running = False
        
        self.poll_task.add_done_callback(handle_task_exception)
        
        logger.info(
            f"✅ Message poller started as LEADER (interval: {settings.message_poller_interval_seconds}s, "
            f"batch_size: {settings.message_poller_batch_size}, worker_id={self.worker_id})"
        )
    
    async def stop(self):
        """Stop the message poller background task"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Message poller stopped")
    
    async def _poll_loop(self):
        """Main polling loop"""
        reclaimer_counter = 0
        reclaimer_interval = 5  # Run reclaimer every 5 poll cycles
        
        while self.is_running:
            try:
                await self._poll_and_process()
                
                # Run stuck job reclaimer periodically
                reclaimer_counter += 1
                if reclaimer_counter >= reclaimer_interval:
                    reclaimer_counter = 0
                    try:
                        loop = asyncio.get_event_loop()
                        stats = await loop.run_in_executor(
                            None,
                            self.stuck_job_reclaimer.detect_and_recover_stuck_jobs
                        )
                        if stats['detected'] > 0:
                            logger.info(
                                f"Stuck job reclaimer: detected={stats['detected']}, "
                                f"reset_to_new={stats['reset_to_new']}, "
                                f"marked_failed={stats['marked_failed']}"
                            )
                    except Exception as e:
                        logger.error(f"Error in stuck job reclaimer: {e}", exc_info=True)
                        
            except asyncio.CancelledError:
                logger.info("Message poller cancelled")
                break
            except Exception as e:
                logger.error(f"Error in message poller loop: {e}", exc_info=True)
            
            # Wait before next poll
            try:
                await asyncio.sleep(settings.message_poller_interval_seconds)
            except asyncio.CancelledError:
                break
    
    async def _poll_and_process(self):
        """
        Poll for new messages and insert into inbox (idempotent)
        Then process claimed jobs from inbox
        """
        # CRITICAL: Check connection pool before processing
        from app.services.connection_pool_monitor import should_throttle_background, log_pool_status, get_pool_usage
        log_pool_status()
        
        pool_usage = get_pool_usage()
        should_throttle = should_throttle_background()
        
        if should_throttle:
            # Pool is critical - reduce batch size but still process at least 1 record
            logger.warning(
                f"Connection pool CRITICAL ({pool_usage['usage_percent']:.1%}) - "
                f"reducing batch size to prevent record accumulation. "
                f"Will process at least 1 record this cycle."
            )
            # Continue but with reduced batch size (handled below)
        else:
            # Pool is healthy - use normal batch size
            pass
        
        # Create fresh inbox service for this poll cycle to avoid transaction issues
        inbox_service = IntegrationInboxService()
        try:
            # Step 1: Poll for new messages from integration.send_serviceops
            # Adjust batch size if pool is critical
            effective_batch_size = settings.message_poller_batch_size
            if should_throttle:
                effective_batch_size = 1  # Process only 1 record when pool is critical
                logger.info(f"Pool critical - processing only 1 record this cycle (normal batch: {settings.message_poller_batch_size})")
            
            loop = asyncio.get_event_loop()
            messages = await loop.run_in_executor(
                None, 
                inbox_service.poll_new_messages,
                effective_batch_size
            )
            
            if not messages:
                logger.debug("No new messages found in integration.send_serviceops")
            else:
                logger.info(f"Found {len(messages)} new message(s) to insert into inbox")
                
                # Step 2: Insert messages into inbox (idempotent)
                max_created_at = None
                max_message_id = 0
                inserted_count = 0
                
                for msg in messages:
                    # Get message_type_id from message (1=intake, 2=UTN success, 3=UTN fail)
                    message_type_id = msg.get('message_type_id')
                    if message_type_id is None:
                        message_type_id = 1  # Default to 1 for backward compatibility
                    
                    # Infer message_type from payload if missing
                    message_type = msg['payload'].get('message_type')
                    if not message_type:
                        # Infer from message_type_id or structure
                        if message_type_id == 2:
                            message_type = 'UTN'
                        elif message_type_id == 3:
                            message_type = 'UTN_FAIL'
                        elif 'decision_tracking_id' in msg['payload'] and 'documents' in msg['payload']:
                            message_type = 'ingest_file_package'
                        else:
                            message_type = 'ingest_file_package'  # Default for backward compatibility
                    
                    # Extract channel_type_id from message (can be None for backward compatibility)
                    channel_type_id = msg.get('channel_type_id')
                    
                    inbox_id = await loop.run_in_executor(
                        None,
                        inbox_service.insert_into_inbox,
                        msg['message_id'],
                        msg['decision_tracking_id'],
                        message_type,
                        msg['created_at'],
                        channel_type_id,  # Pass channel_type_id
                        message_type_id  # Pass message_type_id
                    )
                    
                    if inbox_id:
                        inserted_count += 1
                        logger.info(f"Inserted new message into inbox: inbox_id={inbox_id}, message_id={msg['message_id']}")
                    
                    # Track max for watermark update
                    if max_created_at is None or msg['created_at'] > max_created_at:
                        max_created_at = msg['created_at']
                        max_message_id = msg['message_id']
                    elif msg['created_at'] == max_created_at and msg['message_id'] > max_message_id:
                        max_message_id = msg['message_id']
                
                # Step 3: Update watermark
                if max_created_at:
                    await loop.run_in_executor(
                        None,
                        inbox_service.update_watermark,
                        max_created_at,
                        max_message_id
                    )
                    logger.debug(f"Updated watermark: created_at={max_created_at}, message_id={max_message_id}")
                
                if inserted_count > 0:
                    logger.info(f"Inserted {inserted_count} new message(s) into inbox")
            
            # Step 4: Process claimed jobs from inbox
            await self._process_claimed_jobs()
            
        except Exception as e:
            logger.error(f"Error in poll and process: {e}", exc_info=True)
        finally:
            # Clean up inbox service
            inbox_service.close()
    
    async def _process_claimed_jobs(self):
        """Process jobs claimed from inbox"""
        # Process jobs with configurable concurrency limit
        # Increased cap to 5 concurrent jobs for faster processing
        max_jobs_per_cycle = min(settings.message_poller_batch_size, 5)  # Cap at 5 concurrent jobs
        loop = asyncio.get_event_loop()
        
        for iteration in range(max_jobs_per_cycle):
            # Create fresh inbox service for each claim to avoid transaction issues
            inbox_service = IntegrationInboxService()
            try:
                # Claim a job
                job = await loop.run_in_executor(
                    None,
                    inbox_service.claim_job,
                    self.worker_id,
                    10  # stale_lock_minutes
                )
                
                if not job:
                    # No jobs available
                    break
                
                logger.info(f"Claimed job: inbox_id={job['inbox_id']}, message_id={job['message_id']}, attempt={job['attempt_count']}")
                
                try:
                    # Get source message
                    source_msg = await loop.run_in_executor(
                        None,
                        inbox_service.get_source_message,
                        job['message_id']
                    )
                    
                    if not source_msg:
                        logger.error(f"Source message {job['message_id']} not found")
                        # Use guaranteed status update
                        await loop.run_in_executor(
                            None,
                            self.status_update_service.mark_failed_with_retry,
                            job['inbox_id'],
                            f"Source message {job['message_id']} not found in integration.send_serviceops",
                            job.get('attempt_count')
                        )
                        continue
                    
                    # Extract channel_type_id and message_type_id from job
                    channel_type_id = job.get('channel_type_id')
                    message_type_id = job.get('message_type_id')
                    if message_type_id is None:
                        message_type_id = 1  # Default to 1 for backward compatibility
                    
                    # Process the message with channel_type_id and message_type_id
                    await self._process_message(source_msg, job['inbox_id'], channel_type_id, message_type_id)
                    
                    # Mark as done (with guaranteed retry)
                    result = await loop.run_in_executor(
                        None,
                        self.status_update_service.mark_done_with_retry,
                        job['inbox_id']
                    )
                    
                    if result.success:
                        logger.info(f"Successfully processed job: inbox_id={job['inbox_id']}")
                    else:
                        logger.error(
                            f"Failed to mark job as done after {result.attempts} attempts: "
                            f"inbox_id={job['inbox_id']}, error={result.error}"
                        )
                    
                    # CRITICAL: Add delay between processing jobs to:
                    # 1. Release DB connection back to pool
                    # 2. Allow auth/user requests to get connections
                    # 3. Prevent overwhelming OCR service
                    # Delay after each job except the last iteration (we break if no more jobs)
                    if iteration < max_jobs_per_cycle - 1:
                        delay_seconds = 3.0  # 3 second delay between jobs
                        logger.debug(f"Delaying {delay_seconds}s before next job...")
                        await asyncio.sleep(delay_seconds)
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(
                        f"Error processing job inbox_id={job['inbox_id']}: {error_msg}",
                        exc_info=True
                    )
                    # Mark as failed (with guaranteed retry)
                    await loop.run_in_executor(
                        None,
                        self.status_update_service.mark_failed_with_retry,
                        job['inbox_id'],
                        error_msg,
                        job.get('attempt_count')
                    )
            finally:
                # Clean up inbox service
                inbox_service.close()
    
    def _fetch_messages(self) -> List[SendServiceOpsDB]:
        """
        Fetch unprocessed messages from integration.send_serviceops
        Returns messages that:
        - Are not deleted
        - Have message_type = 'ingest_file_package' (in payload)
        - Have not been processed yet (no packet exists for decision_tracking_id)
        """
        db: Session = SessionLocal()
        try:
            # Fetch all non-deleted messages
            all_messages = db.query(SendServiceOpsDB).filter(
                SendServiceOpsDB.is_deleted == False
            ).order_by(
                SendServiceOpsDB.created_at.asc()  # Process oldest first
            ).limit(
                settings.message_poller_batch_size * 2  # Fetch more to filter
            ).all()
            
            # Filter to only unprocessed messages
            unprocessed_messages = []
            for message in all_messages:
                if self._is_message_processed(db, message):
                    logger.debug(f"Message {message.message_id} already processed, skipping")
                    continue
                
                # Check message_type in payload (backward compatible with new format)
                message_type = message.payload.get('message_type') if message.payload else None
                if not message_type:
                    # Infer from structure: if has decision_tracking_id and documents at root, assume ingest_file_package
                    if message.payload and 'decision_tracking_id' in message.payload and 'documents' in message.payload:
                        message_type = 'ingest_file_package'
                
                if message_type == 'ingest_file_package':
                    unprocessed_messages.append(message)
                
                # Stop when we have enough
                if len(unprocessed_messages) >= settings.message_poller_batch_size:
                    break
            
            return unprocessed_messages
        except Exception as e:
            logger.error(f"Error fetching messages: {e}", exc_info=True)
            return []
        finally:
            db.close()
    
    def _is_message_processed(self, db: Session, message: SendServiceOpsDB) -> bool:
        """
        Check if a message has already been processed
        A message is considered processed if:
        1. A packet exists with matching decision_tracking_id (stored in case_id or external metadata)
        2. OR documents exist that match the unique_id from the message
        
        For now, we'll check by looking for packets/documents with matching identifiers
        from the payload.
        """
        if not message.payload:
            return False
        
        try:
            parsed = PayloadParser.parse_full_payload(message.payload)
        except ValueError as e:
            logger.debug(f"Message {message.message_id} validation failed: {e}")
            return False
        
        decision_tracking_id = parsed.decision_tracking_id
        unique_id = parsed.unique_id
        
        if not decision_tracking_id and not unique_id:
            return False
        
        # Strategy 1: Check if any packet_document exists with a file_name that matches
        # documents from this message (this is a simple heuristic)
        if parsed.documents:
            # Get first document's filename as a check
            first_doc = parsed.documents[0]
            file_name = first_doc.file_name or first_doc.document_unique_identifier
            
            if file_name:
                # Check if document with this filename already exists
                existing_doc = db.query(PacketDocumentDB).filter(
                    PacketDocumentDB.file_name == file_name
                ).first()
                
                if existing_doc:
                    logger.debug(
                        f"Message {message.message_id} already processed "
                        f"(document {file_name} exists)"
                    )
                    return True
        
        # Strategy 2: Check if packet exists with matching decision_tracking_id
        if decision_tracking_id:
            existing_packet = db.query(PacketDB).filter(
                PacketDB.decision_tracking_id == decision_tracking_id
            ).first()
            
            if existing_packet:
                logger.debug(
                    f"Message {message.message_id} already processed "
                    f"(packet {existing_packet.external_id} exists for decision_tracking_id {decision_tracking_id})"
                )
                return True
        
        # Message is not processed
        return False
    
    async def _process_message(
        self,
        message: SendServiceOpsDB,
        inbox_id: Optional[int] = None,
        channel_type_id: Optional[int] = None,
        message_type_id: Optional[int] = None
    ):
        """
        Process a single message
        Routes to appropriate handler based on message_type_id:
        - message_type_id = 1: DocumentProcessor (intake)
        - message_type_id = 2: UtnSuccessHandler (UTN success)
        - message_type_id = 3: UtnFailHandler (UTN fail)
        
        Args:
            message: SendServiceOpsDB message from integration.send_serviceops
            inbox_id: Optional inbox_id for tracking
            channel_type_id: Channel type ID (1=Portal, 2=Fax, 3=ESMD), optional for backward compatibility
            message_type_id: Message type ID (1=intake, 2=UTN success, 3=UTN fail), optional for backward compatibility
        """
        if message_type_id is None:
            message_type_id = getattr(message, 'message_type_id', 1)  # Default to 1
        
        logger.info(
            f"Processing message_id={message.message_id}, inbox_id={inbox_id}, "
            f"message_type_id={message_type_id}"
        )
        
        # Route to appropriate handler based on message_type_id
        if message_type_id == 2:
            # UTN_SUCCESS handler
            await self._process_utn_success(message, inbox_id)
        elif message_type_id == 3:
            # UTN_FAIL handler
            await self._process_utn_fail(message, inbox_id)
        else:
            # Default: message_type_id = 1 (intake) - use DocumentProcessor
            await self._process_intake_message(message, inbox_id, channel_type_id)
    
    async def _process_intake_message(
        self,
        message: SendServiceOpsDB,
        inbox_id: Optional[int] = None,
        channel_type_id: Optional[int] = None
    ):
        """
        Process intake message (message_type_id = 1) using DocumentProcessor
        
        Args:
            message: SendServiceOpsDB message
            inbox_id: Optional inbox_id for tracking
            channel_type_id: Channel type ID
        """
        # Parse payload
        if not message.payload:
            logger.warning(f"Message {message.message_id} has no payload")
            return
        
        try:
            parsed = PayloadParser.parse_full_payload(message.payload)
        except ValueError as e:
            logger.error(f"Payload validation failed for message {message.message_id}: {e}")
            raise
        
        # Log message details
        logger.info(
            f"Message {message.message_id} details:\n"
            f"  Decision Tracking ID: {parsed.decision_tracking_id}\n"
            f"  Unique ID: {parsed.unique_id or '(derived)'}\n"
            f"  eSMD Transaction ID: {parsed.esmd_transaction_id or '(not provided)'}\n"
            f"  Number of Documents: {len(parsed.documents)}\n"
            f"  Message Type: {parsed.message_type}\n"
            f"  Blob Storage Path: {parsed.blob_storage_path or '(not provided)'}\n"
            f"  Extraction Path: {parsed.extraction_path or '(not provided - using blobPath)'}"
        )
        
        # Log document details
        if parsed.documents:
            logger.info(f"  Documents ({len(parsed.documents)}):")
            for doc in parsed.documents:
                file_size_str = f"{doc.file_size} bytes" if doc.file_size is not None else "size unknown"
                logger.info(
                    f"    - {doc.file_name} "
                    f"({file_size_str}, "
                    f"{doc.mime_type}, "
                    f"source: {doc.source_absolute_url})"
                )
        
        # Get channel_type_id from message if not provided (fallback)
        if channel_type_id is None or channel_type_id == 0:
            message_channel_type_id = getattr(message, 'channel_type_id', None)
            if message_channel_type_id is None or message_channel_type_id == 0:
                from app.models.channel_type import ChannelType
                channel_type_id = ChannelType.ESMD  # Default to ESMD
                logger.debug(f"channel_type_id is NULL/empty, defaulting to ESMD (3)")
            else:
                channel_type_id = message_channel_type_id
        
        # Log channel type
        if channel_type_id:
            logger.info(f"Processing with channel_type_id={channel_type_id}")
        else:
            logger.info("Processing with channel_type_id=None (backward compatibility mode)")
        
        # Process documents through DocumentProcessor with channel_type_id
        # CRITICAL: Run in executor to avoid blocking event loop (allows user requests to be processed)
        try:
            processor = DocumentProcessor(channel_type_id=channel_type_id)
            loop = asyncio.get_event_loop()
            # Run blocking I/O operations in executor so they don't block user requests
            await loop.run_in_executor(
                None,
                processor.process_message,
                message,
                inbox_id
            )
            logger.info(f"Message {message.message_id} processed successfully")
        except DocumentProcessorError as e:
            logger.error(f"Document processing failed for message {message.message_id}: {e}", exc_info=True)
            raise  # Re-raise to trigger retry logic
    
    async def _process_utn_success(self, message: SendServiceOpsDB, inbox_id: Optional[int] = None):
        """
        Process UTN_SUCCESS message (message_type_id = 2)
        
        Args:
            message: SendServiceOpsDB message
            inbox_id: Optional inbox_id for tracking
        """
        from app.services.utn_handlers import UtnSuccessHandler
        from app.services.db import SessionLocal
        
        db = SessionLocal()
        try:
            message_dict = {
                'message_id': message.message_id,
                'decision_tracking_id': str(message.decision_tracking_id),
                'payload': message.payload,
                'created_at': message.created_at
            }
            
            # Run handler (it's now async)
            await UtnSuccessHandler.handle(db, message_dict)
            
            db.commit()
            logger.info(f"UTN_SUCCESS message {message.message_id} processed successfully")
        except Exception as e:
            db.rollback()
            logger.error(f"UTN_SUCCESS processing failed for message {message.message_id}: {e}", exc_info=True)
            raise
        finally:
            db.close()
    
    async def _process_utn_fail(self, message: SendServiceOpsDB, inbox_id: Optional[int] = None):
        """
        Process UTN_FAIL message (message_type_id = 3)
        
        Args:
            message: SendServiceOpsDB message
            inbox_id: Optional inbox_id for tracking
        """
        from app.services.utn_handlers import UtnFailHandler
        from app.services.db import SessionLocal
        
        db = SessionLocal()
        try:
            message_dict = {
                'message_id': message.message_id,
                'decision_tracking_id': str(message.decision_tracking_id),
                'payload': message.payload,
                'created_at': message.created_at
            }
            
            # Run handler in executor (it's synchronous)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                UtnFailHandler.handle,
                db,
                message_dict
            )
            
            db.commit()
            logger.info(f"UTN_FAIL message {message.message_id} processed successfully")
        except Exception as e:
            db.rollback()
            logger.error(f"UTN_FAIL processing failed for message {message.message_id}: {e}", exc_info=True)
            raise
        finally:
            db.close()


# Global instance
_message_poller: Optional[MessagePollerService] = None


def get_message_poller() -> MessagePollerService:
    """Get or create the global message poller instance"""
    global _message_poller
    if _message_poller is None:
        _message_poller = MessagePollerService()
    return _message_poller

