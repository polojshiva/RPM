"""
Check packet_decision UTN fields directly
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB

def check_packet_decision_utn():
    """Check UTN fields in packet_decision"""
    db = SessionLocal()
    
    try:
        # Check both packets
        decision_tracking_ids = [
            'b1c2d3e4-5678-4abc-9def-234567890abc',  # AFFIRM
            'f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067'   # NON_AFFIRM
        ]
        
        for dt_id in decision_tracking_ids:
            packet = db.query(PacketDB).filter(
                PacketDB.decision_tracking_id == dt_id
            ).first()
            
            if packet:
                print(f"\nPacket: {packet.external_id} (packet_id: {packet.packet_id})")
                print(f"  decision_tracking_id: {dt_id}")
                print(f"  detailed_status: {packet.detailed_status}")
                
                # Get ALL packet_decision records (not just active)
                all_decisions = db.query(PacketDecisionDB).filter(
                    PacketDecisionDB.packet_id == packet.packet_id
                ).order_by(PacketDecisionDB.created_at.desc()).all()
                
                print(f"\n  All packet_decision records ({len(all_decisions)}):")
                for i, pd in enumerate(all_decisions):
                    print(f"\n    Decision {i+1}:")
                    print(f"      packet_decision_id: {pd.packet_decision_id}")
                    print(f"      is_active: {pd.is_active}")
                    print(f"      decision_outcome: {pd.decision_outcome}")
                    print(f"      utn: {pd.utn}")
                    print(f"      utn_status: {pd.utn_status}")
                    print(f"      utn_received_at: {pd.utn_received_at}")
                    print(f"      letter_status: {pd.letter_status}")
                    print(f"      created_at: {pd.created_at}")
                    # updated_at might not exist
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_packet_decision_utn()

