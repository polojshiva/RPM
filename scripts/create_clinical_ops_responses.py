"""
Script to create synthetic ClinicalOps response records (AFFIRM and NON_AFFIRM)
for testing the ClinicalOps inbox processor.

This creates two records in service_ops.send_serviceops:
1. One with decision_outcome = "AFFIRM"
2. One with decision_outcome = "NON_AFFIRM"

Both reference the same decision_tracking_id from the latest send_clinicalops record.
"""
import sys
import os
from datetime import datetime
from uuid import UUID

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.clinical_ops_db import ClinicalOpsInboxDB
from app.models.send_clinicalops_db import SendClinicalOpsDB


def create_clinical_ops_responses():
    """Create two synthetic ClinicalOps response records"""
    db = SessionLocal()
    try:
        # Get the latest send_clinicalops record (the one we sent to ClinicalOps)
        latest_sent = db.query(SendClinicalOpsDB).order_by(
            SendClinicalOpsDB.message_id.desc()
        ).first()
        
        if not latest_sent:
            print("[ERROR] No records found in service_ops.send_clinicalops")
            print("   Please send a case to ClinicalOps first using 'Send to Clinical Ops'")
            return
        
        decision_tracking_id = latest_sent.decision_tracking_id
        print(f"[OK] Found latest send_clinicalops record:")
        print(f"   message_id: {latest_sent.message_id}")
        print(f"   decision_tracking_id: {decision_tracking_id}")
        print(f"   payload.message_type: {latest_sent.payload.get('message_type')}")
        print()
        
        # Create AFFIRM response
        affirm_payload = {
            "message_type": "CLINICAL_DECISION",
            "decision_tracking_id": str(decision_tracking_id),
            "decision_outcome": "AFFIRM",
            "decision_subtype": "STANDARD_PA",  # or "DIRECT_PA"
            "part_type": "B",  # or "A"
            "procedures": [
                {
                    "procedure_code": "64483",
                    "units": 2,
                    "modifier": "50"
                }
            ],
            "medical_documents": [],  # Array of doc URLs/paths (optional)
            "decision_date": datetime.utcnow().isoformat(),
            "decision_notes": "Clinical review completed - Affirmed",
            "reviewed_by": "CLINICAL_OPS_SYSTEM"
        }
        
        affirm_record = ClinicalOpsInboxDB(
            decision_tracking_id=decision_tracking_id,
            payload=affirm_payload,
            message_status_id=1,  # INGESTED - ready for processing
            audit_user="SYSTEM",
            audit_timestamp=datetime.utcnow(),
            is_deleted=False
        )
        db.add(affirm_record)
        db.flush()
        
        print(f"[OK] Created AFFIRM response:")
        print(f"   message_id: {affirm_record.message_id}")
        print(f"   decision_tracking_id: {affirm_record.decision_tracking_id}")
        print(f"   decision_outcome: {affirm_payload['decision_outcome']}")
        print(f"   decision_subtype: {affirm_payload['decision_subtype']}")
        print(f"   part_type: {affirm_payload['part_type']}")
        print()
        
        # Create NON_AFFIRM response
        non_affirm_payload = {
            "message_type": "CLINICAL_DECISION",
            "decision_tracking_id": str(decision_tracking_id),
            "decision_outcome": "NON_AFFIRM",
            "decision_subtype": "STANDARD_PA",  # or "DIRECT_PA"
            "part_type": "B",  # or "A"
            "procedures": [
                {
                    "procedure_code": "64483",
                    "units": 2,
                    "modifier": "50"
                }
            ],
            "medical_documents": [],  # Array of doc URLs/paths (optional)
            "decision_date": datetime.utcnow().isoformat(),
            "decision_notes": "Clinical review completed - Non-Affirmed",
            "reviewed_by": "CLINICAL_OPS_SYSTEM"
        }
        
        non_affirm_record = ClinicalOpsInboxDB(
            decision_tracking_id=decision_tracking_id,
            payload=non_affirm_payload,
            message_status_id=1,  # INGESTED - ready for processing
            audit_user="SYSTEM",
            audit_timestamp=datetime.utcnow(),
            is_deleted=False
        )
        db.add(non_affirm_record)
        db.flush()
        
        print(f"[OK] Created NON_AFFIRM response:")
        print(f"   message_id: {non_affirm_record.message_id}")
        print(f"   decision_tracking_id: {non_affirm_record.decision_tracking_id}")
        print(f"   decision_outcome: {non_affirm_payload['decision_outcome']}")
        print(f"   decision_subtype: {non_affirm_payload['decision_subtype']}")
        print(f"   part_type: {non_affirm_payload['part_type']}")
        print()
        
        # Commit both records
        db.commit()
        
        print("[OK] Successfully created both response records!")
        print()
        print("[INFO] Summary:")
        print(f"   AFFIRM message_id: {affirm_record.message_id}")
        print(f"   NON_AFFIRM message_id: {non_affirm_record.message_id}")
        print(f"   Both reference decision_tracking_id: {decision_tracking_id}")
        print()
        print("[INFO] Next steps:")
        print("   1. The ClinicalOps inbox processor will pick up these records")
        print("   2. It will update packet_decision with the clinical decision")
        print("   3. It will generate ESMD payloads and write to service_ops.send_integration")
        print("   4. Check the logs to see processing results")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error creating response records: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_clinical_ops_responses()

