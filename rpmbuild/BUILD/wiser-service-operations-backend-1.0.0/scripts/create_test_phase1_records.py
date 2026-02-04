"""
Create test Phase 1 records in service_ops.send_serviceops for testing Phase 1/Phase 2 decoupling

Creates:
1. Records with clinical_ops_decision_json set (Phase 1)
2. Links to existing packets or creates minimal test packets
3. Verifies that Phase 1 commits immediately when processed
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.clinical_ops_db import ClinicalOpsInboxDB
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_column_exists(db):
    """Check if clinical_ops_decision_json column exists"""
    try:
        result = db.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_schema = 'service_ops' 
                    AND table_name = 'send_serviceops' 
                    AND column_name = 'clinical_ops_decision_json'
                )
            """)
        ).scalar()
        return result
    except Exception as e:
        logger.warning(f"Error checking column existence: {e}")
        return False


def create_test_phase1_records(count: int = 5, use_existing_packets: bool = True):
    """
    Create test Phase 1 records in service_ops.send_serviceops
    
    Args:
        count: Number of Phase 1 records to create
        use_existing_packets: If True, use existing packets instead of creating new ones
    """
    db = SessionLocal()
    try:
        print("=" * 80)
        print(f"Creating {count} test Phase 1 records in service_ops.send_serviceops")
        print("=" * 80)
        
        # Check if column exists
        column_exists = check_column_exists(db)
        if not column_exists:
            print()
            print("[ERROR] Column 'clinical_ops_decision_json' does not exist in service_ops.send_serviceops")
            print("Please run migration 029_add_clinical_ops_decision_json.sql first:")
            print("  deploy/migrations/029_add_clinical_ops_decision_json.sql")
            print()
            print("To run the migration:")
            print("  psql -U <user> -d <database> -f deploy/migrations/029_add_clinical_ops_decision_json.sql")
            print()
            return []
        
        # Get or create test packets
        test_packets = []
        
        if use_existing_packets:
            # Use existing packets
            existing_packets = db.query(PacketDB).filter(
                PacketDB.is_deleted == False
            ).limit(count).all()
            
            if len(existing_packets) >= count:
                print(f"[INFO] Using {count} existing packets")
                for packet in existing_packets[:count]:
                    test_packets.append({
                        'packet': packet,
                        'decision_tracking_id': str(packet.decision_tracking_id)
                    })
            else:
                print(f"[INFO] Found {len(existing_packets)} existing packets, will create {count - len(existing_packets)} new ones")
                for packet in existing_packets:
                    test_packets.append({
                        'packet': packet,
                        'decision_tracking_id': str(packet.decision_tracking_id)
                    })
        
        # Create additional packets if needed
        for i in range(len(test_packets), count):
            decision_tracking_id = str(uuid4())
            
            # Check if packet exists
            packet = db.query(PacketDB).filter(
                PacketDB.decision_tracking_id == decision_tracking_id
            ).first()
            
            if not packet:
                # Create minimal test packet
                received_date = datetime.now(timezone.utc)
                due_date = received_date  # Will be updated by sync
                
                packet = PacketDB(
                    decision_tracking_id=decision_tracking_id,
                    external_id=f"TEST-PHASE1-{i+1}-{int(datetime.now(timezone.utc).timestamp())}",
                    beneficiary_name="Test Beneficiary",
                    beneficiary_mbi="1S23456789",
                    provider_name="Test Provider",
                    provider_npi="1234567890",
                    service_type="Prior Authorization",
                    received_date=received_date,
                    due_date=due_date,
                    detailed_status="Pending - Clinical Review",
                    validation_status="Pending - Validation",
                    channel_type_id=1,  # Fax
                    submission_type="standard-initial",
                    has_field_validation_errors=False,
                    created_at=datetime.now(timezone.utc)
                )
                db.add(packet)
                db.flush()
                
                # Create minimal extracted fields
                extracted_fields = {
                    'fields': {
                        'Submission Type': {'value': 'standard-initial', 'confidence': 0.95}
                    }
                }
                
                # Create minimal document
                doc = PacketDocumentDB(
                    packet_id=packet.packet_id,
                    external_id=f"DOC-{packet.external_id}",
                    file_name="test.pdf",
                    document_type_id=1,
                    document_unique_identifier=f"DOC-{decision_tracking_id}",
                    extracted_fields=extracted_fields,
                    updated_extracted_fields=extracted_fields,
                    part_type="PART_B",
                    created_at=datetime.now(timezone.utc)
                )
                db.add(doc)
                db.flush()
                
                # Sync packet from extracted fields to set due_date and other fields
                from app.utils.packet_sync import sync_packet_from_extracted_fields
                sync_packet_from_extracted_fields(packet, extracted_fields, datetime.now(timezone.utc), db)
                db.flush()
                
                print(f"  Created test packet: {packet.external_id} (decision_tracking_id={decision_tracking_id})")
            else:
                print(f"  Using existing packet: {packet.external_id} (decision_tracking_id={decision_tracking_id})")
            
            test_packets.append({
                'packet': packet,
                'decision_tracking_id': decision_tracking_id
            })
        
        db.commit()
        print()
        
        # Create Phase 1 records (clinical_ops_decision_json set, json_sent_to_integration = NULL/False)
        created_records = []
        for i, test_data in enumerate(test_packets):
            decision_tracking_id = test_data['decision_tracking_id']
            packet = test_data['packet']
            
            # Alternate between AFFIRM and NON_AFFIRM
            decision_indicator = 'A' if i % 2 == 0 else 'N'
            decision_outcome = 'AFFIRM' if decision_indicator == 'A' else 'NON_AFFIRM'
            
            # Create clinical_ops_decision_json (Phase 1 data)
            clinical_ops_decision_json = {
                "source": "clinical_ops_ddms",
                "claim_id": 1000 + i,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "decision_status": "Approved" if decision_indicator == 'A' else "Denied",
                "decision_indicator": decision_indicator,  # "A" = AFFIRM, "N" = NON_AFFIRM
                "failed_reason_data": None if decision_indicator == 'A' else "Test denial reason",
                "decision_tracking_id": decision_tracking_id
            }
            
            # Insert Phase 1 record into service_ops.send_serviceops using ORM
            # Phase 1: clinical_ops_decision_json IS NOT NULL, json_sent_to_integration IS NULL/False
            from app.models.clinical_ops_db import ClinicalOpsInboxDB
            import uuid as uuid_lib
            
            phase1_record = ClinicalOpsInboxDB(
                decision_tracking_id=decision_tracking_id,
                payload={},  # Empty payload for Phase 1
                clinical_ops_decision_json=clinical_ops_decision_json,
                message_status_id=1,
                json_sent_to_integration=None,  # NULL for Phase 1
                created_at=datetime.now(timezone.utc),
                audit_user='TEST_SCRIPT',
                audit_timestamp=datetime.now(timezone.utc),
                is_deleted=False
            )
            db.add(phase1_record)
            db.flush()
            
            message_id = phase1_record.message_id
            created_at = phase1_record.created_at
            
            created_records.append({
                'message_id': message_id,
                'decision_tracking_id': decision_tracking_id,
                'external_id': packet.external_id,
                'decision_outcome': decision_outcome,
                'created_at': created_at
            })
            
            print(f"  Created Phase 1 record: message_id={message_id}, "
                  f"decision_tracking_id={decision_tracking_id[:8]}..., "
                  f"decision={decision_outcome}, packet={packet.external_id}")
        
        db.commit()
        print()
        print("=" * 80)
        print(f"[SUCCESS] Created {len(created_records)} Phase 1 records")
        print("=" * 80)
        print()
        print("Records created:")
        for rec in created_records:
            print(f"  - message_id={rec['message_id']}, "
                  f"packet={rec['external_id']}, "
                  f"decision={rec['decision_outcome']}, "
                  f"created_at={rec['created_at']}")
        print()
        print("These records will be processed by the ClinicalOps inbox processor.")
        print("Phase 1 should commit immediately, then Phase 2 will be attempted (best-effort).")
        print()
        
        return created_records
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error creating Phase 1 records: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


def verify_phase1_processing():
    """Verify that Phase 1 records were processed and decisions were saved"""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("VERIFYING PHASE 1 PROCESSING")
        print("=" * 80)
        
        # Check for Phase 1 records that have been processed
        # (clinical_ops_decision_json IS NOT NULL, json_sent_to_integration is still NULL/False)
        phase1_records = db.execute(
            text("""
                SELECT 
                    message_id,
                    decision_tracking_id,
                    clinical_ops_decision_json->>'decision_indicator' as decision_indicator,
                    json_sent_to_integration,
                    created_at
                FROM service_ops.send_serviceops
                WHERE clinical_ops_decision_json IS NOT NULL
                    AND (json_sent_to_integration IS NULL OR json_sent_to_integration = false)
                    AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT 10
            """)
        ).fetchall()
        
        print(f"Found {len(phase1_records)} Phase 1 records (not yet processed by Phase 2)")
        print()
        
        # Check packet_decision for saved decisions
        for rec in phase1_records:
            decision_tracking_id = str(rec[1])
            decision_indicator = rec[2]
            
            # Find packet
            packet = db.query(PacketDB).filter(
                PacketDB.decision_tracking_id == decision_tracking_id
            ).first()
            
            if packet:
                # Check for decision
                from app.models.packet_decision_db import PacketDecisionDB
                decision = db.query(PacketDecisionDB).filter(
                    PacketDecisionDB.packet_id == packet.packet_id,
                    PacketDecisionDB.is_active == True
                ).first()
                
                if decision:
                    print(f"  message_id={rec[0]}: Decision SAVED - "
                          f"clinical_decision={decision.clinical_decision}, "
                          f"decision_outcome={decision.decision_outcome}, "
                          f"packet_status={packet.detailed_status}")
                else:
                    print(f"  message_id={rec[0]}: Decision NOT YET SAVED (will be saved when Phase 1 processes)")
            else:
                print(f"  message_id={rec[0]}: Packet not found for decision_tracking_id={decision_tracking_id[:8]}...")
        
        print()
        
    except Exception as e:
        print(f"[ERROR] Error verifying Phase 1 processing: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Create test Phase 1 records for testing decoupling')
    parser.add_argument('--count', type=int, default=5, help='Number of Phase 1 records to create (default: 5)')
    parser.add_argument('--verify', action='store_true', help='Verify Phase 1 processing after creation')
    
    args = parser.parse_args()
    
    # Create records
    records = create_test_phase1_records(count=args.count)
    
    # Verify if requested
    if args.verify:
        print()
        verify_phase1_processing()
