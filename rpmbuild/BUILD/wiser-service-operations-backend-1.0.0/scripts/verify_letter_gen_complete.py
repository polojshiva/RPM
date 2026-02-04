"""
Verify letter generation workflow completion for existing packets
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.models.send_integration_db import SendIntegrationDB

def print_status(msg):
    print(msg)

def verify_packet_completion(db: Session, packet: PacketDB):
    """Verify a packet has completed letter generation workflow"""
    decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).first()
    
    if not decision:
        return None, "No decision found"
    
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id
    ).first()
    
    # Check letter status
    letter_status = decision.letter_status
    letter_package = decision.letter_package or {}
    
    # Check if letter was sent to integration
    letter_sent = db.query(SendIntegrationDB).filter(
        SendIntegrationDB.decision_tracking_id == packet.decision_tracking_id
    ).first()
    
    result = {
        "packet_id": packet.packet_id,
        "external_id": packet.external_id,
        "decision_outcome": decision.decision_outcome,
        "utn": decision.utn,
        "utn_status": decision.utn_status,
        "letter_status": letter_status,
        "letter_has_blob_url": bool(letter_package.get("blob_url")),
        "letter_filename": letter_package.get("filename"),
        "packet_status": packet.detailed_status,
        "operational_decision": decision.operational_decision,
        "letter_sent_to_integration": letter_sent is not None,
        "letter_sent_message_id": letter_sent.message_id if letter_sent else None
    }
    
    return result, None

def main():
    print("="*80)
    print("VERIFYING LETTER GENERATION WORKFLOW COMPLETION")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Find packets with letter status SENT or READY
        packets = db.query(PacketDB).join(PacketDecisionDB).filter(
            and_(
                PacketDecisionDB.is_active == True,
                PacketDecisionDB.letter_status.in_(['READY', 'SENT'])
            )
        ).limit(20).all()
        
        print(f"\nFound {len(packets)} packet(s) with letters generated\n")
        
        for packet in packets:
            result, error = verify_packet_completion(db, packet)
            if error:
                print(f"ERROR: {packet.external_id} - {error}")
                continue
            
            print(f"Packet: {result['external_id']} (ID: {result['packet_id']})")
            print(f"  Decision: {result['decision_outcome']}")
            print(f"  UTN: {result['utn']} (Status: {result['utn_status']})")
            print(f"  Letter Status: {result['letter_status']}")
            print(f"  Letter Filename: {result['letter_filename']}")
            print(f"  Has Blob URL: {result['letter_has_blob_url']}")
            print(f"  Packet Status: {result['packet_status']}")
            print(f"  Operational Decision: {result['operational_decision']}")
            print(f"  Sent to Integration: {result['letter_sent_to_integration']}")
            if result['letter_sent_message_id']:
                print(f"  Integration Message ID: {result['letter_sent_message_id']}")
            print()
        
        # Summary
        complete_count = sum(1 for p in packets if verify_packet_completion(db, p)[0] and 
                           verify_packet_completion(db, p)[0]['letter_status'] == 'SENT' and
                           verify_packet_completion(db, p)[0]['letter_sent_to_integration'])
        
        print(f"Summary: {complete_count}/{len(packets)} packets fully completed (letter SENT to integration)")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()



