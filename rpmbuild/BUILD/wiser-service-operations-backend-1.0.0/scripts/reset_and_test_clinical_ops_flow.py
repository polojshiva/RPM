"""
Reset state and test ClinicalOps response processing flow
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text
from datetime import datetime
import json
import uuid

def reset_state():
    """Reset database state to before ClinicalOps processing"""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("RESETTING DATABASE STATE")
        print("=" * 80)
        
        # Read and execute cleanup SQL
        cleanup_sql_path = os.path.join(
            os.path.dirname(__file__),
            "cleanup_and_reset_clinical_ops_processing.sql"
        )
        
        with open(cleanup_sql_path, 'r') as f:
            cleanup_sql = f.read()
        
        db.execute(text(cleanup_sql))
        db.commit()
        
        print("[OK] Database state reset complete")
        print()
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error resetting state: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

def create_clinical_ops_responses():
    """Create synthetic ClinicalOps responses for the two packets"""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("CREATING CLINICAL OPS RESPONSES")
        print("=" * 80)
        
        # Get decision_tracking_ids from send_clinicalops
        records = db.execute(text("""
            SELECT 
                decision_tracking_id,
                payload->>'packet_id' as packet_id
            FROM service_ops.send_clinicalops
            ORDER BY message_id
        """)).fetchall()
        
        print(f"Found {len(records)} packets to create responses for")
        print()
        
        # Create one response per packet: first gets AFFIRM, second gets NON_AFFIRM
        for idx, rec in enumerate(records, 1):
            decision_tracking_id = rec[0]
            packet_id = rec[1]
            
            # First packet gets AFFIRM, second gets NON_AFFIRM
            decision_outcome = 'AFFIRM' if idx == 1 else 'NON_AFFIRM'
            
            payload = {
                "message_type": "CLINICAL_DECISION",
                "decision_tracking_id": str(decision_tracking_id),
                "decision_outcome": decision_outcome,
                "decision_subtype": "STANDARD_PA",
                "part_type": "B",
                "procedures": [
                    {
                        "procedure_code": "64483",
                        "units": 2,
                        "modifier": "50"
                    }
                ],
                "medical_documents": [],
                "decision_date": datetime.utcnow().isoformat(),
                "decision_notes": f"Clinical review completed - {decision_outcome}",
                "reviewed_by": "CLINICAL_OPS_SYSTEM"
            }
            
            # Insert into send_serviceops
            from sqlalchemy.dialects.postgresql import JSONB
            db.execute(
                text("""
                    INSERT INTO service_ops.send_serviceops (
                        decision_tracking_id,
                        payload,
                        message_status_id,
                        created_at,
                        audit_user
                    ) VALUES (
                        :dt_id,
                        CAST(:payload AS JSONB),
                        1,
                        NOW(),
                        'SYSTEM'
                    )
                """),
                {
                    'dt_id': decision_tracking_id,
                    'payload': json.dumps(payload)
                }
            )
            
            print(f"  Created {decision_outcome} response for {packet_id} (decision_tracking_id={decision_tracking_id})")
        
        db.commit()
        print()
        print(f"[OK] Created {len(records)} ClinicalOps responses (one per packet)")
        print()
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error creating responses: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

def verify_state():
    """Verify the state after reset"""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("VERIFYING STATE")
        print("=" * 80)
        
        decision_tracking_ids = [
            'b1c2d3e4-5678-4abc-9def-234567890abc',
            'f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067'
        ]
        
        for dt_id in decision_tracking_ids:
            print(f"\nChecking decision_tracking_id: {dt_id}")
            print("-" * 80)
            
            # Check packet status
            packet = db.execute(text("""
                SELECT 
                    packet_id,
                    external_id,
                    detailed_status
                FROM service_ops.packet
                WHERE decision_tracking_id = :dt_id
            """), {"dt_id": dt_id}).fetchone()
            
            if packet:
                print(f"  Packet: {packet[1]} | Status: {packet[2]}")
            
            # Check active decision
            decision = db.execute(text("""
                SELECT 
                    pd.packet_decision_id,
                    pd.operational_decision,
                    pd.clinical_decision,
                    pd.is_active
                FROM service_ops.packet_decision pd
                JOIN service_ops.packet p ON pd.packet_id = p.packet_id
                WHERE p.decision_tracking_id = :dt_id
                AND pd.is_active = true
            """), {"dt_id": dt_id}).fetchone()
            
            if decision:
                print(f"  Active Decision: op={decision[1]}, clinical={decision[2]}, is_active={decision[3]}")
            
            # Check ClinicalOps responses
            responses = db.execute(text("""
                SELECT COUNT(*)
                FROM service_ops.send_serviceops
                WHERE decision_tracking_id = :dt_id
                AND payload->>'message_type' = 'CLINICAL_DECISION'
            """), {"dt_id": dt_id}).scalar()
            
            print(f"  ClinicalOps responses: {responses}")
            
            # Check send_integration records
            integration_records = db.execute(text("""
                SELECT COUNT(*)
                FROM service_ops.send_integration
                WHERE decision_tracking_id = :dt_id
            """), {"dt_id": dt_id}).scalar()
            
            print(f"  send_integration records: {integration_records}")
        
        print()
        
    except Exception as e:
        print(f"[ERROR] Error verifying state: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

def main():
    """Main execution"""
    try:
        # Step 1: Reset state
        reset_state()
        
        # Step 2: Verify reset
        verify_state()
        
        # Step 3: Create new ClinicalOps responses
        create_clinical_ops_responses()
        
        # Step 4: Verify responses created
        verify_state()
        
        print("=" * 80)
        print("[OK] SETUP COMPLETE")
        print("=" * 80)
        print()
        print("Next steps:")
        print("1. The ClinicalOpsInboxProcessor should pick up the new responses")
        print("2. It will process them and update decisions, status, and create ESMD payloads")
        print("3. Check the database to verify the workflow")
        
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

