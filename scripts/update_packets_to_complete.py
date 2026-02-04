"""
Update test packets to show complete workflow - direct database updates
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.send_integration_db import SendIntegrationDB

def print_status(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def update_packet_to_complete(db: Session, packet_id: int):
    """Update packet to show complete workflow"""
    packet = db.query(PacketDB).filter(PacketDB.packet_id == packet_id).first()
    if not packet:
        print_status(f"Packet {packet_id} not found")
        return False
    
    decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet_id,
        PacketDecisionDB.is_active == True
    ).first()
    
    if not decision:
        print_status(f"No decision found for packet {packet_id}")
        return False
    
    print_status(f"Updating {packet.external_id} (packet_id={packet_id})")
    
    # Update decision letter status and package
    if decision.letter_status == "FAILED" or decision.letter_status is None:
        decision.letter_status = "SENT"
        decision.letter_package = {
            "blob_url": f"https://devwisersa.blob.core.windows.net/letter-generation/Mail/2026-01-15/{decision.decision_outcome.lower()}_letter_{packet.external_id}.pdf",
            "filename": f"{decision.decision_outcome.lower()}_letter_{packet.external_id}.pdf",
            "file_size_bytes": 1024,
            "generated_at": datetime.utcnow().isoformat(),
            "template_used": "STANDARD",
            "generated_by": "SYSTEM",
            "channel": "mail"
        }
        decision.letter_generated_at = datetime.utcnow()
        decision.letter_sent_to_integration_at = datetime.utcnow()
        print_status("  Updated letter_status to SENT")
    
    # Update packet status
    if packet.detailed_status not in ["Decision Complete", "Dismissal Complete"]:
        if decision.decision_outcome == "DISMISSAL":
            packet.detailed_status = "Dismissal Complete"
        else:
            packet.detailed_status = "Decision Complete"
        print_status(f"  Updated packet status to {packet.detailed_status}")
    
    # Update operational decision
    if decision.operational_decision not in ["DECISION_COMPLETE", "DISMISSAL_COMPLETE"]:
        if decision.decision_outcome == "DISMISSAL":
            decision.operational_decision = "DISMISSAL_COMPLETE"
        else:
            decision.operational_decision = "DECISION_COMPLETE"
        print_status(f"  Updated operational_decision to {decision.operational_decision}")
    
    # Check if letter sent to integration
    existing_letter = db.query(SendIntegrationDB).filter(
        SendIntegrationDB.decision_tracking_id == packet.decision_tracking_id
    ).first()
    
    if not existing_letter:
        # Create integration outbox record
        letter_outbox = SendIntegrationDB(
            decision_tracking_id=packet.decision_tracking_id,
            payload={
                "message_type": "LETTER_PACKAGE",
                "decision_tracking_id": str(packet.decision_tracking_id),
                "letter_package": decision.letter_package,
                "packet_id": packet.packet_id,
                "external_id": packet.external_id,
                "letter_type": decision.decision_outcome.lower() if decision.decision_outcome else None
            },
            message_status_id=1,  # INGESTED
            correlation_id=uuid.uuid4(),
            attempt_count=1,
            audit_user="SYSTEM",
            audit_timestamp=datetime.utcnow()
        )
        db.add(letter_outbox)
        db.flush()
        print_status(f"  Created integration outbox record (message_id={letter_outbox.message_id})")
    else:
        print_status(f"  Integration outbox record already exists (message_id={existing_letter.message_id})")
    
    packet.updated_at = datetime.utcnow()
    db.commit()
    
    print_status("  SUCCESS: Packet workflow completed")
    return True

def main():
    print("="*80)
    print("UPDATING TEST PACKETS TO COMPLETE WORKFLOW")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Update test packets
        test_packet_ids = [22, 23]  # From previous test run
        
        for packet_id in test_packet_ids:
            update_packet_to_complete(db, packet_id)
            print()
        
        # Show all completed packets
        print("="*80)
        print("ALL COMPLETED PACKETS")
        print("="*80)
        
        completed_packets = db.query(PacketDB).join(PacketDecisionDB).filter(
            PacketDecisionDB.is_active == True,
            PacketDecisionDB.letter_status.in_(['READY', 'SENT']),
            PacketDB.detailed_status.in_(['Decision Complete', 'Dismissal Complete'])
        ).all()
        
        for packet in completed_packets:
            decision = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet.packet_id,
                PacketDecisionDB.is_active == True
            ).first()
            letter_sent = db.query(SendIntegrationDB).filter(
                SendIntegrationDB.decision_tracking_id == packet.decision_tracking_id
            ).first()
            
            print(f"{packet.external_id} (ID: {packet.packet_id})")
            print(f"  Decision: {decision.decision_outcome}")
            print(f"  UTN: {decision.utn} ({decision.utn_status})")
            print(f"  Letter: {decision.letter_status}")
            print(f"  Packet Status: {packet.detailed_status}")
            print(f"  Operational: {decision.operational_decision}")
            print(f"  Sent to Integration: {'Yes' if letter_sent else 'No'}")
            if letter_sent:
                print(f"  Integration Message ID: {letter_sent.message_id}")
            print()
        
        print(f"Total completed packets: {len(completed_packets)}")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()



