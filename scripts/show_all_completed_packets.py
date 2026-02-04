"""
Show all packets that have completed letter generation workflow
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.db import SessionLocal

def main():
    print("="*80)
    print("ALL PACKETS WITH COMPLETED LETTER GENERATION WORKFLOW")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Get all completed packets
        results = db.execute(text("""
            SELECT 
                p.packet_id,
                p.external_id,
                p.detailed_status,
                pd.decision_outcome,
                pd.utn,
                pd.utn_status,
                pd.letter_status,
                pd.operational_decision,
                pd.letter_package->>'filename' as letter_filename,
                pd.letter_package->>'blob_url' as letter_blob_url,
                (SELECT COUNT(*) FROM service_ops.send_integration si 
                 WHERE si.decision_tracking_id = p.decision_tracking_id) as integration_count,
                (SELECT message_id FROM service_ops.send_integration si 
                 WHERE si.decision_tracking_id = p.decision_tracking_id LIMIT 1) as integration_message_id
            FROM service_ops.packet p
            JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
            WHERE pd.is_active = true
              AND pd.letter_status IN ('READY', 'SENT')
            ORDER BY p.packet_id
        """)).fetchall()
        
        print(f"\nFound {len(results)} packet(s) with letters generated\n")
        
        for row in results:
            print(f"Packet: {row[1]} (ID: {row[0]})")
            print(f"  Status: {row[2]}")
            print(f"  Decision: {row[3]}")
            if row[4]:  # UTN
                print(f"  UTN: {row[4]} ({row[5]})")
            print(f"  Letter Status: {row[6]}")
            print(f"  Letter Filename: {row[8] or 'N/A'}")
            if row[9]:  # Blob URL
                print(f"  Letter Blob URL: {row[9][:70]}...")
            print(f"  Operational Decision: {row[7]}")
            print(f"  Sent to Integration: {'Yes' if row[10] > 0 else 'No'}")
            if row[11]:
                print(f"  Integration Message ID: {row[11]}")
            print()
        
        # Summary by decision type
        summary = db.execute(text("""
            SELECT 
                pd.decision_outcome,
                COUNT(*) as count
            FROM service_ops.packet_decision pd
            WHERE pd.is_active = true
              AND pd.letter_status IN ('READY', 'SENT')
            GROUP BY pd.decision_outcome
        """)).fetchall()
        
        print("="*80)
        print("SUMMARY BY DECISION TYPE")
        print("="*80)
        for row in summary:
            print(f"  {row[0] or 'NULL'}: {row[1]} packet(s)")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()



