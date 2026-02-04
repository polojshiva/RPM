"""
Reset message 271 to NEW status so it can be reprocessed with the MIME type fix
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def reset_message():
    """Reset message 271 to NEW status"""
    logger.info("=" * 80)
    logger.info("RESETTING MESSAGE 271 TO NEW STATUS")
    logger.info("=" * 80)
    
    try:
        with engine.connect() as conn:
            # Reset inbox record
            result = conn.execute(text("""
                UPDATE service_ops.integration_inbox
                SET 
                    status = 'NEW',
                    attempt_count = 0,
                    next_attempt_at = NOW(),
                    locked_by = NULL,
                    locked_at = NULL,
                    last_error = NULL,
                    updated_at = NOW()
                WHERE message_id = 271
                RETURNING inbox_id, status, attempt_count
            """))
            
            updated = result.fetchone()
            if updated:
                logger.info(f"✓ Reset inbox record:")
                logger.info(f"    inbox_id: {updated[0]}")
                logger.info(f"    status: {updated[1]}")
                logger.info(f"    attempt_count: {updated[2]}")
            else:
                logger.warning("⚠ No inbox record found for message_id=271")
            
            conn.commit()
            
            logger.info("\n✓ Message 271 has been reset to NEW status")
            logger.info("  The message poller will pick it up and process it with the MIME type fix")
            logger.info("")
            
    except Exception as e:
        logger.error(f"Error resetting message: {e}", exc_info=True)


if __name__ == "__main__":
    reset_message()






