"""
Script to manually process ClinicalOps response records from service_ops.send_serviceops.

This simulates what the ClinicalOps inbox processor would do:
1. Polls for new CLINICAL_DECISION messages
2. Processes them and updates packet_decision
3. Generates ESMD payloads
4. Updates packet status
"""
import sys
import os
import asyncio
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor


async def process_clinical_ops_responses():
    """Manually trigger processing of ClinicalOps response records"""
    processor = ClinicalOpsInboxProcessor()
    
    print("[INFO] Starting ClinicalOps inbox processor...")
    print("[INFO] This will process any pending CLINICAL_DECISION messages")
    print()
    
    # Create watermark table if it doesn't exist
    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS service_ops.clinical_ops_poll_watermark (
                id INTEGER PRIMARY KEY DEFAULT 1,
                last_message_id BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT single_row CHECK (id = 1)
            )
        """))
        db.execute(text("""
            INSERT INTO service_ops.clinical_ops_poll_watermark (id, last_message_id)
            VALUES (1, 0)
            ON CONFLICT (id) DO NOTHING
        """))
        db.commit()
        print("[OK] Watermark table created/verified")
        print()
    except Exception as e:
        db.rollback()
        print(f"[WARN] Could not create watermark table (may already exist): {e}")
        print()
    
    # Manually trigger one polling cycle
    try:
        # Poll for new messages
        messages = processor._poll_new_messages(db)
        
        if not messages:
            print("[INFO] No new messages found in service_ops.send_serviceops")
            print("   Make sure you have created response records with message_type='CLINICAL_DECISION'")
            return
        
        print(f"[OK] Found {len(messages)} message(s) to process:")
        for msg in messages:
            print(f"   - message_id: {msg['message_id']}, decision_tracking_id: {msg['decision_tracking_id']}")
            print(f"     decision_outcome: {msg['payload'].get('decision_outcome')}")
        print()
        
        # Process each message
        for message in messages:
            try:
                print(f"[INFO] Processing message_id: {message['message_id']}...")
                await processor._process_message(db, message)
                print(f"[OK] Successfully processed message_id: {message['message_id']}")
                print()
            except Exception as e:
                print(f"[ERROR] Failed to process message_id {message['message_id']}: {e}")
                import traceback
                traceback.print_exc()
                print()
        
        print("[OK] Processing complete!")
        print()
        print("[INFO] Check the following tables for updates:")
        print("   1. service_ops.packet_decision - Clinical decision should be updated")
        print("   2. service_ops.packet - Status should be updated to 'Clinical Decision Received'")
        print("   3. service_ops.send_integration - ESMD payload should be created")
        
    except Exception as e:
        print(f"[ERROR] Error during processing: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(process_clinical_ops_responses())

