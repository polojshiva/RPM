"""
Check what happened in the database after ClinicalOps responses were processed
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text
from datetime import datetime

def check_processing_state():
    """Check the state of packets and decisions after ClinicalOps processing"""
    db = SessionLocal()
    try:
        # Get the two decision_tracking_ids from send_clinicalops
        print("=" * 80)
        print("CHECKING CLINICAL OPS PROCESSING STATE")
        print("=" * 80)
        print()
        
        # Get records from send_clinicalops
        clinical_ops_records = db.execute(text("""
            SELECT 
                message_id,
                decision_tracking_id,
                payload->>'packet_id' as packet_id,
                created_at
            FROM service_ops.send_clinicalops
            ORDER BY message_id
        """)).fetchall()
        
        print(f"Found {len(clinical_ops_records)} records in send_clinicalops:")
        for rec in clinical_ops_records:
            print(f"  - message_id={rec[0]}, decision_tracking_id={rec[1]}, packet_id={rec[2]}")
        print()
        
        # Check for corresponding records in send_serviceops (ClinicalOps responses)
        for rec in clinical_ops_records:
            decision_tracking_id = rec[1]
            print(f"Checking decision_tracking_id: {decision_tracking_id}")
            print("-" * 80)
            
            # Check send_serviceops (ClinicalOps responses)
            responses = db.execute(text("""
                SELECT 
                    message_id,
                    decision_tracking_id,
                    payload->>'message_type' as message_type,
                    payload->>'decision' as decision,
                    created_at
                FROM service_ops.send_serviceops
                WHERE decision_tracking_id = :dt_id
                AND payload->>'message_type' = 'CLINICAL_DECISION'
                ORDER BY message_id
            """), {"dt_id": decision_tracking_id}).fetchall()
            
            print(f"  ClinicalOps responses in send_serviceops: {len(responses)}")
            for resp in responses:
                print(f"    - message_id={resp[0]}, decision={resp[3]}, created_at={resp[4]}")
            
            # Check packet_decision records (join with packet to get decision_tracking_id)
            decisions = db.execute(text("""
                SELECT 
                    pd.packet_decision_id,
                    p.decision_tracking_id,
                    pd.operational_decision,
                    pd.clinical_decision,
                    pd.is_active,
                    pd.created_at
                FROM service_ops.packet_decision pd
                JOIN service_ops.packet p ON pd.packet_id = p.packet_id
                WHERE p.decision_tracking_id = :dt_id
                ORDER BY pd.created_at DESC
            """), {"dt_id": decision_tracking_id}).fetchall()
            
            print(f"  packet_decision records: {len(decisions)}")
            for dec in decisions:
                print(f"    - decision_id={dec[0]}, op_decision={dec[2]}, clinical_decision={dec[3]}, is_active={dec[4]}, created_at={dec[5]}")
            
            # Check packet status
            packet = db.execute(text("""
                SELECT 
                    packet_id,
                    external_id,
                    detailed_status,
                    decision_tracking_id
                FROM service_ops.packet
                WHERE decision_tracking_id = :dt_id
            """), {"dt_id": decision_tracking_id}).fetchone()
            
            if packet:
                print(f"  Packet status: detailed_status={packet[2]}")
            
            # Check send_integration (UTN/letter packages)
            integration_records = db.execute(text("""
                SELECT 
                    message_id,
                    decision_tracking_id,
                    payload->>'message_type' as message_type,
                    created_at
                FROM service_ops.send_integration
                WHERE decision_tracking_id = :dt_id
                ORDER BY created_at
            """), {"dt_id": decision_tracking_id}).fetchall()
            
            print(f"  send_integration records: {len(integration_records)}")
            for int_rec in integration_records:
                print(f"    - message_id={int_rec[0]}, message_type={int_rec[2]}, created_at={int_rec[3]}")
            
            print()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_processing_state()

