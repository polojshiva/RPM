"""
Integration Inbox Service
Handles idempotent message processing from integration.send_serviceops
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy import text, and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.services.db import SessionLocal, get_db_session
from app.models.integration_db import SendServiceOpsDB

logger = logging.getLogger(__name__)


class IntegrationInboxService:
    """Service for managing integration inbox and polling messages"""
    
    def __init__(self, db: Optional[Session] = None):
        self._db = db  # Store reference but don't create session yet
        self._own_session = db is None  # Track if we own the session
    
    def _get_db(self, fresh: bool = False) -> Session:
        """
        Get database session, creating new one if needed
        
        Args:
            fresh: If True, create a new session even if one exists
        """
        if fresh or self._db is None:
            # Close old session if we own it
            if self._db and self._own_session:
                try:
                    self._db.close()
                except Exception:
                    pass
            self._db = SessionLocal()
            self._own_session = True
        return self._db
    
    def get_watermark(self) -> Dict[str, Any]:
        """
        Get current polling watermark
        
        Returns:
            Dict with 'last_created_at' and 'last_message_id'
        """
        # Use fresh session for read operation to avoid transaction issues
        db = self._get_db(fresh=True)
        try:
            result = db.execute(
                text("""
                    SELECT last_created_at, last_message_id
                    FROM service_ops.integration_poll_watermark
                    WHERE id = 1
                """)
            ).fetchone()
            
            if result:
                return {
                    'last_created_at': result[0],
                    'last_message_id': result[1]
                }
            else:
                # Watermark record doesn't exist - try to initialize it defensively
                # This handles cases where migration 001 INSERT failed or was rolled back
                logger.warning(
                    "Watermark record (id=1) not found in integration_poll_watermark. "
                    "Attempting to initialize it. This should have been created by migration 001."
                )
                try:
                    db.execute(
                        text("""
                            INSERT INTO service_ops.integration_poll_watermark 
                            (id, last_created_at, last_message_id, updated_at)
                            VALUES (1, '1970-01-01 00:00:00', 0, NOW())
                            ON CONFLICT (id) DO NOTHING
                        """)
                    )
                    db.commit()
                    logger.info("✅ Successfully initialized watermark record")
                    
                    # Retry fetch after initialization
                    result = db.execute(
                        text("""
                            SELECT last_created_at, last_message_id
                            FROM service_ops.integration_poll_watermark
                            WHERE id = 1
                        """)
                    ).fetchone()
                    
                    if result:
                        return {
                            'last_created_at': result[0],
                            'last_message_id': result[1]
                        }
                except Exception as init_error:
                    db.rollback()
                    logger.warning(
                        f"Failed to initialize watermark record (may not have permissions or record already exists): {init_error}. "
                        f"Using default watermark. Record will be created automatically on first message processing."
                    )
                
                # Return default watermark if initialization failed or record still doesn't exist
                # This is safe - update_watermark() will create the record on first update
                return {
                    'last_created_at': datetime(1970, 1, 1),
                    'last_message_id': 0
                }
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error getting watermark: {e}", exc_info=True)
            # Return default on error
            return {
                'last_created_at': datetime(1970, 1, 1),
                'last_message_id': 0
            }
    
    def poll_new_messages(self, batch_size: int = 10) -> List[Dict[str, Any]]:
        """
        Poll for new messages from integration.send_serviceops
        
        Args:
            batch_size: Maximum number of messages to fetch
            
        Returns:
            List of message dictionaries with message_id, decision_tracking_id, payload, created_at
        """
        # Use fresh session for this read operation
        db = self._get_db(fresh=True)
        try:
            watermark = self.get_watermark()
            
            # Poll query: Process message_type_id = 1 (intake), 2 (UTN success), 3 (UTN fail)
            # For type 1: Relaxed filter - only require decision_tracking_id OR message_type = 'ingest_file_package'
            # Documents can be missing/empty - will be handled gracefully in processing
            # For type 2/3: Only require decision_tracking_id (UTN events don't have documents)
            # Include channel_type_id and message_type_id from table
            query = text("""
                SELECT 
                    message_id,
                    decision_tracking_id,
                    payload,
                    created_at,
                    channel_type_id,
                    message_type_id
                FROM integration.send_serviceops
                WHERE is_deleted = false
                    AND (
                        -- Process message_type_id = 1 (intake), 2 (UTN success), 3 (UTN fail)
                        message_type_id IN (1, 2, 3)
                        OR message_type_id IS NULL  -- Handle NULL as type 1 for backward compatibility
                    )
                    AND (
                        -- For type 1: require ingest_file_package or decision_tracking_id
                        (message_type_id = 1 OR message_type_id IS NULL)
                        AND (
                            payload->>'message_type' = 'ingest_file_package'
                            OR payload->>'decision_tracking_id' IS NOT NULL
                        )
                        OR
                        -- For type 2/3: only require decision_tracking_id
                        message_type_id IN (2, 3)
                        AND payload->>'decision_tracking_id' IS NOT NULL
                    )
                    AND (
                        created_at > :last_created_at
                        OR (created_at = :last_created_at AND message_id > :last_message_id)
                    )
                ORDER BY created_at ASC, message_id ASC
                LIMIT :batch_size
            """)
            
            result = db.execute(
                query,
                {
                    'last_created_at': watermark['last_created_at'],
                    'last_message_id': watermark['last_message_id'],
                    'batch_size': batch_size
                }
            ).fetchall()
            
            messages = []
            for row in result:
                messages.append({
                    'message_id': row[0],
                    'decision_tracking_id': str(row[1]),
                    'payload': row[2],
                    'created_at': row[3],
                    'channel_type_id': row[4] if len(row) > 4 else None,  # Can be None for backward compatibility
                    'message_type_id': row[5] if len(row) > 5 else None  # message_type_id from table
                })
            
            return messages
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error polling new messages: {e}", exc_info=True)
            raise
    
    def insert_into_inbox(
        self,
        message_id: int,
        decision_tracking_id: str,
        message_type: str,
        source_created_at: datetime,
        channel_type_id: Optional[int] = None,
        message_type_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Idempotently insert a message into inbox
        
        Args:
            message_id: Message ID from integration.send_serviceops
            decision_tracking_id: Decision tracking ID
            message_type: Message type from payload
            source_created_at: Created timestamp from source table
            channel_type_id: Channel type ID (1=Portal, 2=Fax, 3=ESMD), optional for backward compatibility
            message_type_id: Message type ID (1=intake, 2=UTN success, 3=UTN fail), optional for backward compatibility
            
        Returns:
            inbox_id if inserted, None if already exists (idempotent)
        """
        # Use fresh session for each insert to avoid transaction issues
        db = self._get_db(fresh=True)
        try:
            # Use message_id as idempotency key (from Stage 1 migration)
            result = db.execute(
                text("""
                    INSERT INTO service_ops.integration_inbox (
                        message_id,
                        decision_tracking_id,
                        message_type,
                        source_created_at,
                        status,
                        channel_type_id,
                        message_type_id
                    )
                    VALUES (
                        :message_id,
                        CAST(:decision_tracking_id AS UUID),
                        :message_type,
                        :source_created_at,
                        'NEW',
                        :channel_type_id,
                        :message_type_id
                    )
                    ON CONFLICT (message_id) DO NOTHING
                    RETURNING inbox_id
                """),
                {
                    'message_id': message_id,
                    'decision_tracking_id': str(decision_tracking_id),  # Ensure it's a string for UUID cast
                    'message_type': message_type,
                    'source_created_at': source_created_at,
                    'channel_type_id': channel_type_id,
                    'message_type_id': message_type_id
                }
            ).fetchone()
            
            if result:
                db.commit()
                return result[0]
            else:
                db.rollback()
                return None
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error inserting into inbox: {e}", exc_info=True)
            raise
    
    def claim_job(self, worker_id: str, stale_lock_minutes: int = 10) -> Optional[Dict[str, Any]]:
        """
        Atomically claim one eligible job for processing (multi-worker safe)
        
        Args:
            worker_id: Unique identifier for this worker
            stale_lock_minutes: Minutes after which a lock is considered stale
            
        Returns:
            Dict with job details if claimed, None if no jobs available
        """
        # Use fresh session for each claim
        db = self._get_db(fresh=True)
        try:
            # Use parameter substitution for interval
            result = db.execute(
                text(f"""
                    WITH claimed AS (
                        UPDATE service_ops.integration_inbox
                        SET 
                            status = 'PROCESSING',
                            locked_by = :worker_id,
                            locked_at = NOW(),
                            attempt_count = attempt_count + 1,
                            updated_at = NOW()
                        WHERE inbox_id = (
                            SELECT inbox_id
                            FROM service_ops.integration_inbox
                            WHERE status IN ('NEW', 'FAILED')
                                AND next_attempt_at <= NOW()
                                AND (
                                    locked_at IS NULL
                                    OR locked_at < NOW() - INTERVAL '{stale_lock_minutes} minutes'
                                )
                            ORDER BY source_created_at ASC, message_id ASC
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING *
                    )
                    SELECT 
                        inbox_id,
                        message_id,
                        decision_tracking_id,
                        message_type,
                        source_created_at,
                        status,
                        attempt_count,
                        locked_by,
                        locked_at,
                        channel_type_id,
                        message_type_id
                    FROM claimed
                """),
                {
                    'worker_id': worker_id
                }
            ).fetchone()
            
            if result:
                db.commit()
                return {
                    'inbox_id': result[0],
                    'message_id': result[1],
                    'decision_tracking_id': str(result[2]),
                    'message_type': result[3],
                    'source_created_at': result[4],
                    'status': result[5],
                    'attempt_count': result[6],
                    'locked_by': result[7],
                    'locked_at': result[8],
                    'channel_type_id': result[9] if len(result) > 9 else None,  # Can be None
                    'message_type_id': result[10] if len(result) > 10 else None  # Can be None
                }
            else:
                db.rollback()
                return None
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error claiming job: {e}", exc_info=True)
            raise
    
    def mark_done(self, inbox_id: int) -> bool:
        """
        Mark a job as successfully completed
        
        Args:
            inbox_id: Inbox ID of the completed job
            
        Returns:
            True if updated, False if not found
        """
        # Use fresh session
        db = self._get_db(fresh=True)
        try:
            result = db.execute(
                text("""
                    UPDATE service_ops.integration_inbox
                    SET 
                        status = 'DONE',
                        updated_at = NOW(),
                        locked_by = NULL,
                        locked_at = NULL,
                        last_error = NULL
                    WHERE inbox_id = :inbox_id
                """),
                {'inbox_id': inbox_id}
            )
            
            db.commit()
            return result.rowcount > 0
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error marking job as done: {e}", exc_info=True)
            raise
    
    def mark_failed(self, inbox_id: int, error_message: str) -> bool:
        """
        Mark a job as failed with exponential backoff retry
        
        Args:
            inbox_id: Inbox ID of the failed job
            error_message: Error message to store
            
        Returns:
            True if updated, False if not found
        """
        # Use fresh session
        db = self._get_db(fresh=True)
        try:
            # First get current attempt_count
            current = db.execute(
                text("""
                    SELECT attempt_count
                    FROM service_ops.integration_inbox
                    WHERE inbox_id = :inbox_id
                """),
                {'inbox_id': inbox_id}
            ).fetchone()
            
            if not current:
                return False
            
            attempt_count = current[0]
            
            # Calculate backoff interval
            if attempt_count == 0:
                backoff_interval = "1 minute"
            elif attempt_count == 1:
                backoff_interval = "5 minutes"
            elif attempt_count == 2:
                backoff_interval = "15 minutes"
            elif attempt_count == 3:
                backoff_interval = "1 hour"
            elif attempt_count == 4:
                backoff_interval = "6 hours"
            else:
                backoff_interval = "24 hours"  # Fallback
            
            # Determine if should be marked as DEAD
            new_status = 'DEAD' if attempt_count >= 5 else 'FAILED'
            
            result = db.execute(
                text(f"""
                    UPDATE service_ops.integration_inbox
                    SET 
                        status = :new_status,
                        last_error = :error_message,
                        next_attempt_at = CASE 
                            WHEN attempt_count >= 5 THEN next_attempt_at  -- Don't update if DEAD
                            ELSE NOW() + INTERVAL '{backoff_interval}'
                        END,
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = NOW()
                    WHERE inbox_id = :inbox_id
                """),
                {
                    'inbox_id': inbox_id,
                    'new_status': new_status,
                    'error_message': error_message[:1000]  # Limit error message length
                }
            )
            
            db.commit()
            return result.rowcount > 0
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error marking job as failed: {e}", exc_info=True)
            raise
    
    def update_watermark(self, max_created_at: datetime, max_message_id: int) -> None:
        """
        Update polling watermark after processing a batch
        
        Args:
            max_created_at: Maximum created_at timestamp from processed batch
            max_message_id: Maximum message_id from processed batch
        """
        # Use fresh session
        db = self._get_db(fresh=True)
        try:
            db.execute(
                text("""
                    INSERT INTO service_ops.integration_poll_watermark (
                        id,
                        last_created_at,
                        last_message_id,
                        updated_at
                    )
                    VALUES (1, :max_created_at, :max_message_id, NOW())
                    ON CONFLICT (id) 
                    DO UPDATE SET 
                        last_created_at = GREATEST(
                            service_ops.integration_poll_watermark.last_created_at,
                            EXCLUDED.last_created_at
                        ),
                        last_message_id = GREATEST(
                            service_ops.integration_poll_watermark.last_message_id,
                            EXCLUDED.last_message_id
                        ),
                        updated_at = NOW()
                """),
                {
                    'max_created_at': max_created_at,
                    'max_message_id': max_message_id
                }
            )
            db.commit()
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error updating watermark: {e}", exc_info=True)
            raise
    
    def get_source_message(self, message_id: int) -> Optional[SendServiceOpsDB]:
        """
        Get the original message from integration.send_serviceops
        
        Args:
            message_id: Message ID to fetch
            
        Returns:
            SendServiceOpsDB object or None
        """
        # Use fresh session
        db = self._get_db(fresh=True)
        try:
            return db.query(SendServiceOpsDB).filter(
                SendServiceOpsDB.message_id == message_id
            ).first()
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error getting source message: {e}", exc_info=True)
            raise
    
    def close(self):
        """Close database session"""
        if self._db and self._own_session:
            try:
                self._db.close()
            except Exception:
                pass
            finally:
                self._db = None

