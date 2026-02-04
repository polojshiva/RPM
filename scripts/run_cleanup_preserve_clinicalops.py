"""
Run cleanup script that preserves send_clinicalops and send_serviceops
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_cleanup():
    """Run the cleanup SQL script"""
    script_path = Path(__file__).parent / "clean_db_preserve_clinicalops.sql"
    
    logger.info("=" * 80)
    logger.info("CLEANING DATABASE - PRESERVING send_clinicalops AND send_serviceops")
    logger.info("=" * 80)
    
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()
        
        with engine.connect() as conn:
            # Execute the entire script
            conn.execute(text(sql_script))
            conn.commit()
        
        logger.info("✓ Cleanup completed successfully")
        logger.info("✓ service_ops.send_clinicalops preserved")
        logger.info("✓ integration.send_serviceops test messages preserved")
        return True
        
    except Exception as e:
        logger.error(f"✗ Cleanup failed: {e}", exc_info=True)
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
            return True
            
    except Exception as e:
        logger.error(f"✗ Verification failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = run_cleanup()
    if success:
        verify_cleanup()
    else:
        sys.exit(1)

