"""
Script to create synthetic UTN_SUCCESS record in integration.send_serviceops
Based on sample record from test server
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_decision_db import PacketDecisionDB
from datetime import datetime
import uuid

def create_synthetic_utn_record():
    """Create synthetic UTN_SUCCESS record for Standard PA"""
    db = SessionLocal()
    
    try:
        # Find AFFIRM and NON_AFFIRM decisions
        from app.models.packet_db import PacketDB
        
        affirm_decision = db.query(PacketDecisionDB).join(
            PacketDB, PacketDecisionDB.packet_id == PacketDB.packet_id
        ).filter(
            PacketDecisionDB.decision_outcome == 'AFFIRM',
            PacketDecisionDB.decision_subtype == 'STANDARD_PA'
        ).order_by(PacketDecisionDB.created_at.desc()).first()
        
        non_affirm_decision = db.query(PacketDecisionDB).join(
            PacketDB, PacketDecisionDB.packet_id == PacketDB.packet_id
        ).filter(
            PacketDecisionDB.decision_outcome == 'NON_AFFIRM',
            PacketDecisionDB.decision_subtype == 'STANDARD_PA'
        ).order_by(PacketDecisionDB.created_at.desc()).first()
        
        if not affirm_decision:
            print("ERROR: No AFFIRM STANDARD_PA decision found")
            return
        
        if not non_affirm_decision:
            print("ERROR: No NON_AFFIRM STANDARD_PA decision found")
            return
        
        # Get packets for the decisions
        affirm_packet = db.query(PacketDB).filter(PacketDB.packet_id == affirm_decision.packet_id).first()
        non_affirm_packet = db.query(PacketDB).filter(PacketDB.packet_id == non_affirm_decision.packet_id).first()
        
        affirm_tracking_id = affirm_packet.decision_tracking_id
        non_affirm_tracking_id = non_affirm_packet.decision_tracking_id
        
        print(f"SUCCESS: Found AFFIRM decision_tracking_id: {affirm_tracking_id}")
        print(f"SUCCESS: Found NON_AFFIRM decision_tracking_id: {non_affirm_tracking_id}")
        
        # Create UTN_SUCCESS record for AFFIRM (based on sample)
        # Generate synthetic UTN and unique_id
        import random
        import string
        
        def generate_utn():
            """Generate synthetic UTN: 14 alphanumeric characters"""
            prefix = "JLB"
            date_part = "86260113"  # YYYYMMDD format
            suffix = ''.join(random.choices(string.digits, k=3))
            return f"{prefix}{date_part}{suffix}"
        
        def generate_unique_id():
            """Generate synthetic unique_id: R + 13 digits"""
            return f"R{''.join(random.choices(string.digits, k=13))}"
        
        # Get esmd_transaction_id from packet.case_id (for ESMD channel)
        esmd_transaction_id = affirm_packet.case_id or "PER0007271785EC"
        
        # Create payload based on sample structure
        utn_affirm = generate_utn()
        unique_id_affirm = generate_unique_id()
        
        payload_affirm = {
            "unique_id": unique_id_affirm,
            "upload_id": 538,  # From sample
            "created_at": datetime.utcnow().isoformat() + "Z",
            "message_type": "UTN",
            "decision_package": {
                "filename": f"ESMD2.P.L19.{esmd_transaction_id}.WMP001.D011226.T0410046.zip",
                "file_size": 1867,
                "package_id": 649,
                "status_code": "PICKUP_CONFIRMED",
                "package_type": "DECISION",
                "blob_storage_path": f"v2/2026/01-12/{esmd_transaction_id}/ESMD2.P.L19.{esmd_transaction_id}.WMP001.D011226.T0410046.zip"
            },
            "destination_type": "MAC",
            "esmd_transaction_id": esmd_transaction_id,
            "decision_tracking_id": str(affirm_tracking_id),
            "unique_tracking_number": utn_affirm
        }
        
        # Check if UTN record already exists for AFFIRM (any message_type_id)
        existing_affirm = db.query(SendServiceOpsDB).filter(
            SendServiceOpsDB.decision_tracking_id == str(affirm_tracking_id),
            SendServiceOpsDB.is_deleted == False
        ).first()
        
        if existing_affirm:
            print(f"WARNING: Record already exists for AFFIRM decision_tracking_id: {affirm_tracking_id}")
            print(f"   Existing message_id: {existing_affirm.message_id}, message_type_id: {existing_affirm.message_type_id}")
            # Update existing record to be UTN_SUCCESS
            existing_affirm.payload = payload_affirm
            existing_affirm.message_type_id = 2  # UTN_SUCCESS
            existing_affirm.channel_type_id = 3  # ESMD
            existing_affirm.audit_timestamp = datetime.utcnow()
            utn_record_affirm = existing_affirm
        else:
            # Create record for AFFIRM
            utn_record_affirm = SendServiceOpsDB(
                decision_tracking_id=str(affirm_tracking_id),
                payload=payload_affirm,
                message_type_id=2,  # UTN_SUCCESS
                channel_type_id=3,  # ESMD
                is_deleted=False,
                created_at=datetime.utcnow(),
                audit_user="SYSTEM",
                audit_timestamp=datetime.utcnow()
            )
            
            db.add(utn_record_affirm)
        
        db.flush()
        
        print(f"\nSUCCESS: Created UTN_SUCCESS record for AFFIRM:")
        print(f"   message_id: {utn_record_affirm.message_id}")
        print(f"   decision_tracking_id: {affirm_tracking_id}")
        print(f"   UTN: {utn_affirm}")
        print(f"   unique_id: {unique_id_affirm}")
        print(f"   esmd_transaction_id: {esmd_transaction_id}")
        
        # Create UTN_SUCCESS record for NON_AFFIRM
        utn_non_affirm = generate_utn()
        unique_id_non_affirm = generate_unique_id()
        
        # Get esmd_transaction_id for NON_AFFIRM packet
        esmd_transaction_id_non_affirm = non_affirm_packet.case_id or "PER0007271786EC"
        
        payload_non_affirm = {
            "unique_id": unique_id_non_affirm,
            "upload_id": 539,  # Different upload_id
            "created_at": datetime.utcnow().isoformat() + "Z",
            "message_type": "UTN",
            "decision_package": {
                "filename": f"ESMD2.P.L19.{esmd_transaction_id_non_affirm}.WMP001.D011226.T0410047.zip",
                "file_size": 1867,
                "package_id": 650,
                "status_code": "PICKUP_CONFIRMED",
                "package_type": "DECISION",
                "blob_storage_path": f"v2/2026/01-12/{esmd_transaction_id_non_affirm}/ESMD2.P.L19.{esmd_transaction_id_non_affirm}.WMP001.D011226.T0410047.zip"
            },
            "destination_type": "MAC",
            "esmd_transaction_id": esmd_transaction_id_non_affirm,
            "decision_tracking_id": str(non_affirm_tracking_id),
            "unique_tracking_number": utn_non_affirm
        }
        
        # Check if record already exists for NON_AFFIRM (any message_type_id)
        existing_non_affirm = db.query(SendServiceOpsDB).filter(
            SendServiceOpsDB.decision_tracking_id == str(non_affirm_tracking_id),
            SendServiceOpsDB.is_deleted == False
        ).first()
        
        if existing_non_affirm:
            print(f"WARNING: Record already exists for NON_AFFIRM decision_tracking_id: {non_affirm_tracking_id}")
            print(f"   Existing message_id: {existing_non_affirm.message_id}, message_type_id: {existing_non_affirm.message_type_id}")
            # Update existing record to be UTN_SUCCESS
            existing_non_affirm.payload = payload_non_affirm
            existing_non_affirm.message_type_id = 2  # UTN_SUCCESS
            existing_non_affirm.channel_type_id = 3  # ESMD
            existing_non_affirm.audit_timestamp = datetime.utcnow()
            utn_record_non_affirm = existing_non_affirm
        else:
            utn_record_non_affirm = SendServiceOpsDB(
                decision_tracking_id=str(non_affirm_tracking_id),
                payload=payload_non_affirm,
                message_type_id=2,  # UTN_SUCCESS
                channel_type_id=3,  # ESMD
                is_deleted=False,
                created_at=datetime.utcnow(),
                audit_user="SYSTEM",
                audit_timestamp=datetime.utcnow()
            )
            
            db.add(utn_record_non_affirm)
        
        db.flush()
        
        print(f"\nSUCCESS: Created UTN_SUCCESS record for NON_AFFIRM:")
        print(f"   message_id: {utn_record_non_affirm.message_id}")
        print(f"   decision_tracking_id: {non_affirm_tracking_id}")
        print(f"   UTN: {utn_non_affirm}")
        print(f"   unique_id: {unique_id_non_affirm}")
        print(f"   esmd_transaction_id: {esmd_transaction_id_non_affirm}")
        
        db.commit()
        
        print(f"\nSUCCESS: Successfully created 2 UTN_SUCCESS records in integration.send_serviceops")
        print(f"   They will be processed by IntegrationInboxService on next poll")
        
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    create_synthetic_utn_record()

