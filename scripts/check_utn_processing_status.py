"""
Check if UTN_SUCCESS records were processed and what happened
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB

def check_utn_processing_status():
    """Check status of UTN_SUCCESS records and their processing"""
    db = SessionLocal()
    
    try:
        print("=" * 80)
        print("CHECKING UTN_SUCCESS PROCESSING STATUS")
        print("=" * 80)
        
        # Find the UTN_SUCCESS records we created
        utn_records = db.query(SendServiceOpsDB).filter(
            SendServiceOpsDB.message_type_id == 2,
            SendServiceOpsDB.is_deleted == False
        ).order_by(SendServiceOpsDB.created_at.desc()).limit(5).all()
        
        print(f"\nFound {len(utn_records)} UTN_SUCCESS records in integration.send_serviceops:")
        print("-" * 80)
        
        for record in utn_records:
            payload = record.payload
            decision_tracking_id = record.decision_tracking_id
            utn = payload.get('unique_tracking_number', 'N/A')
            
            print(f"\nRecord message_id: {record.message_id}")
            print(f"  decision_tracking_id: {decision_tracking_id}")
            print(f"  UTN: {utn}")
            print(f"  created_at: {record.created_at}")
            print(f"  message_type_id: {record.message_type_id}")
            print(f"  channel_type_id: {record.channel_type_id}")
            
            # Check if packet exists
            packet = db.query(PacketDB).filter(
                PacketDB.decision_tracking_id == decision_tracking_id
            ).first()
            
            if packet:
                print(f"\n  Packet Status:")
                print(f"    packet_id: {packet.packet_id}")
                print(f"    external_id: {packet.external_id}")
                print(f"    detailed_status: {packet.detailed_status}")
                
                # Check packet_decision
                packet_decision = db.query(PacketDecisionDB).filter(
                    PacketDecisionDB.packet_id == packet.packet_id,
                    PacketDecisionDB.is_active == True
                ).first()
                
                if packet_decision:
                    print(f"\n  Decision Status:")
                    print(f"    decision_outcome: {packet_decision.decision_outcome}")
                    print(f"    decision_subtype: {packet_decision.decision_subtype}")
                    print(f"    part_type: {packet_decision.part_type}")
                    print(f"    utn: {packet_decision.utn}")
                    print(f"    utn_status: {packet_decision.utn_status}")
                    print(f"    utn_received_at: {packet_decision.utn_received_at}")
                    print(f"    esmd_request_status: {packet_decision.esmd_request_status}")
                    print(f"    letter_status: {packet_decision.letter_status}")
                    print(f"    letter_generated_at: {packet_decision.letter_generated_at}")
                    
                    # Check if letter package was sent to integration
                    from app.models.send_integration_db import SendIntegrationDB
                    letter_records = db.query(SendIntegrationDB).filter(
                        SendIntegrationDB.decision_tracking_id == decision_tracking_id,
                        SendIntegrationDB.payload['message_type'].astext == 'LETTER_PACKAGE'
                    ).all()
                    
                    if letter_records:
                        print(f"\n  Letter Package Sent:")
                        for letter_record in letter_records:
                            print(f"    message_id: {letter_record.message_id}")
                            print(f"    message_status_id: {letter_record.message_status_id}")
                            print(f"    created_at: {letter_record.created_at}")
                    else:
                        print(f"\n  Letter Package: NOT SENT YET")
                else:
                    print(f"\n  Decision: NOT FOUND")
            else:
                print(f"\n  Packet: NOT FOUND for decision_tracking_id={decision_tracking_id}")
        
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total UTN_SUCCESS records: {len(utn_records)}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_utn_processing_status()

