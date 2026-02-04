"""
Manual Test Script: Duplicate Decision Records Fix

Simulates the Phase 1 retry scenario where:
1. Phase 1 message is processed (creates decision with AFFIRM)
2. Phase 2 fails (JSON Generator fails)
3. Phase 1 message is retried (should NOT create duplicate decision)

This script verifies that the idempotency fix prevents duplicate decision records.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor
from datetime import datetime, timezone
import uuid

def test_duplicate_decision_fix():
    """
    Test that processing the same Phase 1 message twice does not create duplicate decision records.
    
    Steps:
    1. Create a test packet
    2. Process Phase 1 message first time (should create decision)
    3. Process same Phase 1 message second time (should NOT create duplicate)
    4. Verify decision count increased by at most 1 (not 2)
    """
    db: Session = SessionLocal()
    processor = ClinicalOpsInboxProcessor()
    
    try:
        # Step 1: Create test packet
        decision_tracking_id = str(uuid.uuid4())
        test_packet = PacketDB(
            external_id=f"TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            decision_tracking_id=decision_tracking_id,
            detailed_status="Pending - Clinical Review",
            created_at=datetime.now(timezone.utc)
        )
        db.add(test_packet)
        db.commit()
        db.refresh(test_packet)
        
        print(f"✅ Created test packet: packet_id={test_packet.packet_id}, decision_tracking_id={decision_tracking_id}")
        
        # Create test document (required for decision creation)
        from app.models.document_db import PacketDocumentDB
        test_document = PacketDocumentDB(
            packet_id=test_packet.packet_id,
            part_type="B",
            created_at=datetime.now(timezone.utc)
        )
        db.add(test_document)
        db.commit()
        db.refresh(test_document)
        
        print(f"✅ Created test document: packet_document_id={test_document.packet_document_id}")
        
        # Step 2: Get initial decision count
        initial_count = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == test_packet.packet_id
        ).count()
        print(f"📊 Initial decision count: {initial_count}")
        
        # Step 3: Process Phase 1 message first time
        clinical_ops_decision_json = {
            "source": "clinical_ops_ddms",
            "claim_id": 9999,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision_status": "Approved",
            "decision_indicator": "A",  # A = AFFIRM
            "failed_reason_data": None,
            "decision_tracking_id": decision_tracking_id
        }
        
        message = {
            'decision_tracking_id': decision_tracking_id,
            'message_id': 1,
            'created_at': datetime.now(timezone.utc)
        }
        
        import asyncio
        asyncio.run(processor._handle_clinical_decision(
            db, message, clinical_ops_decision_json
        ))
        db.commit()
        
        # Get decision count after first processing
        count_after_first = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == test_packet.packet_id
        ).count()
        print(f"📊 Decision count after first processing: {count_after_first} (increased by {count_after_first - initial_count})")
        
        # Step 4: Process same Phase 1 message second time (simulating retry)
        print("\n🔄 Processing same Phase 1 message again (simulating retry after Phase 2 failure)...")
        asyncio.run(processor._handle_clinical_decision(
            db, message, clinical_ops_decision_json
        ))
        db.commit()
        
        # Get decision count after second processing
        count_after_second = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == test_packet.packet_id
        ).count()
        print(f"📊 Decision count after second processing: {count_after_second} (increased by {count_after_second - count_after_first})")
        
        # Step 5: Verify results
        total_increase = count_after_second - initial_count
        increase_on_retry = count_after_second - count_after_first
        
        print("\n" + "="*60)
        print("TEST RESULTS:")
        print("="*60)
        print(f"Total decision records created: {total_increase}")
        print(f"Decision records created on retry: {increase_on_retry}")
        
        if increase_on_retry == 0:
            print("✅ PASS: No duplicate decision created on retry (idempotent)")
        else:
            print(f"❌ FAIL: Created {increase_on_retry} duplicate decision(s) on retry")
            return False
        
        if total_increase <= 1:
            print("✅ PASS: Total decision count increased by at most 1")
        else:
            print(f"❌ FAIL: Total decision count increased by {total_increase} (expected at most 1)")
            return False
        
        # Verify active decision has correct values
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        active_decision = WorkflowOrchestratorService.get_active_decision(db, test_packet.packet_id)
        if active_decision:
            print(f"✅ Active decision: clinical_decision={active_decision.clinical_decision}, decision_outcome={active_decision.decision_outcome}")
            if active_decision.clinical_decision == 'AFFIRM' and active_decision.decision_outcome == 'AFFIRM':
                print("✅ PASS: Active decision has correct values")
            else:
                print(f"❌ FAIL: Active decision has incorrect values")
                return False
        else:
            print("❌ FAIL: No active decision found")
            return False
        
        print("="*60)
        print("✅ ALL TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup: Delete test packet and decisions
        try:
            db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == test_packet.packet_id
            ).delete()
            db.query(PacketDocumentDB).filter(
                PacketDocumentDB.packet_id == test_packet.packet_id
            ).delete()
            db.query(PacketDB).filter(
                PacketDB.packet_id == test_packet.packet_id
            ).delete()
            db.commit()
            print("\n🧹 Cleaned up test data")
        except:
            pass
        db.close()


if __name__ == '__main__':
    print("="*60)
    print("Manual Test: Duplicate Decision Records Fix")
    print("="*60)
    print()
    
    success = test_duplicate_decision_fix()
    
    if success:
        print("\n✅ Test completed successfully")
        sys.exit(0)
    else:
        print("\n❌ Test failed")
        sys.exit(1)
