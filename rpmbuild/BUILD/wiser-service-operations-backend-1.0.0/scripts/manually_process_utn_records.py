"""
Manually trigger processing of UTN_SUCCESS records
"""
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB  # Ensure all models are loaded
from app.services.utn_handlers import UtnSuccessHandler

async def manually_process_utn_records():
    """Manually process UTN_SUCCESS records"""
    db = SessionLocal()
    
    try:
        # Find UTN_SUCCESS records
        utn_records = db.query(SendServiceOpsDB).filter(
            SendServiceOpsDB.message_type_id == 2,
            SendServiceOpsDB.is_deleted == False
        ).order_by(SendServiceOpsDB.created_at.asc()).all()
        
        print(f"Found {len(utn_records)} UTN_SUCCESS records to process")
        print("=" * 80)
        
        for record in utn_records:
            print(f"\nProcessing message_id: {record.message_id}")
            print(f"  decision_tracking_id: {record.decision_tracking_id}")
            print(f"  UTN: {record.payload.get('unique_tracking_number', 'N/A')}")
            
            message_dict = {
                'message_id': record.message_id,
                'decision_tracking_id': str(record.decision_tracking_id),
                'payload': record.payload,
                'created_at': record.created_at
            }
            
            try:
                # Process the UTN_SUCCESS message
                await UtnSuccessHandler.handle(db, message_dict)
                db.commit()
                print(f"  SUCCESS: Processed message_id {record.message_id}")
            except Exception as e:
                db.rollback()
                print(f"  ERROR: Failed to process message_id {record.message_id}: {e}")
                import traceback
                traceback.print_exc()
        
        print("\n" + "=" * 80)
        print("Processing complete!")
        
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(manually_process_utn_records())

