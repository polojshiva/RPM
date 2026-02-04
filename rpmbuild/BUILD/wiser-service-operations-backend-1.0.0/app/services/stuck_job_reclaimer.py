"""
Stuck Job Reclaimer
Detects and recovers jobs stuck in PROCESSING status.
Runs periodically to reset stale locks.

Uses atomic batch-based updates for production safety:
- Single atomic UPDATE per batch (no SELECT then UPDATE per row)
- CTE-based candidates selection with RETURNING
- Atomic "claim" of max-attempts jobs before marking FAILED
"""
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.db import SessionLocal
from app.services.status_update_service import StatusUpdateService

logger = logging.getLogger(__name__)


class StuckJobReclaimer:
    """
    Service for detecting and recovering stuck jobs.
    
    A job is considered "stuck" if:
    - Status is PROCESSING
    - locked_at is older than stale_lock_minutes
    
    Recovery policy:
    - If attempt_count < max_attempts: Reset to NEW (retry)
    - Else: Mark as FAILED (max retries exceeded)
    """
    
    def __init__(
        self,
        stale_lock_minutes: int = 10,
        max_attempts: int = 5,
        batch_size: int = 200,
        status_update_service: Optional[StatusUpdateService] = None
    ):
        """
        Initialize stuck job reclaimer.
        
        Args:
            stale_lock_minutes: Minutes after which a lock is considered stale (default: 10)
            max_attempts: Maximum attempts before marking as FAILED (default: 5)
            batch_size: Maximum jobs to process per batch (default: 200)
            status_update_service: StatusUpdateService instance (creates new if None)
        """
        self.stale_lock_minutes = stale_lock_minutes
        self.max_attempts = max_attempts
        self.batch_size = batch_size
        self.status_update_service = status_update_service or StatusUpdateService()
        self.reclaimer_id = f"reclaimer:{uuid.uuid4().hex[:8]}"  # Unique ID for this reclaimer instance
    
    def detect_and_recover_stuck_jobs(self) -> Dict[str, Any]:
        """
        Detect and recover stuck jobs using atomic batch-based updates.
        
        Process:
        1. Count stale jobs (cheap COUNT query)
        2. Atomic batch reset-to-NEW (single UPDATE with CTE, single commit)
        3. Atomic claim of max-attempts jobs (single UPDATE with CTE, then mark_failed per job)
        
        Returns:
            Dict with recovery statistics:
            - detected: Number of stuck jobs detected
            - reset_to_new: Number reset to NEW
            - marked_failed: Number marked as FAILED
            - errors: Number of errors during recovery
        """
        stats = {
            'detected': 0,
            'reset_to_new': 0,
            'marked_failed': 0,
            'errors': 0
        }
        
        db: Optional[Session] = None
        try:
            db = SessionLocal()
            
            # Step A1: Count stale jobs for stats (cheap COUNT query)
            # Use parameterized interval to prevent SQL injection
            count_result = db.execute(
                text("""
                    SELECT COUNT(*)
                    FROM service_ops.integration_inbox
                    WHERE status = 'PROCESSING'
                      AND locked_at IS NOT NULL
                      AND locked_at < NOW() - INTERVAL '1 minute' * :stale_lock_minutes
                """),
                {'stale_lock_minutes': self.stale_lock_minutes}
            ).scalar()
            
            stats['detected'] = count_result or 0
            
            if stats['detected'] == 0:
                logger.debug("No stuck jobs detected")
                return stats
            
            logger.warning(
                f"Detected {stats['detected']} stuck job(s) in PROCESSING status "
                f"(locked_at older than {self.stale_lock_minutes} minutes)"
            )
            
            # Step A2: Atomic batch reset-to-NEW (single UPDATE with CTE, single commit)
            # Use parameterized interval and ensure FOR UPDATE SKIP LOCKED locks correctly
            reset_result = db.execute(
                text("""
                    WITH candidates AS (
                        SELECT inbox_id
                        FROM service_ops.integration_inbox
                        WHERE status = 'PROCESSING'
                          AND locked_at IS NOT NULL
                          AND locked_at < NOW() - INTERVAL '1 minute' * :stale_lock_minutes
                          AND attempt_count < :max_attempts
                        ORDER BY locked_at ASC
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE service_ops.integration_inbox
                    SET 
                        status = 'NEW',
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = NOW()
                    FROM candidates
                    WHERE integration_inbox.inbox_id = candidates.inbox_id
                      AND integration_inbox.status = 'PROCESSING'
                      AND integration_inbox.locked_at < NOW() - INTERVAL '1 minute' * :stale_lock_minutes
                    RETURNING 
                        integration_inbox.inbox_id,
                        integration_inbox.attempt_count,
                        integration_inbox.locked_at,
                        integration_inbox.decision_tracking_id
                """),
                {
                    'stale_lock_minutes': self.stale_lock_minutes,
                    'max_attempts': self.max_attempts,
                    'batch_size': self.batch_size
                }
            ).fetchall()
            
            if reset_result:
                db.commit()  # Single commit for entire batch
                stats['reset_to_new'] = len(reset_result)
                logger.info(
                    f"✓ Batch reset {stats['reset_to_new']} stuck job(s) to NEW "
                    f"(atomic update, single commit)"
                )
                # Log individual jobs at debug level (no PHI)
                for row in reset_result:
                    logger.debug(
                        f"Reset job: inbox_id={row[0]}, attempt_count={row[1]}, "
                        f"decision_tracking_id={row[3]}"
                    )
            else:
                db.rollback()
            
            # Step A3: Atomic claim of "mark FAILED" candidates
            # First, atomically claim jobs that exceed max attempts
            # Use parameterized interval and ensure FOR UPDATE SKIP LOCKED locks correctly
            failed_candidates = db.execute(
                text("""
                    WITH candidates AS (
                        SELECT inbox_id, attempt_count, locked_at, decision_tracking_id
                        FROM service_ops.integration_inbox
                        WHERE status = 'PROCESSING'
                          AND locked_at IS NOT NULL
                          AND locked_at < NOW() - INTERVAL '1 minute' * :stale_lock_minutes
                          AND attempt_count >= :max_attempts
                          AND (locked_by IS NULL OR locked_by NOT LIKE 'reclaimer:%')
                        ORDER BY locked_at ASC
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE service_ops.integration_inbox
                    SET 
                        locked_by = :reclaimer_id,
                        updated_at = NOW()
                    FROM candidates
                    WHERE integration_inbox.inbox_id = candidates.inbox_id
                      AND integration_inbox.status = 'PROCESSING'
                      AND integration_inbox.locked_at < NOW() - INTERVAL '1 minute' * :stale_lock_minutes
                      AND integration_inbox.attempt_count >= :max_attempts
                      AND (integration_inbox.locked_by IS NULL OR integration_inbox.locked_by NOT LIKE 'reclaimer:%')
                    RETURNING 
                        candidates.inbox_id,
                        candidates.attempt_count,
                        candidates.locked_at,
                        candidates.decision_tracking_id
                """),
                {
                    'stale_lock_minutes': self.stale_lock_minutes,
                    'max_attempts': self.max_attempts,
                    'batch_size': self.batch_size,
                    'reclaimer_id': self.reclaimer_id
                }
            ).fetchall()
            
            if failed_candidates:
                db.commit()  # Commit the claim
                logger.info(
                    f"✓ Atomically claimed {len(failed_candidates)} job(s) for FAILED marking "
                    f"(reclaimer_id={self.reclaimer_id})"
                )
                
                # Now mark each as FAILED using StatusUpdateService
                for row in failed_candidates:
                    inbox_id = row[0]
                    attempt_count = row[1]
                    locked_at = row[2]
                    decision_tracking_id = str(row[3])
                    
                    try:
                        error_msg = (
                            f"Stuck in PROCESSING for > {self.stale_lock_minutes} minutes "
                            f"(locked_at={locked_at}). Max attempts ({self.max_attempts}) exceeded."
                        )
                        
                        # Use status update service for guaranteed update
                        result = self.status_update_service.mark_failed_with_retry(
                            inbox_id=inbox_id,
                            error_message=error_msg,
                            attempt_count=attempt_count
                        )
                        
                        if result.success:
                            stats['marked_failed'] += 1
                            logger.warning(
                                f"⚠ Marked stuck job as FAILED: inbox_id={inbox_id}, "
                                f"attempt_count={attempt_count}, decision_tracking_id={decision_tracking_id}"
                            )
                        else:
                            stats['errors'] += 1
                            logger.error(
                                f"✗ Failed to mark stuck job as FAILED after {result.attempts} attempts: "
                                f"inbox_id={inbox_id}, error={result.error}",
                                exc_info=True
                            )
                            # Job remains claimed by this reclaimer - will be retried by next reclaimer run
                            # (locked_by='reclaimer:...' prevents other reclaimers from claiming it)
                    
                    except Exception as e:
                        stats['errors'] += 1
                        logger.error(
                            f"Error marking stuck job as FAILED: inbox_id={inbox_id}, error={e}",
                            exc_info=True
                        )
                        # Do NOT throw - reclaimer must finish its scan
                        # Job remains claimed - will be retried by next reclaimer run
            else:
                db.rollback()
            
            if stats['detected'] > 0:
                logger.info(
                    f"Stuck job recovery completed: detected={stats['detected']}, "
                    f"reset_to_new={stats['reset_to_new']}, "
                    f"marked_failed={stats['marked_failed']}, "
                    f"errors={stats['errors']}"
                )
            
            return stats
            
        except Exception as e:
            logger.error(f"Error in detect_and_recover_stuck_jobs: {e}", exc_info=True)
            stats['errors'] += 1
            return stats
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

