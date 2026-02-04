"""
Script to run migration 010 and cleanup database for channel testing
- Runs migration: Add channel_type_id to integration_inbox
- Cleans all related tables (packet, packet_document, integration_inbox, etc.)
- Keeps only 3 test records in send_serviceops (message_id 270, 271, 272)
"""
import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import SessionLocal, engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Run migration 010: Add channel_type_id to integration_inbox"""
    logger.info("=" * 80)
    logger.info("Running Migration 010: Add channel_type_id to integration_inbox")
    logger.info("=" * 80)
    
    migration_sql = """
    BEGIN;

    -- Add channel_type_id column to integration_inbox
    ALTER TABLE service_ops.integration_inbox
    ADD COLUMN IF NOT EXISTS channel_type_id BIGINT;

    -- Add index for channel_type_id lookups
    CREATE INDEX IF NOT EXISTS idx_integration_inbox_channel_type_id 
        ON service_ops.integration_inbox(channel_type_id)
        WHERE channel_type_id IS NOT NULL;

    -- Add comment
    COMMENT ON COLUMN service_ops.integration_inbox.channel_type_id IS 
        'Channel type ID: 1=Genzeon Portal, 2=Genzeon Fax, 3=ESMD. NULL for backward compatibility with old messages.';

    COMMIT;
    """
    
    try:
        with engine.connect() as conn:
            conn.execute(text(migration_sql))
            conn.commit()
        logger.info("✓ Migration 010 completed successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Migration 010 failed: {e}", exc_info=True)
        return False


def cleanup_tables():
    """Clean all related tables, keeping only 3 test records in send_serviceops"""
    logger.info("=" * 80)
    logger.info("Cleaning database tables for channel testing")
    logger.info("=" * 80)
    
    cleanup_sql = """
    BEGIN;

    -- Clear service_ops tables (in dependency order)
    DELETE FROM service_ops.packet_decision;
    DELETE FROM service_ops.validation_run;
    DELETE FROM service_ops.packet_document;
    DELETE FROM service_ops.packet;
    DELETE FROM service_ops.integration_inbox;

    -- Reset watermark to start fresh
    UPDATE service_ops.integration_poll_watermark
    SET 
        last_created_at = '1970-01-01 00:00:00',
        last_message_id = 0,
        updated_at = NOW()
    WHERE id = 1;

    -- Clean integration.send_serviceops - Keep only 3 test records
    DELETE FROM integration.send_serviceops
    WHERE message_id NOT IN (270, 271, 272);

    COMMIT;
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(cleanup_sql))
            conn.commit()
        logger.info("✓ Database cleanup completed successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Database cleanup failed: {e}", exc_info=True)
        return False


def verify_cleanup():
    """Verify cleanup was successful"""
    logger.info("=" * 80)
    logger.info("Verifying cleanup results")
    logger.info("=" * 80)
    
    verification_queries = {
        "packet": "SELECT COUNT(*) FROM service_ops.packet",
        "packet_document": "SELECT COUNT(*) FROM service_ops.packet_document",
        "integration_inbox": "SELECT COUNT(*) FROM service_ops.integration_inbox",
        "send_serviceops": "SELECT COUNT(*) FROM integration.send_serviceops WHERE is_deleted = false",
        "send_serviceops_details": """
            SELECT message_id, channel_type_id, decision_tracking_id 
            FROM integration.send_serviceops 
            WHERE is_deleted = false 
            ORDER BY message_id
        """
    }
    
    try:
        with engine.connect() as conn:
            # Check counts
            for table_name, query in verification_queries.items():
                if table_name == "send_serviceops_details":
                    continue
                result = conn.execute(text(query))
                count = result.scalar()
                logger.info(f"  {table_name}: {count} records")
                
                # Verify send_serviceops has exactly 3 records
                if table_name == "send_serviceops":
                    if count != 3:
                        logger.error(f"✗ Expected 3 records in send_serviceops, found {count}")
                        return False
                    else:
                        logger.info(f"✓ Verified: 3 records in send_serviceops")
            
            # Show details of the 3 records
            logger.info("\n  send_serviceops records:")
            result = conn.execute(text(verification_queries["send_serviceops_details"]))
            for row in result:
                logger.info(f"    message_id={row[0]}, channel_type_id={row[1]}, decision_tracking_id={row[2]}")
        
        logger.info("\n✓ Verification completed successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Verification failed: {e}", exc_info=True)
        return False


def main():
    """Main execution"""
    logger.info("\n" + "=" * 80)
    logger.info("MIGRATION AND CLEANUP SCRIPT FOR CHANNEL TESTING")
    logger.info("=" * 80 + "\n")
    
    # Step 1: Run migration
    if not run_migration():
        logger.error("Migration failed. Aborting.")
        return False
    
    logger.info("")
    
    # Step 2: Cleanup tables
    if not cleanup_tables():
        logger.error("Cleanup failed. Aborting.")
        return False
    
    logger.info("")
    
    # Step 3: Verify cleanup
    if not verify_cleanup():
        logger.error("Verification failed.")
        return False
    
    logger.info("\n" + "=" * 80)
    logger.info("✓ ALL OPERATIONS COMPLETED SUCCESSFULLY")
    logger.info("=" * 80)
    logger.info("\nDatabase is ready for channel testing:")
    logger.info("  - Migration 010 applied (channel_type_id added to integration_inbox)")
    logger.info("  - All related tables cleaned")
    logger.info("  - Only 3 test records remain in send_serviceops:")
    logger.info("    * message_id=270 (ESMD, channel_type_id=3)")
    logger.info("    * message_id=271 (Genzeon Fax, channel_type_id=2)")
    logger.info("    * message_id=272 (Genzeon Portal, channel_type_id=1)")
    logger.info("\nThe system will now process these 3 messages through different workflows.\n")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)






