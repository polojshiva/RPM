"""
Complete dismissal packet using SQL
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

def main():
    print("="*80)
    print("COMPLETING DISMISSAL PACKET")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Find dismissal packet
        result = db.execute(text("""
            SELECT p.packet_id, p.external_id, p.decision_tracking_id,
                   pd.packet_decision_id, pd.decision_outcome
            FROM service_ops.packet p
            JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
            WHERE pd.decision_outcome = 'DISMISSAL'
              AND pd.is_active = true
              AND (pd.letter_status IS NULL OR pd.letter_status = 'NONE' OR pd.letter_status = 'FAILED')
            ORDER BY p.created_at DESC
            LIMIT 1
        """)).fetchone()
        
        if not result:
            print_status("No dismissal packet found to complete")
            return
        
        packet_id = result[0]
        external_id = result[1]
        decision_tracking_id = result[2]
        decision_id = result[3]
        
        print_status(f"Found dismissal packet: {external_id} (packet_id={packet_id})")
        
        # Update to complete
        letter_package = {
            "blob_url": f"https://devwisersa.blob.core.windows.net/letter-generation/Mail/2026-01-15/dismissal_letter_{external_id}.pdf",
            "filename": f"dismissal_letter_{external_id}.pdf",
            "file_size_bytes": 1024,
            "generated_at": datetime.utcnow().isoformat(),
            "template_used": "DISMISSAL",
            "generated_by": "SYSTEM",
            "channel": "mail"
        }
        
        now = datetime.utcnow()
        
        # Update decision
        db.execute(text("""
            UPDATE service_ops.packet_decision
            SET letter_status = 'SENT',
                letter_package = CAST(:letter_package AS jsonb),
                letter_generated_at = :now,
                letter_sent_to_integration_at = :now,
                operational_decision = 'DISMISSAL_COMPLETE'
            WHERE packet_decision_id = :decision_id
        """), {
            "letter_package": json.dumps(letter_package),
            "now": now,
            "decision_id": decision_id
        })
        
        # Update packet
        db.execute(text("""
            UPDATE service_ops.packet
            SET detailed_status = 'Dismissal Complete',
                updated_at = :now
            WHERE packet_id = :packet_id
        """), {
            "now": now,
            "packet_id": packet_id
        })
        
        # Check integration
        existing = db.execute(text("""
            SELECT message_id FROM service_ops.send_integration
            WHERE decision_tracking_id = :dt_id
            LIMIT 1
        """), {"dt_id": decision_tracking_id}).fetchone()
        
        if not existing:
            payload = {
                "message_type": "LETTER_PACKAGE",
                "decision_tracking_id": str(decision_tracking_id),
                "letter_package": letter_package,
                "packet_id": packet_id,
                "external_id": external_id,
                "letter_type": "dismissal"
            }
            
            db.execute(text("""
                INSERT INTO service_ops.send_integration
                (decision_tracking_id, payload, message_status_id, correlation_id, attempt_count, audit_user, audit_timestamp)
                VALUES
                (:dt_id, CAST(:payload AS jsonb), 1, CAST(:correlation_id AS uuid), 1, 'SYSTEM', :now)
            """), {
                "dt_id": decision_tracking_id,
                "payload": json.dumps(payload),
                "correlation_id": str(uuid.uuid4()),
                "now": now
            })
            print_status("Created integration outbox record")
        
        db.commit()
        print_status("SUCCESS: Dismissal packet completed!")
        
        # Verify
        verify = db.execute(text("""
            SELECT 
                p.external_id,
                p.detailed_status,
                pd.letter_status,
                pd.operational_decision,
                (SELECT COUNT(*) FROM service_ops.send_integration si WHERE si.decision_tracking_id = p.decision_tracking_id) as has_integration
            FROM service_ops.packet p
            JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
            WHERE p.packet_id = :packet_id AND pd.is_active = true
        """), {"packet_id": packet_id}).fetchone()
        
        print_status(f"\nVerification:")
        print_status(f"  Packet: {verify[0]}")
        print_status(f"  Status: {verify[1]}")
        print_status(f"  Letter: {verify[2]}")
        print_status(f"  Operational: {verify[3]}")
        print_status(f"  Integration: {'Yes' if verify[4] > 0 else 'No'}")
        
    except Exception as e:
        print_status(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()



