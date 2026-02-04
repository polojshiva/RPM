"""
Check polling watermark to see if UTN records are being blocked
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text

def check_polling_watermark():
    """Check integration polling watermark"""
    db = SessionLocal()
    
    try:
        print("=" * 80)
        print("CHECKING INTEGRATION POLLING WATERMARK")
        print("=" * 80)
        
        # Check watermark
        watermark_query = text("""
            SELECT 
                last_created_at,
                last_message_id,
                updated_at
            FROM service_ops.integration_poll_watermark
            WHERE id = 1
        """)
        
        result = db.execute(watermark_query).fetchone()
        
        if result:
            last_created_at, last_message_id, updated_at = result
            print(f"\nWatermark Status:")
            print(f"  last_created_at: {last_created_at}")
            print(f"  last_message_id: {last_message_id}")
            print(f"  updated_at: {updated_at}")
        else:
            print("\nNo watermark record found (will default to epoch)")
        
        # Check UTN records timestamps
        utn_query = text("""
            SELECT 
                message_id,
                decision_tracking_id,
                created_at,
                message_type_id
            FROM integration.send_serviceops
            WHERE message_type_id = 2
                AND is_deleted = false
            ORDER BY created_at DESC
            LIMIT 5
        """)
        
        utn_records = db.execute(utn_query).fetchall()
        
        print(f"\nUTN_SUCCESS Records:")
        print("-" * 80)
        for record in utn_records:
            msg_id, dt_id, created_at, msg_type = record
            print(f"  message_id: {msg_id}")
            print(f"  created_at: {created_at}")
            print(f"  decision_tracking_id: {str(dt_id)}")
            
            if result:
                if created_at > last_created_at:
                    print(f"    -> SHOULD BE PICKED UP (created_at > watermark)")
                elif created_at == last_created_at and msg_id > last_message_id:
                    print(f"    -> SHOULD BE PICKED UP (same timestamp, higher message_id)")
                else:
                    print(f"    -> BLOCKED BY WATERMARK (already processed or before watermark)")
            print()
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_polling_watermark()

