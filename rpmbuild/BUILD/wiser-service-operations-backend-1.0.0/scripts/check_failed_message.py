"""
Check details of failed message 271
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_failed_message():
    """Check details of failed message"""
    logger.info("=" * 80)
    logger.info("CHECKING FAILED MESSAGE 271")
    logger.info("=" * 80)
    
    try:
        with engine.connect() as conn:
            # Check inbox record
            result = conn.execute(text("""
                SELECT 
                    inbox_id,
                    message_id,
                    decision_tracking_id,
                    status,
                    attempt_count,
                    last_error,
                    locked_by,
                    locked_at,
                    next_attempt_at,
                    channel_type_id
                FROM service_ops.integration_inbox
                WHERE message_id = 271
            """))
            inbox_row = result.fetchone()
            
            if inbox_row:
                logger.info(f"\nInbox record for message 271:")
                logger.info(f"  inbox_id: {inbox_row[0]}")
                logger.info(f"  status: {inbox_row[3]}")
                logger.info(f"  attempt_count: {inbox_row[4]}")
                logger.info(f"  last_error: {inbox_row[5]}")
                logger.info(f"  locked_by: {inbox_row[6]}")
                logger.info(f"  locked_at: {inbox_row[7]}")
                logger.info(f"  next_attempt_at: {inbox_row[8]}")
                logger.info(f"  channel_type_id: {inbox_row[9]}")
            
            # Check if packet was created
            result = conn.execute(text("""
                SELECT 
                    packet_id,
                    external_id,
                    decision_tracking_id,
                    channel_type_id
                FROM service_ops.packet
                WHERE decision_tracking_id = 'e7b8c1e2-1234-4cde-9abc-1234567890ab'
            """))
            packet_row = result.fetchone()
            
            if packet_row:
                logger.info(f"\nPacket was created:")
                logger.info(f"  packet_id: {packet_row[0]}")
                logger.info(f"  external_id: {packet_row[1]}")
                logger.info(f"  channel_type_id: {packet_row[3]}")
            else:
                logger.info("\nNo packet was created for message 271")
            
            # Check if document was created
            if packet_row:
                result = conn.execute(text("""
                    SELECT 
                        packet_document_id,
                        external_id,
                        split_status,
                        ocr_status,
                        consolidated_blob_path
                    FROM service_ops.packet_document
                    WHERE packet_id = :packet_id
                """), {'packet_id': packet_row[0]})
                doc_row = result.fetchone()
                
                if doc_row:
                    logger.info(f"\nDocument was created:")
                    logger.info(f"  packet_document_id: {doc_row[0]}")
                    logger.info(f"  external_id: {doc_row[1]}")
                    logger.info(f"  split_status: {doc_row[2]}")
                    logger.info(f"  ocr_status: {doc_row[3]}")
                    logger.info(f"  consolidated_blob_path: {doc_row[4]}")
                else:
                    logger.info("\nNo document was created for message 271")
            
            # Check send_serviceops payload for message 271
            result = conn.execute(text("""
                SELECT 
                    message_id,
                    payload->>'documents' as documents_json,
                    payload->'documents'->0->>'blobPath' as blob_path
                FROM integration.send_serviceops
                WHERE message_id = 271
            """))
            source_row = result.fetchone()
            
            if source_row:
                logger.info(f"\nSource message 271:")
                logger.info(f"  blob_path: {source_row[2]}")
            
    except Exception as e:
        logger.error(f"Error checking failed message: {e}", exc_info=True)


if __name__ == "__main__":
    check_failed_message()

