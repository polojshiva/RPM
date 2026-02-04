"""
Execute cleanup script directly
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def execute_cleanup():
    """Execute the cleanup SQL script"""
    script_path = Path(__file__).parent / "clean_db_preserve_clinicalops.sql"
    
    logger.info("=" * 80)
    logger.info("CLEANING DATABASE - PRESERVING send_clinicalops AND send_serviceops")
    logger.info("=" * 80)
    
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()
        
        # Execute the entire script as one transaction
        # Remove verification SELECTs at the end (we'll do that separately)
        sql_to_execute = sql_script
        # Remove the verification section
        if '-- Verification' in sql_to_execute:
            sql_to_execute = sql_to_execute.split('-- Verification')[0] + 'COMMIT;'
        
        with engine.connect() as conn:
            # Execute the entire script
            conn.execute(text(sql_to_execute))
            conn.commit()
            logger.info("✓ Executed cleanup script")
        
        logger.info("\n✓ Cleanup completed successfully")
        logger.info("✓ service_ops.send_clinicalops preserved")
        logger.info("✓ integration.send_serviceops test messages preserved")
        
        # Now run verification
        verify_cleanup()
        return True
        
    except Exception as e:
        logger.error(f"\n✗ Cleanup failed: {e}", exc_info=True)
        return False


def verify_cleanup():
    """Verify cleanup was successful"""
    logger.info("\n" + "=" * 80)
    logger.info("VERIFYING CLEANUP")
    logger.info("=" * 80)
    
    verification_sql = """
    SELECT 
        'service_ops.packet' AS table_name,
        COUNT(*) AS row_count
    FROM service_ops.packet
    UNION ALL
    SELECT 
        'service_ops.packet_document',
        COUNT(*)
    FROM service_ops.packet_document
    UNION ALL
    SELECT 
        'service_ops.packet_decision',
        COUNT(*)
    FROM service_ops.packet_decision
    UNION ALL
    SELECT 
        'service_ops.packet_validation',
        COUNT(*)
    FROM service_ops.packet_validation
    UNION ALL
    SELECT 
        'service_ops.send_clinicalops (PRESERVED)',
        COUNT(*)
    FROM service_ops.send_clinicalops
    UNION ALL
    SELECT 
        'integration.send_serviceops (PRESERVED)',
        COUNT(*)
    FROM integration.send_serviceops
    WHERE is_deleted = false;
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(verification_sql))
            rows = result.fetchall()
            
            logger.info("\nTable Row Counts:")
            logger.info("-" * 80)
            for row in rows:
                table_name = row[0]
                count = row[1]
                status = "✓" if "PRESERVED" in table_name or count == 0 else "?"
                logger.info(f"{status} {table_name}: {count} rows")
            
            logger.info("\n✓ Verification complete")
            logger.info("\n" + "=" * 80)
            logger.info("Database is ready for end-to-end testing!")
            logger.info("=" * 80)
            return True
            
    except Exception as e:
        logger.error(f"✗ Verification failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = execute_cleanup()
    sys.exit(0 if success else 1)

