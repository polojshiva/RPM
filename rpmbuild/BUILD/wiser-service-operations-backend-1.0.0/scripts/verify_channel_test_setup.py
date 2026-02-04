"""
Verification script to check channel testing setup
Shows the 3 test records and their channel_type_id values
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_setup():
    """Verify the 3 test records are ready"""
    logger.info("=" * 80)
    logger.info("CHANNEL TESTING SETUP VERIFICATION")
    logger.info("=" * 80)
    
    query = text("""
        SELECT 
            message_id,
            channel_type_id,
            decision_tracking_id,
            CASE 
                WHEN channel_type_id = 1 THEN 'Genzeon Portal (Skip OCR, extract from payload.ocr)'
                WHEN channel_type_id = 2 THEN 'Genzeon Fax (Full OCR workflow)'
                WHEN channel_type_id = 3 THEN 'ESMD (Full OCR workflow)'
                WHEN channel_type_id IS NULL THEN 'NULL (Will default to ESMD)'
                ELSE 'Unknown'
            END as channel_description,
            payload->>'messageType' as message_type_from_payload,
            CASE 
                WHEN payload ? 'ocr' THEN 'YES (has ocr field)'
                ELSE 'NO (no ocr field)'
            END as has_ocr_field
        FROM integration.send_serviceops
        WHERE is_deleted = false
        ORDER BY message_id
    """)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            rows = result.fetchall()
            
            if len(rows) != 3:
                logger.error(f"✗ Expected 3 records, found {len(rows)}")
                return False
            
            logger.info(f"\n✓ Found {len(rows)} test records:\n")
            
            for row in rows:
                logger.info(f"  Message ID: {row[0]}")
                logger.info(f"    Channel Type ID: {row[1]} ({row[3]})")
                logger.info(f"    Decision Tracking ID: {row[2]}")
                logger.info(f"    Message Type (from payload): {row[4] or 'N/A'}")
                logger.info(f"    Has OCR field in payload: {row[5]}")
                logger.info("")
            
            # Verify channel_type_id values
            expected_channels = {270: 3, 271: 2, 272: 1}
            all_correct = True
            
            for row in rows:
                msg_id = row[0]
                channel_id = row[1]
                expected = expected_channels.get(msg_id)
                
                if channel_id != expected:
                    logger.error(f"✗ message_id={msg_id}: Expected channel_type_id={expected}, got {channel_id}")
                    all_correct = False
                else:
                    logger.info(f"✓ message_id={msg_id}: channel_type_id={channel_id} is correct")
            
            if all_correct:
                logger.info("\n" + "=" * 80)
                logger.info("✓ ALL RECORDS ARE CORRECTLY CONFIGURED")
                logger.info("=" * 80)
                logger.info("\nExpected workflows:")
                logger.info("  - message_id=270 (ESMD, channel_type_id=3): Full OCR workflow")
                logger.info("  - message_id=271 (Genzeon Fax, channel_type_id=2): Full OCR workflow")
                logger.info("  - message_id=272 (Genzeon Portal, channel_type_id=1): Skip OCR, extract from payload.ocr")
                logger.info("\nSystem is ready to process these messages!\n")
                return True
            else:
                logger.error("\n✗ Some records have incorrect channel_type_id values")
                return False
                
    except Exception as e:
        logger.error(f"✗ Verification failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = verify_setup()
    sys.exit(0 if success else 1)






