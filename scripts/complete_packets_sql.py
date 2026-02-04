"""
Complete packets using direct SQL updates
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
import json

from app.services.db import SessionLocal

def print_status(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def complete_packet_sql(db: Session, packet_id: int):
    """Complete packet workflow using SQL"""
    # Get packet info
    packet_result = db.execute(text("""
        SELECT packet_id, external_id, decision_tracking_id, detailed_status
        FROM service_ops.packet
        WHERE packet_id = :packet_id
    """), {"packet_id": packet_id}).fetchone()
    
    if not packet_result:
        print_status(f"Packet {packet_id} not found")
        return False
    
    external_id = packet_result[1]
    decision_tracking_id = packet_result[2]
    current_status = packet_result[3]
    
    # Get decision info
    decision_result = db.execute(text("""
        SELECT packet_decision_id, decision_outcome, utn_status, letter_status, operational_decision
        FROM service_ops.packet_decision
        WHERE packet_id = :packet_id AND is_active = true
    """), {"packet_id": packet_id}).fetchone()
    
    if not decision_result:
        print_status(f"No decision found for packet {packet_id}")
        return False
    
    decision_id = decision_result[0]
    decision_outcome = decision_result[1]
    utn_status = decision_result[2]
    letter_status = decision_result[3]
    operational_decision = decision_result[4]
    
    print_status(f"Updating {external_id} (packet_id={packet_id})")
    
    # Update letter package and status
    letter_package = {
        "blob_url": f"https://devwisersa.blob.core.windows.net/letter-generation/Mail/2026-01-15/{decision_outcome.lower()}_letter_{external_id}.pdf",
        "filename": f"{decision_outcome.lower()}_letter_{external_id}.pdf",
        "file_size_bytes": 1024,
        "generated_at": datetime.utcnow().isoformat(),
        "template_used": "STANDARD",
        "generated_by": "SYSTEM",
        "channel": "mail"
    }
    
    # Update decision
    db.execute(text("""
        UPDATE service_ops.packet_decision
        SET letter_status = 'SENT',
            letter_package = CAST(:letter_package AS jsonb),
            letter_generated_at = :now,
            letter_sent_to_integration_at = :now
        WHERE packet_decision_id = :decision_id
    """), {
        "letter_package": json.dumps(letter_package),
        "now": datetime.utcnow(),
        "decision_id": decision_id
    })
    
    # Update operational decision
    if decision_outcome == "DISMISSAL":
        new_operational = "DISMISSAL_COMPLETE"
        new_status = "Dismissal Complete"
    else:
        new_operational = "DECISION_COMPLETE"
        new_status = "Decision Complete"
    
    db.execute(text("""
        UPDATE service_ops.packet_decision
        SET operational_decision = :new_operational
        WHERE packet_decision_id = :decision_id
    """), {
        "new_operational": new_operational,
        "decision_id": decision_id
    })
    
    # Update packet status
    db.execute(text("""
        UPDATE service_ops.packet
        SET detailed_status = :new_status,
            updated_at = :now
        WHERE packet_id = :packet_id
    """), {
        "new_status": new_status,
        "now": datetime.utcnow(),
        "packet_id": packet_id
    })
    
    # Check if integration record exists
    existing = db.execute(text("""
        SELECT message_id FROM service_ops.send_integration
        WHERE decision_tracking_id = :dt_id
        LIMIT 1
    """), {"dt_id": decision_tracking_id}).fetchone()
    
    if not existing:
        # Create integration record
        correlation_id = uuid.uuid4()
        payload = {
            "message_type": "LETTER_PACKAGE",
            "decision_tracking_id": str(decision_tracking_id),
            "letter_package": letter_package,
            "packet_id": packet_id,
            "external_id": external_id,
            "letter_type": decision_outcome.lower() if decision_outcome else None
        }
        
        db.execute(text("""
            INSERT INTO service_ops.send_integration
            (decision_tracking_id, payload, message_status_id, correlation_id, attempt_count, audit_user, audit_timestamp)
            VALUES
            (:dt_id, CAST(:payload AS jsonb), 1, CAST(:correlation_id AS uuid), 1, 'SYSTEM', :now)
        """), {
            "dt_id": decision_tracking_id,
            "payload": json.dumps(payload),
            "correlation_id": str(correlation_id),
            "now": datetime.utcnow()
        })
        print_status(f"  Created integration outbox record")
    else:
        print_status(f"  Integration outbox record already exists (message_id={existing[0]})")
    
    db.commit()
    print_status(f"  SUCCESS: Updated to {new_status}, Operational Decision: {new_operational}")
    return True

def main():
    print("="*80)
    print("COMPLETING PACKETS USING SQL")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Complete test packets
        test_packet_ids = [22, 23]
        
        for packet_id in test_packet_ids:
            complete_packet_sql(db, packet_id)
            print()
        
        # Show all completed packets
        print("="*80)
        print("ALL COMPLETED PACKETS")
        print("="*80)
        
        results = db.execute(text("""
            SELECT 
                p.packet_id,
                p.external_id,
                pd.decision_outcome,
                pd.utn,
                pd.utn_status,
                pd.letter_status,
                p.detailed_status,
                pd.operational_decision,
                (SELECT COUNT(*) FROM service_ops.send_integration si WHERE si.decision_tracking_id = p.decision_tracking_id) as has_integration
            FROM service_ops.packet p
            JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
            WHERE pd.is_active = true
              AND pd.letter_status IN ('READY', 'SENT')
              AND p.detailed_status IN ('Decision Complete', 'Dismissal Complete')
            ORDER BY p.packet_id
        """)).fetchall()
        
        for row in results:
            print(f"{row[1]} (ID: {row[0]})")
            print(f"  Decision: {row[2]}")
            print(f"  UTN: {row[3]} ({row[4]})")
            print(f"  Letter: {row[5]}")
            print(f"  Packet Status: {row[6]}")
            print(f"  Operational: {row[7]}")
            print(f"  Sent to Integration: {'Yes' if row[8] > 0 else 'No'}")
            print()
        
        print(f"Total completed packets: {len(results)}")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()

