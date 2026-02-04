"""
Clean all ServiceOps processing tables, keeping all records in integration.send_serviceops
This allows reprocessing all messages from scratch to test the three channel types
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine, get_db_session
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def clean_all_tables():
    """Clean all processing tables, keeping all records in send_serviceops"""
    logger.info("=" * 80)
    logger.info("CLEANING ALL SERVICEOPS TABLES")
    logger.info("Keeping all records in integration.send_serviceops for reprocessing")
    logger.info("=" * 80)
    
    try:
        with get_db_session() as db:
            # Step 1: Clean all service_ops tables (in dependency order)
            logger.info("\n1. Cleaning service_ops tables...")
            
            cleanup_queries = [
                ("packet_decision", "DELETE FROM service_ops.packet_decision"),
                ("validation_run", "DELETE FROM service_ops.validation_run"),
                ("packet_document", "DELETE FROM service_ops.packet_document"),
                ("packet", "DELETE FROM service_ops.packet"),
                ("integration_inbox", "DELETE FROM service_ops.integration_inbox"),
            ]
            
            for table_name, query in cleanup_queries:
                result = db.execute(text(query))
                deleted_count = result.rowcount
                logger.info(f"  ✓ Cleaned {table_name}: {deleted_count} records deleted")
            
            # Reset watermark to start fresh
            logger.info("\n2. Resetting poll watermark...")
            db.execute(text("""
                UPDATE service_ops.integration_poll_watermark
                SET 
                    last_created_at = '1970-01-01 00:00:00',
                    last_message_id = 0,
                    updated_at = NOW()
                WHERE id = 1
            """))
            logger.info("  ✓ Watermark reset")
            
            # Commit all changes
            db.commit()
            
            # Step 3: Verify cleanup
            logger.info("\n3. Verifying cleanup...")
            verification_queries = [
                ("packet", "SELECT COUNT(*) FROM service_ops.packet"),
                ("packet_document", "SELECT COUNT(*) FROM service_ops.packet_document"),
                ("integration_inbox", "SELECT COUNT(*) FROM service_ops.integration_inbox"),
                ("packet_decision", "SELECT COUNT(*) FROM service_ops.packet_decision"),
                ("validation_run", "SELECT COUNT(*) FROM service_ops.validation_run"),
            ]
            
            all_clean = True
            for table_name, query in verification_queries:
                result = db.execute(text(query))
                count = result.scalar()
                if count == 0:
                    logger.info(f"  ✓ {table_name}: {count} records (clean)")
                else:
                    logger.error(f"  ✗ {table_name}: {count} records (expected 0)")
                    all_clean = False
            
            if not all_clean:
                logger.error("\n✗ Some tables are not clean!")
                return False
            
            # Step 4: Show messages ready for processing
            logger.info("\n4. Messages ready for processing in integration.send_serviceops:")
            result = db.execute(text("""
                SELECT 
                    message_id,
                    decision_tracking_id,
                    channel_type_id,
                    created_at,
                    payload->>'message_type' as message_type,
                    CASE 
                        WHEN channel_type_id = 1 THEN 'Portal'
                        WHEN channel_type_id = 2 THEN 'Fax'
                        WHEN channel_type_id = 3 THEN 'ESMD'
                        ELSE 'Unknown'
                    END as channel_name
                FROM integration.send_serviceops
                WHERE is_deleted = false
                ORDER BY channel_type_id, created_at
            """))
            
            records = result.fetchall()
            logger.info(f"\n  Found {len(records)} messages ready for processing:\n")
            
            # Group by channel
            portal_count = 0
            fax_count = 0
            esmd_count = 0
            
            for row in records:
                message_id, decision_tracking_id, channel_type_id, created_at, message_type, channel_name = row
                logger.info(f"    message_id={message_id:4d} | channel={channel_name:6s} (id={channel_type_id}) | "
                          f"decision_tracking_id={decision_tracking_id} | created_at={created_at}")
                
                if channel_type_id == 1:
                    portal_count += 1
                elif channel_type_id == 2:
                    fax_count += 1
                elif channel_type_id == 3:
                    esmd_count += 1
            
            logger.info(f"\n  Summary by channel:")
            logger.info(f"    Portal (channel_type_id=1): {portal_count} messages")
            logger.info(f"    Fax (channel_type_id=2): {fax_count} messages")
            logger.info(f"    ESMD (channel_type_id=3): {esmd_count} messages")
            
            logger.info("\n" + "=" * 80)
            logger.info("✓ DATABASE CLEANUP COMPLETE")
            logger.info("=" * 80)
            logger.info("\nDatabase is ready for processing:")
            logger.info("  - All processing tables cleaned")
            logger.info(f"  - {len(records)} messages remain in send_serviceops")
            logger.info("  - Watermark reset to start from beginning")
            logger.info("\nThe message poller will now process all messages from scratch.\n")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Cleanup failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = clean_all_tables()
    sys.exit(0 if success else 1)

