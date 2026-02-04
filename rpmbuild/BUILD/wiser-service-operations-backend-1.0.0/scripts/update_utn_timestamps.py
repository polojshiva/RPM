"""
Update UTN_SUCCESS records created_at to be newer than watermark
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.integration_db import SendServiceOpsDB
from datetime import datetime, timezone, timedelta

def update_utn_timestamps():
    """Update created_at for UTN_SUCCESS records to be processable"""
    db = SessionLocal()
    
    try:
        # Get current watermark
        from sqlalchemy import text
        watermark_result = db.execute(text("""
            SELECT last_created_at, last_message_id
            FROM service_ops.integration_poll_watermark
            WHERE id = 1
        """)).fetchone()
        
        if watermark_result:
            last_created_at, last_message_id = watermark_result
            print(f"Current watermark: {last_created_at}, message_id: {last_message_id}")
            
            # Set new timestamp to be 1 second after watermark
            new_timestamp = last_created_at + timedelta(seconds=1)
            if new_timestamp.tzinfo is None:
                new_timestamp = new_timestamp.replace(tzinfo=timezone.utc)
        else:
            # No watermark, use current time
            new_timestamp = datetime.now(timezone.utc)
            print("No watermark found, using current time")
        
        # Find UTN_SUCCESS records
        utn_records = db.query(SendServiceOpsDB).filter(
            SendServiceOpsDB.message_type_id == 2,
            SendServiceOpsDB.is_deleted == False
        ).all()
        
        print(f"\nFound {len(utn_records)} UTN_SUCCESS records to update")
        
        for i, record in enumerate(utn_records):
            old_timestamp = record.created_at
            # Set timestamp with slight offset for each record
            record.created_at = new_timestamp + timedelta(seconds=i)
            print(f"\nRecord message_id: {record.message_id}")
            print(f"  decision_tracking_id: {record.decision_tracking_id}")
            print(f"  Old created_at: {old_timestamp}")
            print(f"  New created_at: {record.created_at}")
        
        db.commit()
        print(f"\nSUCCESS: Updated {len(utn_records)} UTN_SUCCESS records")
        print("They will be picked up on the next poll cycle")
        
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    update_utn_timestamps()

