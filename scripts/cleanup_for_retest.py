"""
Cleanup script to reset database for retesting the 3 messages
Clears all processing data but keeps the 3 test records in send_serviceops
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def cleanup_database():
    """Clean all processing tables, keeping only 3 test records in send_serviceops"""
    logger.info("=" * 80)
    logger.info("CLEANING DATABASE FOR RETEST")
    logger.info("=" * 80)
    
    try:
        with engine.connect() as conn:
            # Clean all service_ops tables (in dependency order)
            logger.info("\n1. Cleaning service_ops tables...")
            
            cleanup_sql = """
            BEGIN;
            
            -- Clear decisions and validations first (they reference documents)
            DELETE FROM service_ops.packet_decision;
            DELETE FROM service_ops.validation_run;
            
            -- Clear documents (they reference packets)
            DELETE FROM service_ops.packet_document;
            
            -- Clear packets
            DELETE FROM service_ops.packet;
            
            -- Clear inbox (processing queue)
            DELETE FROM service_ops.integration_inbox;
            
            -- Reset watermark to start fresh
            UPDATE service_ops.integration_poll_watermark
            SET 
                last_created_at = '1970-01-01 00:00:00',
                last_message_id = 0,
                updated_at = NOW()
            WHERE id = 1;
            
            COMMIT;
            """
            
            conn.execute(text(cleanup_sql))
            conn.commit()
            
            logger.info("  ✓ Cleaned packet_decision")
            logger.info("  ✓ Cleaned validation_run")
            logger.info("  ✓ Cleaned packet_document")
            logger.info("  ✓ Cleaned packet")
            logger.info("  ✓ Cleaned integration_inbox")
            logger.info("  ✓ Reset watermark")
            
            # Verify send_serviceops still has 3 records
            logger.info("\n2. Verifying send_serviceops table...")
            result = conn.execute(text("""
                SELECT 
                    message_id,
                    channel_type_id,
                    decision_tracking_id,
                    CASE 
                        WHEN channel_type_id = 1 THEN 'Genzeon Portal'
                        WHEN channel_type_id = 2 THEN 'Genzeon Fax'
                        WHEN channel_type_id = 3 THEN 'ESMD'
                        ELSE 'Unknown'
                    END as channel_name
                FROM integration.send_serviceops
                WHERE is_deleted = false
                ORDER BY message_id
            """))
            
            records = result.fetchall()
            logger.info(f"  Found {len(records)} records in send_serviceops:")
            for row in records:
                logger.info(f"    message_id={row[0]}, channel_type_id={row[1]} ({row[3]}), decision_tracking_id={row[2]}")
            
            if len(records) != 3:
                logger.error(f"✗ Expected 3 records, found {len(records)}")
                return False
            
            # Verify all tables are empty
            logger.info("\n3. Verifying tables are clean...")
            tables_to_check = [
                ("packet", "SELECT COUNT(*) FROM service_ops.packet"),
                ("packet_document", "SELECT COUNT(*) FROM service_ops.packet_document"),
                ("integration_inbox", "SELECT COUNT(*) FROM service_ops.integration_inbox"),
                ("packet_decision", "SELECT COUNT(*) FROM service_ops.packet_decision"),
                ("validation_run", "SELECT COUNT(*) FROM service_ops.validation_run"),
            ]
            
            all_clean = True
            for table_name, query in tables_to_check:
                result = conn.execute(text(query))
                count = result.scalar()
                if count == 0:
                    logger.info(f"  ✓ {table_name}: {count} records")
                else:
                    logger.error(f"  ✗ {table_name}: {count} records (expected 0)")
                    all_clean = False
            
            if not all_clean:
                logger.error("\n✗ Some tables are not clean")
                return False
            
            logger.info("\n" + "=" * 80)
            logger.info("✓ DATABASE CLEANUP COMPLETE")
            logger.info("=" * 80)
            logger.info("\nDatabase is ready for retesting:")
            logger.info("  - All processing tables cleaned")
            logger.info("  - 3 test records remain in send_serviceops:")
            logger.info("    * message_id=270 (ESMD, channel_type_id=3)")
            logger.info("    * message_id=271 (Genzeon Fax, channel_type_id=2)")
            logger.info("    * message_id=272 (Genzeon Portal, channel_type_id=1)")
            logger.info("  - Watermark reset to start from beginning")
            logger.info("\nThe message poller will now process all 3 messages from scratch.\n")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Cleanup failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = cleanup_database()
    sys.exit(0 if success else 1)






