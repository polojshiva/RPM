"""
Test ClinicalOps rejection workflow with automatic migration check
This script will:
1. Check if migrations are needed
2. Run migrations if needed
3. Find a test record
4. Simulate rejection
5. Process it and show results
"""
import os
import sys
import argparse
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.services.db import SessionLocal
from app.models.send_clinicalops_db import SendClinicalOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_validation_db import PacketValidationDB
from app.services.clinical_ops_rejection_processor import ClinicalOpsRejectionProcessor


def check_column_exists(db: Session, table_name: str, column_name: str) -> bool:
    """Check if a column exists"""
    result = db.execute(text("""
        SELECT EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = :table_name
            AND column_name = :column_name
        )
    """), {"table_name": table_name, "column_name": column_name}).scalar()
    return result


def run_migrations_if_needed(db: Session):
    """Run migrations if columns don't exist"""
    print("\nChecking migrations...")
    
    needs_migration = False
    
    # Check migration 023 columns
    if not check_column_exists(db, "send_clinicalops", "is_picked"):
        print("[MIGRATION NEEDED] Column is_picked does not exist")
        needs_migration = True
    
    if not check_column_exists(db, "send_clinicalops", "error_reason"):
        print("[MIGRATION NEEDED] Column error_reason does not exist")
        needs_migration = True
    
    # Check migration 024 columns
    if not check_column_exists(db, "send_clinicalops", "is_looped_back_to_validation"):
        print("[MIGRATION NEEDED] Column is_looped_back_to_validation does not exist")
        needs_migration = True
    
    if not check_column_exists(db, "send_clinicalops", "retry_count"):
        print("[MIGRATION NEEDED] Column retry_count does not exist")
        needs_migration = True
    
    if not needs_migration:
        print("[OK] All migrations are already applied")
        return
    
    print("\nRunning migrations...")
    
    # Migration 023
    if not check_column_exists(db, "send_clinicalops", "is_picked"):
        print("  Adding is_picked column...")
        db.execute(text("ALTER TABLE service_ops.send_clinicalops ADD COLUMN IF NOT EXISTS is_picked BOOLEAN DEFAULT NULL;"))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.is_picked IS 
                'Indicates if ClinicalOps has reviewed this record. NULL = not yet reviewed, TRUE = picked and processed successfully, FALSE = picked but has errors (check error_reason).';
        """))
    
    if not check_column_exists(db, "send_clinicalops", "error_reason"):
        print("  Adding error_reason column...")
        db.execute(text("ALTER TABLE service_ops.send_clinicalops ADD COLUMN IF NOT EXISTS error_reason VARCHAR(500) DEFAULT NULL;"))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.error_reason IS 
                'Reason why the record was rejected by ClinicalOps (e.g., "Missing HCPCS code", "Invalid provider NPI"). Only populated when is_picked = FALSE.';
        """))
    
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_send_clinicalops_is_picked 
        ON service_ops.send_clinicalops(is_picked)
        WHERE is_picked IS NULL;
    """))
    
    # Migration 024
    if not check_column_exists(db, "send_clinicalops", "is_looped_back_to_validation"):
        print("  Adding is_looped_back_to_validation column...")
        db.execute(text("ALTER TABLE service_ops.send_clinicalops ADD COLUMN IF NOT EXISTS is_looped_back_to_validation BOOLEAN DEFAULT FALSE;"))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.is_looped_back_to_validation IS 
                'Indicates if a rejected record (is_picked = false) has been looped back to ServiceOps validation phase. Prevents reprocessing.';
        """))
    
    if not check_column_exists(db, "send_clinicalops", "retry_count"):
        print("  Adding retry_count column...")
        db.execute(text("ALTER TABLE service_ops.send_clinicalops ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;"))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.retry_count IS 
                'Number of times this decision_tracking_id has been sent to ClinicalOps. Prevents infinite retry loops.';
        """))
    
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_send_clinicalops_rejected_unprocessed 
        ON service_ops.send_clinicalops(is_picked, is_looped_back_to_validation)
        WHERE is_picked = FALSE AND is_looped_back_to_validation = FALSE;
    """))
    
    db.commit()
    print("[OK] Migrations complete!")


def find_test_record(db: Session, packet_id: str = None, message_id: int = None):
    """Find a record to test with"""
    if message_id:
        record = db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.message_id == message_id,
            SendClinicalOpsDB.is_deleted == False
        ).first()
        if record:
            return record
        print(f"[ERROR] Message ID {message_id} not found")
        return None
    
    if packet_id:
        packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
        if not packet:
            print(f"[ERROR] Packet {packet_id} not found")
            return None
        
        record = db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.decision_tracking_id == str(packet.decision_tracking_id),
            SendClinicalOpsDB.is_deleted == False
        ).order_by(SendClinicalOpsDB.created_at.desc()).first()
        
        if record:
            return record
        print(f"[ERROR] No send_clinicalops record found for packet {packet_id}")
        return None
    
    # Find any recent record
    record = db.query(SendClinicalOpsDB).filter(
        SendClinicalOpsDB.is_deleted == False,
        SendClinicalOpsDB.payload['message_type'].astext == 'CASE_READY_FOR_REVIEW'
    ).order_by(SendClinicalOpsDB.created_at.desc()).first()
    
    if record:
        return record
    
    print("[ERROR] No suitable records found. Please provide --packet-id or --message-id")
    return None


def main():
    parser = argparse.ArgumentParser(description="Test ClinicalOps rejection workflow")
    parser.add_argument("--packet-id", type=str, help="Packet external_id (e.g., SVC-2026-000001)")
    parser.add_argument("--message-id", type=int, help="send_clinicalops message_id")
    parser.add_argument("--error-reason", type=str, default="Missing HCPCS code", 
                       help="Error reason for rejection")
    parser.add_argument("--skip-migrations", action="store_true",
                       help="Skip migration check (assume migrations are already run)")
    
    args = parser.parse_args()
    
    db: Session = SessionLocal()
    
    try:
        print("=" * 80)
        print("ClinicalOps Rejection Feedback Loop - Test Script")
        print("=" * 80)
        
        # Step 1: Run migrations if needed
        if not args.skip_migrations:
            run_migrations_if_needed(db)
        else:
            print("\n[Skipping migrations]")
        
        # Step 2: Find test record
        print("\nStep 1: Finding test record...")
        record = find_test_record(db, args.packet_id, args.message_id)
        
        if not record:
            print("\n[ERROR] No suitable record found. Exiting.")
            return
        
        print(f"[OK] Found record: message_id={record.message_id}")
        print(f"   Decision Tracking ID: {record.decision_tracking_id}")
        print(f"   Current is_picked: {record.is_picked}")
        print(f"   Current error_reason: {record.error_reason}")
        
        # Step 3: Show current packet status
        print("\nStep 2: Current packet status...")
        packet = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id == record.decision_tracking_id
        ).first()
        
        if not packet:
            print("[ERROR] Packet not found. Exiting.")
            return
        
        print(f"   Packet ID: {packet.external_id}")
        print(f"   Detailed Status: {packet.detailed_status}")
        print(f"   Validation Status: {packet.validation_status}")
        print(f"   Assigned To: {packet.assigned_to}")
        
        # Step 4: Simulate rejection
        print("\nStep 3: Simulating ClinicalOps rejection...")
        print(f"   Message ID: {record.message_id}")
        print(f"   Setting is_picked = false, error_reason = '{args.error_reason}'")
        
        record.is_picked = False
        record.error_reason = args.error_reason
        record.is_looped_back_to_validation = False  # Reset to allow processing
        
        db.commit()
        db.refresh(record)
        
        print(f"[OK] Marked as rejected")
        
        # Step 5: Process rejection
        print("\nStep 4: Processing rejection (looping back to validation)...")
        
        count_before = ClinicalOpsRejectionProcessor.get_rejected_records_count(db)
        print(f"   Rejected records pending: {count_before}")
        
        processed_count = ClinicalOpsRejectionProcessor.process_rejected_records(db, batch_size=10)
        
        count_after = ClinicalOpsRejectionProcessor.get_rejected_records_count(db)
        
        print(f"[OK] Processed {processed_count} records")
        print(f"   Remaining: {count_after}")
        
        # Refresh and show results
        db.refresh(record)
        db.refresh(packet)
        
        print(f"\nStep 5: Results...")
        print(f"   Record is_looped_back_to_validation: {record.is_looped_back_to_validation}")
        print(f"   Packet Status: {packet.detailed_status}")
        print(f"   Validation Status: {packet.validation_status}")
        
        # Show validation record
        validation = db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == packet.packet_id,
            PacketValidationDB.validation_type == "CLINICAL_OPS_REJECTION",
            PacketValidationDB.is_active == True
        ).order_by(PacketValidationDB.validated_at.desc()).first()
        
        if validation:
            print(f"\nStep 6: Validation record created:")
            print(f"   Validation Type: {validation.validation_type}")
            print(f"   Validation Status: {validation.validation_status}")
            print(f"   Is Passed: {validation.is_passed}")
            print(f"   Update Reason: {validation.update_reason}")
            print(f"   Validation Errors: {validation.validation_errors}")
            print("[OK] Validation record created successfully")
        else:
            print("[ERROR] No CLINICAL_OPS_REJECTION validation record found")
        
        print("\n" + "=" * 80)
        print("[OK] Test complete!")
        print("=" * 80)
        print("\nNext steps:")
        print("   1. Check UI - packet should appear in 'Intake Validation' queue")
        print(f"   2. Review error_reason: '{args.error_reason}' in validation record")
        print("   3. Either fix issue and approve, or dismiss the packet")
        print(f"\nPacket ID to check in UI: {packet.external_id}")
        
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
