"""
Background Task Leader Election
Ensures only ONE instance of background tasks runs across multiple Gunicorn workers.

Uses database-based leader election with heartbeat mechanism.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import text
from app.services.db import SessionLocal

logger = logging.getLogger(__name__)

# Leader election settings
LEADER_HEARTBEAT_INTERVAL_SECONDS = 30  # Update heartbeat every 30s
LEADER_STALE_THRESHOLD_SECONDS = 90  # Consider leader stale after 90s without heartbeat
LEADER_LOCK_TABLE = "service_ops.background_task_leader"


class BackgroundTaskLeader:
    """
    Database-based leader election for background tasks.
    Ensures only ONE instance of background tasks runs across all Gunicorn workers.
    """
    
    def __init__(self, task_name: str):
        """
        Initialize leader election for a specific task.
        
        Args:
            task_name: Unique name for the task (e.g., 'message_poller', 'clinical_ops_processor')
        """
        self.task_name = task_name
        self.worker_id = f"{task_name}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.is_leader = False
        self.heartbeat_task: Optional[asyncio.Task] = None
        self._ensure_table_exists()
    
    def _table_exists(self) -> bool:
        """Check if the leader election table exists"""
        db = SessionLocal()
        try:
            result = db.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'service_ops' 
                    AND table_name = 'background_task_leader'
                )
            """)).scalar()
            return bool(result)
        except Exception as e:
            logger.debug(f"Error checking if table exists: {e}")
            return False
        finally:
            db.close()
    
    def _ensure_table_exists(self):
        """Ensure the leader election table exists"""
        # First check if table exists
        if self._table_exists():
            logger.debug(f"Leader election table exists for task: {self.task_name}")
            return
        
        # Table doesn't exist - try to create it
        db = SessionLocal()
        try:
            db.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {LEADER_LOCK_TABLE} (
                    task_name VARCHAR(100) PRIMARY KEY,
                    worker_id VARCHAR(200) NOT NULL,
                    heartbeat_at TIMESTAMP NOT NULL,
                    elected_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            db.commit()
            logger.info(f"✅ Created leader election table for task: {self.task_name}")
        except Exception as e:
            db.rollback()
            # Check if it's a permission error
            error_str = str(e).lower()
            if 'permission' in error_str or 'privilege' in error_str:
                logger.error(
                    f"❌ CRITICAL: Cannot create leader election table - insufficient database permissions. "
                    f"Please run migration 025_create_background_task_leader_table.sql as a database administrator. "
                    f"Background tasks will not start until this table exists. Error: {e}"
                )
            else:
                logger.error(f"Failed to ensure leader table exists: {e}", exc_info=True)
        finally:
            db.close()
    
    async def try_become_leader(self) -> bool:
        """
        Try to become the leader for this task.
        Uses database-based atomic operation to ensure only one leader.
        
        Returns:
            True if this instance became the leader, False otherwise
        """
        # Check if table exists first
        if not self._table_exists():
            logger.error(
                f"❌ CRITICAL: Leader election table does not exist. "
                f"Please run migration 025_create_background_task_leader_table.sql. "
                f"Background task '{self.task_name}' cannot start without this table."
            )
            return False
        
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            stale_threshold = now - timedelta(seconds=LEADER_STALE_THRESHOLD_SECONDS)
            
            # Strategy: Try to update if leader is stale, otherwise try to insert
            # First, try to take over from stale leader
            update_result = db.execute(
                text(f"""
                    UPDATE {LEADER_LOCK_TABLE}
                    SET 
                        worker_id = :worker_id,
                        heartbeat_at = :heartbeat_at,
                        elected_at = :elected_at,
                        updated_at = NOW()
                    WHERE task_name = :task_name 
                      AND heartbeat_at < :stale_threshold
                    RETURNING worker_id, heartbeat_at
                """),
                {
                    'task_name': self.task_name,
                    'worker_id': self.worker_id,
                    'heartbeat_at': now,
                    'elected_at': now,
                    'stale_threshold': stale_threshold
                }
            ).fetchone()
            
            if update_result and update_result[0] == self.worker_id:
                # Successfully took over from stale leader
                db.commit()
                self.is_leader = True
                logger.info(
                    f"✅ Became leader for {self.task_name} by taking over from stale leader "
                    f"(worker_id={self.worker_id})"
                )
                
                # Start heartbeat task
                if self.heartbeat_task is None or self.heartbeat_task.done():
                    self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    
                    # Add exception handler to prevent unhandled exceptions from crashing
                    def handle_heartbeat_exception(task: asyncio.Task):
                        """Handle unhandled exceptions in heartbeat task"""
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            pass  # Expected during shutdown
                        except Exception as e:
                            logger.error(
                                f"CRITICAL: Unhandled exception in heartbeat task for {self.task_name}: {e}. "
                                f"Leadership will be lost but worker will continue.",
                                exc_info=True
                            )
                            self.is_leader = False
                    
                    self.heartbeat_task.add_done_callback(handle_heartbeat_exception)
                
                return True
            
            # No stale leader - check if there's an active leader
            current_leader = db.execute(
                text(f"""
                    SELECT worker_id, heartbeat_at
                    FROM {LEADER_LOCK_TABLE}
                    WHERE task_name = :task_name
                """),
                {'task_name': self.task_name}
            ).fetchone()
            
            if current_leader:
                # Active leader exists
                heartbeat_age = (now - current_leader[1]).total_seconds() if isinstance(current_leader[1], datetime) else 999
                if heartbeat_age < LEADER_STALE_THRESHOLD_SECONDS:
                    # Active leader is not stale - no transaction to rollback (SELECT is read-only)
                    self.is_leader = False
                    logger.debug(
                        f"Not leader for {self.task_name} - active leader: {current_leader[0]} "
                        f"(heartbeat age: {heartbeat_age:.1f}s)"
                    )
                    return False
            
            # No active leader - try to insert (atomic operation protected by PRIMARY KEY)
            try:
                insert_result = db.execute(
                    text(f"""
                        INSERT INTO {LEADER_LOCK_TABLE} (task_name, worker_id, heartbeat_at, elected_at)
                        VALUES (:task_name, :worker_id, :heartbeat_at, :elected_at)
                        RETURNING worker_id, heartbeat_at
                    """),
                    {
                        'task_name': self.task_name,
                        'worker_id': self.worker_id,
                        'heartbeat_at': now,
                        'elected_at': now
                    }
                ).fetchone()
                
                db.commit()
                
                # INSERT succeeded - we are the leader (PRIMARY KEY constraint ensures only one)
                if insert_result and insert_result[0] == self.worker_id:
                    self.is_leader = True
                    logger.info(
                        f"✅ Became leader for {self.task_name} (no existing leader, worker_id={self.worker_id})"
                    )
                    
                    # Start heartbeat task
                    if self.heartbeat_task is None or self.heartbeat_task.done():
                        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    
                    return True
                else:
                    # Should never happen - INSERT succeeded but worker_id doesn't match
                    # This indicates a logic error, but handle gracefully
                    logger.error(
                        f"CRITICAL: INSERT succeeded but worker_id mismatch for {self.task_name} "
                        f"(expected: {self.worker_id}, got: {insert_result[0] if insert_result else None})"
                    )
                    self.is_leader = False
                    return False
                    
            except Exception as insert_error:
                # Insert failed - could be unique constraint violation (another worker is leader)
                # or other database error
                db.rollback()
                
                # Re-check who the current leader is (if any)
                try:
                    final_check = db.execute(
                        text(f"""
                            SELECT worker_id, heartbeat_at
                            FROM {LEADER_LOCK_TABLE}
                            WHERE task_name = :task_name
                        """),
                        {'task_name': self.task_name}
                    ).fetchone()
                    
                    self.is_leader = False
                    if final_check:
                        logger.debug(
                            f"Not leader for {self.task_name} - another worker is leader: {final_check[0]}"
                        )
                    else:
                        logger.warning(
                            f"Insert failed for {self.task_name} but no leader found: {insert_error}"
                        )
                except Exception as check_error:
                    logger.error(
                        f"Error checking leader after insert failure for {self.task_name}: {check_error}",
                        exc_info=True
                    )
                
                return False
                
        except Exception as e:
            db.rollback()
            error_str = str(e).lower()
            if 'does not exist' in error_str or 'undefinedtable' in error_str or 'relation' in error_str:
                logger.error(
                    f"❌ CRITICAL: Leader election table does not exist. "
                    f"Please run migration 025_create_background_task_leader_table.sql. "
                    f"Background task '{self.task_name}' cannot start without this table. Error: {e}"
                )
            else:
                logger.error(f"Error in leader election for {self.task_name}: {e}", exc_info=True)
            return False
        finally:
            db.close()
    
    async def _heartbeat_loop(self):
        """Continuously update heartbeat with connection pool awareness"""
        consecutive_failures = 0  # For DB errors
        consecutive_pool_skips = 0  # For pool exhaustion skips
        max_pool_skips = 10  # Max 10 consecutive skips before warning
        
        while self.is_leader:
            try:
                await asyncio.sleep(LEADER_HEARTBEAT_INTERVAL_SECONDS)
                
                if not self.is_leader:
                    break
                
                # Check connection pool before heartbeat
                pool_critical = False
                try:
                    from app.services.connection_pool_monitor import get_pool_usage
                    pool_usage = get_pool_usage()
                    
                    if pool_usage['usage_percent'] > 0.95:
                        pool_critical = True
                        consecutive_pool_skips += 1
                        logger.warning(
                            f"Connection pool critical ({pool_usage['usage_percent']:.1%}) - "
                            f"skipping heartbeat to preserve connections for {self.task_name}. "
                            f"Skip count: {consecutive_pool_skips}/{max_pool_skips}. "
                            f"This is safe - heartbeat will resume when pool recovers."
                        )
                        
                        if consecutive_pool_skips >= max_pool_skips:
                            logger.error(
                                f"CRITICAL: Skipped {consecutive_pool_skips} consecutive heartbeats "
                                f"for {self.task_name} due to pool exhaustion. "
                                f"Leadership may be lost. Check connection pool configuration."
                            )
                        continue
                except ImportError:
                    # Connection pool monitor not available - proceed with heartbeat
                    pass
                except Exception as pool_check_error:
                    # Log but don't fail heartbeat if pool check fails
                    logger.debug(f"Error checking connection pool: {pool_check_error}")
                
                # Reset skip counter on successful pool check
                if not pool_critical:
                    consecutive_pool_skips = 0
                
                # Update heartbeat
                db = SessionLocal()
                try:
                    now = datetime.utcnow()
                    result = db.execute(
                        text(f"""
                            UPDATE {LEADER_LOCK_TABLE}
                            SET heartbeat_at = :heartbeat_at, updated_at = NOW()
                            WHERE task_name = :task_name AND worker_id = :worker_id
                            RETURNING worker_id
                        """),
                        {
                            'task_name': self.task_name,
                            'worker_id': self.worker_id,
                            'heartbeat_at': now
                        }
                    ).fetchone()
                    
                    db.commit()
                    
                    if not result or result[0] != self.worker_id:
                        # Lost leadership (another worker took over)
                        logger.warning(
                            f"⚠️ Lost leadership for {self.task_name} (worker_id={self.worker_id})"
                        )
                        self.is_leader = False
                        break
                    
                    # Reset failure counters on successful heartbeat
                    consecutive_failures = 0
                    consecutive_pool_skips = 0
                    
                except Exception as e:
                    db.rollback()
                    consecutive_failures += 1
                    
                    # Exponential backoff for DB errors
                    backoff_delay = min(
                        LEADER_HEARTBEAT_INTERVAL_SECONDS * (2 ** min(consecutive_failures, 4)),
                        300  # Max 5 minutes
                    )
                    
                    error_str = str(e).lower()
                    if 'does not exist' in error_str or 'undefinedtable' in error_str or 'relation' in error_str:
                        logger.error(
                            f"❌ CRITICAL: Leader election table does not exist during heartbeat. "
                            f"Please run migration 025_create_background_task_leader_table.sql. "
                            f"Leadership lost for {self.task_name}."
                        )
                        self.is_leader = False
                        break
                    else:
                        logger.error(
                            f"Error updating heartbeat for {self.task_name} (attempt {consecutive_failures}): {e}. "
                            f"Retrying in {backoff_delay}s. "
                            f"If database is unavailable, leadership will be lost after {LEADER_STALE_THRESHOLD_SECONDS}s.",
                            exc_info=True
                        )
                        await asyncio.sleep(backoff_delay)
                finally:
                    db.close()
                    
            except asyncio.CancelledError:
                logger.info(f"Heartbeat loop cancelled for {self.task_name}")
                break
            except Exception as e:
                logger.error(f"Unexpected error in heartbeat loop for {self.task_name}: {e}", exc_info=True)
                # Wait before retrying to avoid tight error loop
                await asyncio.sleep(LEADER_HEARTBEAT_INTERVAL_SECONDS)
    
    async def release_leadership(self):
        """Release leadership (cleanup on shutdown)"""
        if not self.is_leader:
            return
        
        self.is_leader = False
        
        # Cancel heartbeat task
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Remove from database (only if we're still the leader)
        db = SessionLocal()
        try:
            db.execute(
                text(f"""
                    DELETE FROM {LEADER_LOCK_TABLE}
                    WHERE task_name = :task_name AND worker_id = :worker_id
                """),
                {
                    'task_name': self.task_name,
                    'worker_id': self.worker_id
                }
            )
            db.commit()
            logger.info(f"Released leadership for {self.task_name} (worker_id={self.worker_id})")
        except Exception as e:
            db.rollback()
            error_str = str(e).lower()
            if 'does not exist' in error_str or 'undefinedtable' in error_str or 'relation' in error_str:
                logger.warning(
                    f"Leader election table does not exist during release (migration may not be run). "
                    f"Task: {self.task_name}"
                )
            else:
                logger.error(f"Error releasing leadership for {self.task_name}: {e}", exc_info=True)
        finally:
            db.close()
    
    def check_leadership(self) -> bool:
        """Check if this instance is still the leader (synchronous check)"""
        if not self.is_leader:
            return False
        
        db = SessionLocal()
        try:
            result = db.execute(
                text(f"""
                    SELECT worker_id, heartbeat_at
                    FROM {LEADER_LOCK_TABLE}
                    WHERE task_name = :task_name
                """),
                {'task_name': self.task_name}
            ).fetchone()
            
            if result and result[0] == self.worker_id:
                # Check if heartbeat is recent
                heartbeat_at = result[1]
                if isinstance(heartbeat_at, datetime):
                    age = (datetime.utcnow() - heartbeat_at).total_seconds()
                    if age < LEADER_STALE_THRESHOLD_SECONDS:
                        return True
            
            # Lost leadership
            self.is_leader = False
            return False
            
        except Exception as e:
            error_str = str(e).lower()
            if 'does not exist' in error_str or 'undefinedtable' in error_str or 'relation' in error_str:
                logger.warning(
                    f"Leader election table does not exist during leadership check (migration may not be run). "
                    f"Task: {self.task_name}"
                )
            else:
                logger.error(f"Error checking leadership for {self.task_name}: {e}", exc_info=True)
            return False
        finally:
            db.close()
