"""
Status Update Service
Guarantees that status updates never fail silently.
Uses fresh DB sessions and retries with exponential backoff.
"""
import logging
import time
from typing import Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.db import SessionLocal

logger = logging.getLogger(__name__)


class StatusUpdateResult:
    """Result of a status update operation"""
    def __init__(self, success: bool, attempts: int = 0, dlq: bool = False, error: Optional[str] = None):
        self.success = success
        self.attempts = attempts
        self.dlq = dlq  # Sent to dead letter queue
        self.error = error


class StatusUpdateService:
    """
    Service for guaranteed status updates.
    
    Features:
    - Uses fresh DB session for each attempt
    - Retries with exponential backoff
    - Never fails silently
    - Logs loudly on failure
    """
    
    def __init__(self, max_retries: int = 10):
        """
        Initialize status update service.
        
        Args:
            max_retries: Maximum number of retry attempts (default: 10)
        """
        self.max_retries = max_retries
    
    def _backoff_interval_to_minutes(self, interval_str: str) -> int:
        """
        Convert backoff interval string to minutes for parameterized query.
        Safe because interval_str is controlled by our code, not user input.
        """
        import re
        if 'minute' in interval_str.lower():
            # Extract number (e.g., "1 minute" -> 1, "5 minutes" -> 5)
            match = re.search(r'(\d+)', interval_str)
            if match:
                return int(match.group(1))
        elif 'hour' in interval_str.lower():
            # Extract number and convert to minutes (e.g., "1 hour" -> 60, "6 hours" -> 360)
            match = re.search(r'(\d+)', interval_str)
            if match:
                return int(match.group(1)) * 60
        # Default fallback (should not happen with our controlled strings)
        return 1
    
    def mark_done_with_retry(self, inbox_id: int) -> StatusUpdateResult:
        """
        Mark a job as done with guaranteed retry.
        
        Args:
            inbox_id: Inbox ID of the completed job
            
        Returns:
            StatusUpdateResult indicating success or failure
        """
        return self._update_status_with_retry(
            inbox_id=inbox_id,
            target_status='DONE',
            error_message=None
        )
    
    def mark_failed_with_retry(
        self,
        inbox_id: int,
        error_message: str,
        attempt_count: Optional[int] = None
    ) -> StatusUpdateResult:
        """
        Mark a job as failed with guaranteed retry.
        
        Args:
            inbox_id: Inbox ID of the failed job
            error_message: Error message to store
            attempt_count: Optional attempt count (if None, will be fetched)
            
        Returns:
            StatusUpdateResult indicating success or failure
        """
        return self._update_status_with_retry(
            inbox_id=inbox_id,
            target_status='FAILED',
            error_message=error_message,
            attempt_count=attempt_count
        )
    
    def _update_status_with_retry(
        self,
        inbox_id: int,
        target_status: str,
        error_message: Optional[str],
        attempt_count: Optional[int] = None
    ) -> StatusUpdateResult:
        """
        Update inbox status with retry logic.
        
        Args:
            inbox_id: Inbox ID
            target_status: Target status ('DONE' or 'FAILED')
            error_message: Error message (for FAILED status)
            attempt_count: Optional attempt count (for FAILED status)
            
        Returns:
            StatusUpdateResult
        """
        last_error = None
        last_exception = None  # Store original exception for full stack trace logging
        
        for attempt in range(1, self.max_retries + 1):
            # Use fresh session for each attempt
            db: Optional[Session] = None
            try:
                db = SessionLocal()
                
                if target_status == 'FAILED':
                    # For FAILED, we need to calculate backoff and determine if DEAD
                    if attempt_count is None:
                        # Fetch current attempt_count
                        current = db.execute(
                            text("""
                                SELECT attempt_count
                                FROM service_ops.integration_inbox
                                WHERE inbox_id = :inbox_id
                            """),
                            {'inbox_id': inbox_id}
                        ).fetchone()
                        
                        if not current:
                            db.close()
                            return StatusUpdateResult(
                                success=False,
                                attempts=attempt,
                                error=f"Inbox ID {inbox_id} not found"
                            )
                        
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
                        backoff_interval = "24 hours"
                    
                    # Determine if should be marked as DEAD
                    new_status = 'DEAD' if attempt_count >= 5 else 'FAILED'
                    
                    # Update with backoff
                    # Use parameterized interval to prevent SQL injection
                    # Note: PostgreSQL doesn't support parameterized INTERVAL directly,
                    # but backoff_interval is a controlled string from our logic, not user input
                    # We use make_interval() for safety
                    result = db.execute(
                        text("""
                            UPDATE service_ops.integration_inbox
                            SET 
                                status = :new_status,
                                last_error = :error_message,
                                next_attempt_at = CASE 
                                    WHEN attempt_count >= 5 THEN next_attempt_at
                                    ELSE NOW() + make_interval(mins => :backoff_minutes)
                                END,
                                locked_by = NULL,
                                locked_at = NULL,
                                updated_at = NOW()
                            WHERE inbox_id = :inbox_id
                        """),
                        {
                            'inbox_id': inbox_id,
                            'new_status': new_status,
                            'error_message': (error_message or '')[:1000],  # Limit length
                            'backoff_minutes': self._backoff_interval_to_minutes(backoff_interval)
                        }
                    )
                else:
                    # For DONE status
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
                
                if result.rowcount > 0:
                    logger.info(
                        f"✓ Status update SUCCESS: inbox_id={inbox_id}, "
                        f"status={target_status}, attempts={attempt}"
                    )
                    return StatusUpdateResult(success=True, attempts=attempt)
                else:
                    # Row not found
                    db.close()
                    return StatusUpdateResult(
                        success=False,
                        attempts=attempt,
                        error=f"Inbox ID {inbox_id} not found"
                    )
                    
            except Exception as e:
                last_error = str(e)
                last_exception = e  # Store exception object for full stack trace
                error_msg = f"Status update attempt {attempt}/{self.max_retries} failed: {e}"
                
                if attempt < self.max_retries:
                    # Exponential backoff: 2^(attempt-1) seconds
                    wait_time = 2 ** (attempt - 1)
                    logger.warning(
                        f"Status update failed (attempt {attempt}/{self.max_retries}): {error_msg}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    # All retries failed
                    logger.error(
                        f"✗ Status update FAILED after {self.max_retries} attempts: "
                        f"inbox_id={inbox_id}, target_status={target_status}, error={last_error}",
                        exc_info=True
                    )
                
                # Clean up session
                if db:
                    try:
                        db.rollback()
                        db.close()
                    except Exception:
                        pass
                    db = None
        
        # All retries failed - log loudly with full stack trace
        logger.critical(
            f"🚨 CRITICAL: Status update FAILED after {self.max_retries} attempts. "
            f"Inbox ID {inbox_id} may be stuck in PROCESSING. "
            f"Target status: {target_status}, Last error: {last_error}",
            exc_info=last_exception  # Log full stack trace of original exception
        )
        
        # Job will be reclaimed by StuckJobReclaimer (runs every 5 poll cycles)
        # Reclaimer will detect it as stuck (locked_at > stale_lock_minutes) and reset to NEW or mark FAILED
        logger.warning(
            f"Job {inbox_id} will be reclaimed by StuckJobReclaimer "
            f"(runs every 5 poll cycles, threshold: 10 minutes). "
            f"Job will be retried or marked as FAILED based on attempt_count."
        )
        
        # TODO: Send alert (email, PagerDuty, etc.) if needed
        # For now, reclaimer will handle it automatically
        
        return StatusUpdateResult(
            success=False,
            attempts=self.max_retries,
            dlq=True,  # Would send to DLQ if we had one
            error=last_error
        )

