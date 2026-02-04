"""
Test script for ClinicalOps rejection feedback loop
Simulates a ClinicalOps rejection and processes it through the feedback loop

Usage:
    python scripts/test_clinical_ops_rejection_workflow.py [--packet-id PACKET_ID] [--message-id MESSAGE_ID]
    
Options:
    --packet-id: Use specific packet (by external_id like SVC-2026-000001)
    --message-id: Use specific send_clinicalops message_id
    --process: Actually run the processor (default: just show what would happen)
"""
import os
import sys
import argparse
from datetime import datetime, timezone
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.orm import Session
from app.services.db import SessionLocal
from app.models.send_clinicalops_db import SendClinicalOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_validation_db import PacketValidationDB
from app.services.clinical_ops_rejection_processor import ClinicalOpsRejectionProcessor
from app.services.workflow_orchestrator import WorkflowOrchestratorService


def print_status(message: str, success: bool = True):
    """Print status message"""
    prefix = "[OK]" if success else "[ERROR]"
    print(f"{prefix} {message}")


def find_test_record(db: Session, packet_id: str = None, message_id: int = None):
    """Find a record to test with"""
    if message_id:
        record = db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.message_id == message_id,
            SendClinicalOpsDB.is_deleted == False
        ).first()
        if record:
            return record
        print_status(f"Message ID {message_id} not found", False)
        return None
    
    if packet_id:
        # Find by packet external_id
        packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
        if not packet:
            print_status(f"Packet {packet_id} not found", False)
            return None
        
        record = db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.decision_tracking_id == str(packet.decision_tracking_id),
            SendClinicalOpsDB.is_deleted == False
        ).order_by(SendClinicalOpsDB.created_at.desc()).first()
        
        if record:
            return record
        print_status(f"No send_clinicalops record found for packet {packet_id}", False)
        return None
    
    # Find any recent record
    record = db.query(SendClinicalOpsDB).filter(
        SendClinicalOpsDB.is_deleted == False,
        SendClinicalOpsDB.payload['message_type'].astext == 'CASE_READY_FOR_REVIEW'
    ).order_by(SendClinicalOpsDB.created_at.desc()).first()
    
    if record:
        return record
    
    print_status("No suitable records found. Please provide --packet-id or --message-id", False)
    return None


def simulate_rejection(db: Session, record: SendClinicalOpsDB, error_reason: str = "Missing HCPCS code"):
    """Simulate ClinicalOps rejecting the record"""
    print(f"\nSimulating ClinicalOps rejection...")
    print(f"   Message ID: {record.message_id}")
    print(f"   Decision Tracking ID: {record.decision_tracking_id}")
    print(f"   Current is_picked: {record.is_picked}")
    print(f"   Current error_reason: {record.error_reason}")
    
    # Mark as rejected
    record.is_picked = False
    record.error_reason = error_reason
    record.is_looped_back_to_validation = False  # Reset to allow processing
    
    db.commit()
    db.refresh(record)
    
    print_status(f"Marked as rejected: is_picked=false, error_reason='{error_reason}'")
    return record


def show_packet_status(db: Session, decision_tracking_id: str):
    """Show current packet status"""
    packet = db.query(PacketDB).filter(
        PacketDB.decision_tracking_id == decision_tracking_id
    ).first()
    
    if not packet:
        print_status("Packet not found", False)
        return None
    
    print(f"\nPacket Status:")
    print(f"   Packet ID: {packet.external_id}")
    print(f"   Detailed Status: {packet.detailed_status}")
    print(f"   Validation Status: {packet.validation_status}")
    print(f"   Assigned To: {packet.assigned_to}")
    
    # Get validation records
    validations = db.query(PacketValidationDB).filter(
        PacketValidationDB.packet_id == packet.packet_id,
        PacketValidationDB.is_active == True
    ).order_by(PacketValidationDB.validated_at.desc()).all()
    
    if validations:
        print(f"\n   Recent Validation Records:")
        for val in validations[:3]:  # Show last 3
            print(f"      - {val.validation_type}: {val.validation_status}")
            if val.validation_errors:
                print(f"        Errors: {val.validation_errors}")
    
    return packet


def main():
    parser = argparse.ArgumentParser(description="Test ClinicalOps rejection feedback loop")
    parser.add_argument("--packet-id", type=str, help="Packet external_id (e.g., SVC-2026-000001)")
    parser.add_argument("--message-id", type=int, help="send_clinicalops message_id")
    parser.add_argument("--error-reason", type=str, default="Missing HCPCS code", 
                       help="Error reason for rejection (default: 'Missing HCPCS code')")
    parser.add_argument("--process", action="store_true", 
                       help="Actually run the processor (default: dry-run)")
    parser.add_argument("--skip-rejection", action="store_true",
                       help="Skip creating rejection (assume record is already rejected)")
    
    args = parser.parse_args()
    
    db: Session = SessionLocal()
    
    try:
        print("=" * 80)
        print("ClinicalOps Rejection Feedback Loop - Test Script")
        print("=" * 80)
        
        # Step 1: Find a record to test
        print("\nStep 1: Finding test record...")
        record = find_test_record(db, args.packet_id, args.message_id)
        
        if not record:
            print("\n❌ No suitable record found. Exiting.")
            return
        
        print_status(f"Found record: message_id={record.message_id}")
        print(f"   Decision Tracking ID: {record.decision_tracking_id}")
        print(f"   Current is_picked: {record.is_picked}")
        print(f"   Current error_reason: {record.error_reason}")
        print(f"   Current is_looped_back: {record.is_looped_back_to_validation}")
        
        # Step 2: Show current packet status
        print("\nStep 2: Current packet status...")
        packet = show_packet_status(db, record.decision_tracking_id)
        
        if not packet:
            print("\n❌ Packet not found. Exiting.")
            return
        
        # Step 3: Simulate rejection (unless skipped)
        if not args.skip_rejection:
            print("\nStep 3: Simulating ClinicalOps rejection...")
            record = simulate_rejection(db, record, args.error_reason)
        else:
            print("\nStep 3: Skipping rejection (using existing rejected record)...")
            if record.is_picked is not False or not record.error_reason:
                print_status("Record is not rejected. Use --error-reason or remove --skip-rejection", False)
                return
        
        # Step 4: Process rejection
        if args.process:
            print("\nStep 4: Processing rejection (looping back to validation)...")
            
            # Get count before
            count_before = ClinicalOpsRejectionProcessor.get_rejected_records_count(db)
            print(f"   Rejected records pending: {count_before}")
            
            # Process
            processed_count = ClinicalOpsRejectionProcessor.process_rejected_records(db, batch_size=10)
            
            # Get count after
            count_after = ClinicalOpsRejectionProcessor.get_rejected_records_count(db)
            
            print_status(f"Processed {processed_count} records")
            print(f"   Remaining: {count_after}")
            
            # Refresh record
            db.refresh(record)
            print(f"\n   Record after processing:")
            print(f"      is_looped_back_to_validation: {record.is_looped_back_to_validation}")
            
            # Show updated packet status
            print("\nStep 5: Updated packet status...")
            db.refresh(packet)
            show_packet_status(db, record.decision_tracking_id)
            
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
                print_status("Validation record created successfully")
            else:
                print_status("No CLINICAL_OPS_REJECTION validation record found", False)
            
        else:
            print("\nStep 4: DRY RUN - Would process rejection...")
            print("   (Use --process to actually run the processor)")
            print(f"\n   Would:")
            print(f"   1. Find packet by decision_tracking_id={record.decision_tracking_id}")
            print(f"   2. Update packet status to 'Intake Validation'")
            print(f"   3. Update validation_status to 'Pending - Validation'")
            print(f"   4. Create validation record with error_reason='{record.error_reason}'")
            print(f"   5. Mark record.is_looped_back_to_validation = true")
        
        print("\n" + "=" * 80)
        print("Test complete!")
        print("=" * 80)
        
        if args.process:
            print("\nNext steps:")
            print("   1. Check UI - packet should appear in 'Intake Validation' queue")
            print("   2. Review error_reason in validation record")
            print("   3. Either fix issue and approve, or dismiss the packet")
        
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
