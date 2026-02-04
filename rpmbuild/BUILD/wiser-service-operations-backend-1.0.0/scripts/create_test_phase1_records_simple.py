"""
Simple script to create test Phase 1 records using existing packets
This script will work even if the clinical_ops_decision_json column doesn't exist yet
(It will just inform you that the column is missing)
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.services.db import SessionLocal
from app.models.packet_db import PacketDB


def check_and_create_phase1_records(count: int = 3):
    """
    Check if column exists, then create Phase 1 records using existing packets
    """
    db = SessionLocal()
    try:
        print("=" * 80)
        print(f"Creating {count} test Phase 1 records")
        print("=" * 80)
        print()
        
        # Check if column exists
        column_check = db.execute(
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
        
        if not column_check:
            print("[ERROR] Column 'clinical_ops_decision_json' does not exist!")
            print()
            print("Please run the migration first:")
            print("  deploy/migrations/029_add_clinical_ops_decision_json.sql")
            print()
            print("After running the migration, this script will work.")
            return []
        
        print("[OK] Column 'clinical_ops_decision_json' exists")
        print()
        
        # Get existing packets
        packets = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id.isnot(None)
        ).limit(count).all()
        
        if len(packets) < count:
            print(f"[WARNING] Only found {len(packets)} existing packets (requested {count})")
            print("Will create records for available packets.")
            print()
        
        if not packets:
            print("[ERROR] No existing packets found in database")
            print("Please create some packets first or run the migration to add the column.")
            return []
        
        print(f"Using {len(packets)} existing packets:")
        for p in packets:
            print(f"  - {p.external_id}: {p.decision_tracking_id}")
        print()
        
        # Create Phase 1 records
        created_records = []
        for i, packet in enumerate(packets):
            decision_tracking_id = str(packet.decision_tracking_id)
            
            # Alternate between AFFIRM and NON_AFFIRM
            decision_indicator = 'A' if i % 2 == 0 else 'N'
            decision_outcome = 'AFFIRM' if decision_indicator == 'A' else 'NON_AFFIRM'
            
            # Create clinical_ops_decision_json (Phase 1 data)
            clinical_ops_decision_json = {
                "source": "clinical_ops_ddms",
                "claim_id": 1000 + i,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "decision_status": "Approved" if decision_indicator == 'A' else "Denied",
                "decision_indicator": decision_indicator,
                "failed_reason_data": None if decision_indicator == 'A' else "Test denial reason",
                "decision_tracking_id": decision_tracking_id
            }
            
            # Insert using raw SQL (more reliable)
            result = db.execute(
                text("""
                    INSERT INTO service_ops.send_serviceops (
                        decision_tracking_id,
                        payload,
                        clinical_ops_decision_json,
                        message_status_id,
                        json_sent_to_integration,
                        created_at,
                        audit_user,
                        audit_timestamp,
                        is_deleted
                    ) VALUES (
                        CAST(:dt_id AS uuid),
                        '{}'::jsonb,
                        CAST(:clinical_ops_json AS jsonb),
                        1,
                        NULL,
                        NOW(),
                        'TEST_SCRIPT',
                        NOW(),
                        false
                    )
                    RETURNING message_id, created_at
                """),
                {
                    'dt_id': decision_tracking_id,
                    'clinical_ops_json': json.dumps(clinical_ops_decision_json)
                }
            )
            record = result.fetchone()
            message_id = record[0]
            created_at = record[1]
            
            created_records.append({
                'message_id': message_id,
                'decision_tracking_id': decision_tracking_id,
                'external_id': packet.external_id,
                'decision_outcome': decision_outcome,
                'created_at': created_at
            })
            
            print(f"  Created Phase 1 record: message_id={message_id}, "
                  f"packet={packet.external_id}, decision={decision_outcome}")
        
        db.commit()
        print()
        print("=" * 80)
        print(f"[SUCCESS] Created {len(created_records)} Phase 1 records")
        print("=" * 80)
        print()
        print("These records will be processed by the ClinicalOps inbox processor.")
        print("Phase 1 should commit immediately, then Phase 2 will be attempted (best-effort).")
        print()
        print("To verify processing:")
        print("  1. Wait for the next poll cycle (default: 5 minutes)")
        print("  2. Check packet_decision table for saved decisions")
        print("  3. Check packet.detailed_status for status updates")
        print()
        
        return created_records
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Create test Phase 1 records')
    parser.add_argument('--count', type=int, default=3, help='Number of records to create (default: 3)')
    
    args = parser.parse_args()
    
    check_and_create_phase1_records(count=args.count)
