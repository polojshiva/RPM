"""
Comprehensive verification script to check if all 3 messages were processed correctly
Checks all tables and verifies channel-specific workflows
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_processing():
    """Comprehensive verification of processing results"""
    logger.info("=" * 80)
    logger.info("COMPREHENSIVE PROCESSING VERIFICATION")
    logger.info("=" * 80)
    
    try:
        with engine.connect() as conn:
            # 1. Check send_serviceops - should have 3 records
            logger.info("\n1. Checking send_serviceops table:")
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
            send_serviceops_records = result.fetchall()
            logger.info(f"  Found {len(send_serviceops_records)} records in send_serviceops")
            for row in send_serviceops_records:
                logger.info(f"    message_id={row[0]}, channel_type_id={row[1]} ({row[3]}), decision_tracking_id={row[2]}")
            
            if len(send_serviceops_records) != 3:
                logger.error(f"✗ Expected 3 records, found {len(send_serviceops_records)}")
                return False
            
            # 2. Check integration_inbox - should have 3 records, all DONE
            logger.info("\n2. Checking integration_inbox table:")
            result = conn.execute(text("""
                SELECT 
                    inbox_id,
                    message_id,
                    decision_tracking_id,
                    status,
                    attempt_count,
                    channel_type_id,
                    CASE 
                        WHEN channel_type_id = 1 THEN 'Genzeon Portal'
                        WHEN channel_type_id = 2 THEN 'Genzeon Fax'
                        WHEN channel_type_id = 3 THEN 'ESMD'
                        ELSE 'Unknown'
                    END as channel_name
                FROM service_ops.integration_inbox
                ORDER BY inbox_id
            """))
            inbox_records = result.fetchall()
            logger.info(f"  Found {len(inbox_records)} records in integration_inbox")
            for row in inbox_records:
                logger.info(f"    inbox_id={row[0]}, message_id={row[1]}, status={row[3]}, attempts={row[4]}, channel={row[6]}")
            
            if len(inbox_records) != 3:
                logger.error(f"✗ Expected 3 records in inbox, found {len(inbox_records)}")
                return False
            
            done_count = sum(1 for row in inbox_records if row[3] == 'DONE')
            if done_count != 3:
                logger.error(f"✗ Expected 3 DONE records, found {done_count}")
                return False
            logger.info(f"  ✓ All {done_count} records are DONE")
            
            # 3. Check packet table - should have 3 packets with correct channel_type_id
            logger.info("\n3. Checking packet table:")
            result = conn.execute(text("""
                SELECT 
                    packet_id,
                    external_id,
                    decision_tracking_id,
                    channel_type_id,
                    beneficiary_name,
                    provider_name,
                    CASE 
                        WHEN channel_type_id = 1 THEN 'Genzeon Portal'
                        WHEN channel_type_id = 2 THEN 'Genzeon Fax'
                        WHEN channel_type_id = 3 THEN 'ESMD'
                        ELSE 'Unknown'
                    END as channel_name
                FROM service_ops.packet
                ORDER BY packet_id
            """))
            packet_records = result.fetchall()
            logger.info(f"  Found {len(packet_records)} records in packet")
            for row in packet_records:
                logger.info(f"    packet_id={row[0]}, external_id={row[1]}, decision_tracking_id={row[2]}, channel={row[6]}")
            
            if len(packet_records) != 3:
                logger.error(f"✗ Expected 3 packets, found {len(packet_records)}")
                return False
            
            # 4. Check packet_document table - should have 3 documents
            logger.info("\n4. Checking packet_document table:")
            result = conn.execute(text("""
                SELECT 
                    pd.packet_document_id,
                    pd.external_id,
                    pd.packet_id,
                    pd.split_status,
                    pd.ocr_status,
                    pd.coversheet_page_number,
                    pd.part_type,
                    p.channel_type_id,
                    CASE 
                        WHEN p.channel_type_id = 1 THEN 'Genzeon Portal'
                        WHEN p.channel_type_id = 2 THEN 'Genzeon Fax'
                        WHEN p.channel_type_id = 3 THEN 'ESMD'
                        ELSE 'Unknown'
                    END as channel_name,
                    CASE 
                        WHEN pd.extracted_fields IS NOT NULL 
                            AND jsonb_typeof(pd.extracted_fields->'fields') = 'object'
                            THEN (
                                SELECT COUNT(*) 
                                FROM jsonb_object_keys(pd.extracted_fields->'fields')
                            )
                        ELSE 0 
                    END as field_count,
                    CASE 
                        WHEN pd.ocr_metadata IS NOT NULL THEN pd.ocr_metadata->>'source'
                        ELSE NULL
                    END as ocr_source
                FROM service_ops.packet_document pd
                JOIN service_ops.packet p ON pd.packet_id = p.packet_id
                ORDER BY pd.packet_document_id
            """))
            document_records = result.fetchall()
            logger.info(f"  Found {len(document_records)} records in packet_document")
            for row in document_records:
                logger.info(f"    doc_id={row[1]}, packet_id={row[2]}, split={row[3]}, ocr={row[4]}, coversheet_page={row[5]}, part_type={row[6]}, channel={row[8]}, fields={row[9]}, ocr_source={row[10]}")
            
            if len(document_records) != 3:
                logger.error(f"✗ Expected 3 documents, found {len(document_records)}")
                return False
            
            # 5. Verify channel-specific processing
            logger.info("\n5. Verifying channel-specific processing:")
            
            # Check Portal (should have source='payload' in ocr_metadata)
            portal_docs = [r for r in document_records if r[7] == 1]
            if len(portal_docs) != 1:
                logger.error(f"✗ Expected 1 Portal document, found {len(portal_docs)}")
                return False
            portal_doc = portal_docs[0]
            if portal_doc[10] != 'payload':
                logger.error(f"✗ Portal document should have ocr_source='payload', got '{portal_doc[10]}'")
                return False
            if portal_doc[4] != 'DONE':
                logger.error(f"✗ Portal document should have ocr_status='DONE', got '{portal_doc[4]}'")
                return False
            logger.info(f"  ✓ Portal document (doc_id={portal_doc[1]}): ocr_source=payload, ocr_status=DONE, fields={portal_doc[9]}")
            
            # Check ESMD/Fax (should have source='ocr' or NULL in ocr_metadata, and ocr_status='DONE')
            ocr_docs = [r for r in document_records if r[7] in [2, 3]]
            if len(ocr_docs) != 2:
                logger.error(f"✗ Expected 2 OCR documents (ESMD/Fax), found {len(ocr_docs)}")
                return False
            for ocr_doc in ocr_docs:
                if ocr_doc[4] != 'DONE':
                    logger.error(f"✗ OCR document (doc_id={ocr_doc[1]}) should have ocr_status='DONE', got '{ocr_doc[4]}'")
                    return False
                if ocr_doc[10] not in ['ocr', None]:
                    logger.warning(f"  ⚠ OCR document (doc_id={ocr_doc[1]}) has ocr_source='{ocr_doc[10]}' (expected 'ocr' or NULL)")
                logger.info(f"  ✓ OCR document (doc_id={ocr_doc[1]}, channel={ocr_doc[8]}): ocr_status=DONE, fields={ocr_doc[9]}")
            
            # 6. Verify all have split_status = DONE
            logger.info("\n6. Verifying split status:")
            split_done = sum(1 for r in document_records if r[3] == 'DONE')
            if split_done != 3:
                logger.error(f"✗ Expected 3 documents with split_status='DONE', found {split_done}")
                return False
            logger.info(f"  ✓ All {split_done} documents have split_status='DONE'")
            
            # 7. Verify all have coversheet_page_number set
            logger.info("\n7. Verifying coversheet detection:")
            coversheet_set = sum(1 for r in document_records if r[5] is not None)
            if coversheet_set != 3:
                logger.error(f"✗ Expected 3 documents with coversheet_page_number set, found {coversheet_set}")
                return False
            logger.info(f"  ✓ All {coversheet_set} documents have coversheet_page_number set")
            for row in document_records:
                logger.info(f"    doc_id={row[1]}: coversheet_page={row[5]}, part_type={row[6]}")
            
            # 8. Verify extracted_fields are populated
            logger.info("\n8. Verifying extracted_fields:")
            fields_populated = sum(1 for r in document_records if r[9] > 0)
            if fields_populated != 3:
                logger.error(f"✗ Expected 3 documents with extracted_fields populated, found {fields_populated}")
                return False
            logger.info(f"  ✓ All {fields_populated} documents have extracted_fields populated")
            
            # 9. Summary
            logger.info("\n" + "=" * 80)
            logger.info("VERIFICATION SUMMARY")
            logger.info("=" * 80)
            logger.info("✓ send_serviceops: 3 records")
            logger.info("✓ integration_inbox: 3 records, all DONE")
            logger.info("✓ packet: 3 records with correct channel_type_id")
            logger.info("✓ packet_document: 3 records")
            logger.info("✓ Portal workflow: Fields extracted from payload (not OCR)")
            logger.info("✓ ESMD/Fax workflows: Fields extracted from OCR service")
            logger.info("✓ All documents: split_status=DONE, ocr_status=DONE")
            logger.info("✓ All documents: coversheet_page_number set, extracted_fields populated")
            logger.info("\n✓ ALL VERIFICATIONS PASSED - System processed all 3 messages correctly!\n")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Verification failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = verify_processing()
    sys.exit(0 if success else 1)


