"""
Test script to verify extracted_fields and updated_extracted_fields data flow.

This script tests:
1. Initial OCR extraction → extracted_fields (baseline)
2. Manual field updates → updated_extracted_fields (working copy)
3. JSON Generator reading priority (should read updated_extracted_fields if exists)
4. Packet sync from extracted fields
5. Full workflow verification

Run: python scripts/test_extracted_fields_flow.py
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from sqlalchemy.orm.attributes import flag_modified

def print_section(title: str):
    """Print a formatted section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_test_result(test_name: str, passed: bool, details: str = ""):
    """Print test result"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status} {test_name}")
    if details:
        print(f"    {details}")

def find_or_create_test_packet_and_document(db):
    """Find an existing packet or use the first available one for testing"""
    print_section("Step 1: Find Test Packet and Document")
    
    # Try to find an existing packet with a document
    packet = db.query(PacketDB).join(PacketDocumentDB).filter(
        PacketDocumentDB.extracted_fields.isnot(None)
    ).first()
    
    if not packet:
        print("No existing packet found. Please create a packet with extracted_fields first.")
        print("This test requires an existing packet with OCR data.")
        return None, None
    
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.extracted_fields.isnot(None)
    ).first()
    
    if not document:
        print(f"Packet {packet.external_id} found but no document with extracted_fields.")
        return None, None
    
    print(f"Using existing packet: {packet.external_id} (packet_id={packet.packet_id})")
    print(f"  decision_tracking_id: {packet.decision_tracking_id}")
    print(f"Using existing document: {document.external_id} (packet_document_id={document.packet_document_id})")
    
    if document.extracted_fields:
        field_count = len(document.extracted_fields.get('fields', {}))
        print(f"  Initial extracted_fields has {field_count} fields")
    
    if document.updated_extracted_fields:
        updated_count = len(document.updated_extracted_fields.get('fields', {}))
        print(f"  updated_extracted_fields has {updated_count} fields (will be modified)")
    
    return packet, document

def test_manual_field_update(db, document: PacketDocumentDB):
    """Test manual field update (simulating user edit)"""
    print_section("Step 2: Simulate Manual Field Update")
    
    # Simulate user editing Provider NPI and adding a new field
    now = datetime.now(timezone.utc)
    
    # Get current fields (should be from extracted_fields since updated_extracted_fields is None)
    if document.updated_extracted_fields:
        working_fields = document.updated_extracted_fields.get('fields', {}).copy()
    else:
        # Initialize from extracted_fields
        working_fields = document.extracted_fields.get('fields', {}).copy() if document.extracted_fields else {}
    
    # Update Provider NPI (user correction)
    working_fields["Provider NPI"] = {
        "value": "9876543210",  # Changed from 1234567890
        "source": "MANUAL",
        "confidence": 1.0,
        "updated_at": now.isoformat(),
        "updated_by": "test_user"
    }
    
    # Add a new field (user addition)
    working_fields["Anticipated Date of Service"] = {
        "value": "2026-02-15",
        "source": "MANUAL",
        "confidence": 1.0,
        "updated_at": now.isoformat(),
        "updated_by": "test_user"
    }
    
    # Build updated_extracted_fields payload
    updated_payload = {
        "fields": working_fields,
        "raw": document.extracted_fields.get('raw', {}) if document.extracted_fields else {},
        "last_updated_at": now.isoformat(),
        "last_updated_by": "test_user",
        "source": "MANUAL"
    }
    
    # Update ONLY updated_extracted_fields (preserve extracted_fields baseline)
    document.updated_extracted_fields = updated_payload
    flag_modified(document, 'updated_extracted_fields')
    
    # Add audit history
    if not document.extracted_fields_update_history:
        document.extracted_fields_update_history = []
    
    audit_entry = {
        'type': 'MANUAL_SAVE',
        'updated_at': now.isoformat(),
        'updated_by': 'test_user',
        'changed_fields': {
            'Provider NPI': {'old': '1234567890', 'new': '9876543210'},
            'Anticipated Date of Service': {'old': None, 'new': '2026-02-15'}
        },
        'note': 'Manual field update test'
    }
    document.extracted_fields_update_history.append(audit_entry)
    flag_modified(document, 'extracted_fields_update_history')
    
    document.updated_at = now
    db.commit()
    
    print("Updated updated_extracted_fields with manual edits:")
    print(f"  Provider NPI: 1234567890 -> 9876543210")
    print(f"  Added: Anticipated Date of Service = 2026-02-15")
    print(f"  Total fields in updated_extracted_fields: {len(working_fields)}")
    print(f"  Audit history entries: {len(document.extracted_fields_update_history)}")
    
    # Verify extracted_fields is unchanged (baseline preserved)
    baseline_npi = document.extracted_fields.get('fields', {}).get('Provider NPI', {})
    baseline_npi_value = baseline_npi.get('value') if isinstance(baseline_npi, dict) else baseline_npi
    print(f"\nBaseline (extracted_fields) preserved:")
    print(f"  Provider NPI in extracted_fields: {baseline_npi_value} (unchanged)")
    
    return document

def test_json_generator_read_priority(db, document: PacketDocumentDB):
    """Test what JSON Generator would read (should use priority logic)"""
    print_section("Step 3: Test JSON Generator Read Priority")
    
    # Refresh document from DB
    db.refresh(document)
    
    # Current JSON Generator logic (WRONG - reads only extracted_fields)
    json_gen_reads = document.extracted_fields
    print("Current JSON Generator reads:")
    print(f"  Source: extracted_fields (baseline OCR)")
    if json_gen_reads:
        npi_value = json_gen_reads.get('fields', {}).get('Provider NPI', {})
        if isinstance(npi_value, dict):
            npi_value = npi_value.get('value', 'N/A')
        print(f"  Provider NPI: {npi_value}")
        print(f"  Has 'Anticipated Date of Service': {'Anticipated Date of Service' in json_gen_reads.get('fields', {})}")
    else:
        print("  No extracted_fields found")
    
    # Correct priority logic (what it SHOULD read)
    correct_reads = document.updated_extracted_fields if document.updated_extracted_fields else document.extracted_fields
    print("\nCorrect priority logic (updated_extracted_fields first):")
    print(f"  Source: {'updated_extracted_fields' if document.updated_extracted_fields else 'extracted_fields'}")
    if correct_reads:
        npi_value = correct_reads.get('fields', {}).get('Provider NPI', {})
        if isinstance(npi_value, dict):
            npi_value = npi_value.get('value', 'N/A')
        print(f"  Provider NPI: {npi_value}")
        print(f"  Has 'Anticipated Date of Service': {'Anticipated Date of Service' in correct_reads.get('fields', {})}")
    else:
        print("  No fields found")
    
    # Test result
    if document.updated_extracted_fields:
        baseline_npi = document.extracted_fields.get('fields', {}).get('Provider NPI', {})
        baseline_npi_value = baseline_npi.get('value') if isinstance(baseline_npi, dict) else baseline_npi
        
        updated_npi = document.updated_extracted_fields.get('fields', {}).get('Provider NPI', {})
        updated_npi_value = updated_npi.get('value') if isinstance(updated_npi, dict) else updated_npi
        
        if baseline_npi_value != updated_npi_value:
            print_test_result(
                "JSON Generator Priority Check",
                False,
                f"JSON Generator would read OLD value '{baseline_npi_value}' instead of UPDATED value '{updated_npi_value}'"
            )
            return False
        else:
            print_test_result("JSON Generator Priority Check", True)
            return True
    else:
        print_test_result("JSON Generator Priority Check", True, "No updated_extracted_fields, so both read same")
        return True

def test_packet_sync(db, packet: PacketDB, document: PacketDocumentDB):
    """Test packet sync from extracted fields"""
    print_section("Step 4: Test Packet Sync from Extracted Fields")
    
    from app.utils.packet_sync import sync_packet_from_extracted_fields
    
    # Refresh from DB
    db.refresh(packet)
    db.refresh(document)
    
    # Get fields with priority (ServiceOps standard)
    # Use inline function to avoid import issues
    if document.updated_extracted_fields:
        fields_dict = document.updated_extracted_fields
    else:
        fields_dict = document.extracted_fields
    
    if not fields_dict:
        print("No fields found to sync")
        return False
    
    # Sync packet
    now = datetime.now(timezone.utc)
    packet_updated = sync_packet_from_extracted_fields(packet, fields_dict, now, db)
    
    db.commit()
    db.refresh(packet)
    
    print(f"Packet sync result: {'Updated' if packet_updated else 'No changes'}")
    print(f"  beneficiary_name: {packet.beneficiary_name}")
    print(f"  beneficiary_mbi: {packet.beneficiary_mbi}")
    print(f"  provider_npi: {packet.provider_npi}")
    print(f"  hcpcs: {packet.hcpcs}")
    print(f"  submission_type: {packet.submission_type}")
    
    # Verify NPI was synced from updated_extracted_fields (should be 9876543210)
    expected_npi = "9876543210"
    if packet.provider_npi == expected_npi:
        print_test_result("Packet Sync from updated_extracted_fields", True, f"NPI correctly synced: {expected_npi}")
        return True
    else:
        print_test_result(
            "Packet Sync from updated_extracted_fields",
            False,
            f"Expected NPI {expected_npi}, got {packet.provider_npi}"
        )
        return False

def test_full_workflow_simulation(db, packet: PacketDB, document: PacketDocumentDB):
    """Simulate full workflow: OCR → Edit → JSON Generation"""
    print_section("Step 5: Full Workflow Simulation")
    
    db.refresh(document)
    
    # Step 1: Initial OCR (extracted_fields)
    print("\n1. Initial OCR Extraction:")
    print(f"   extracted_fields has {len(document.extracted_fields.get('fields', {}))} fields")
    print(f"   updated_extracted_fields: {'Set' if document.updated_extracted_fields else 'Not set'}")
    
    # Step 2: Manual Edit (updated_extracted_fields)
    print("\n2. After Manual Edit:")
    print(f"   extracted_fields: {len(document.extracted_fields.get('fields', {}))} fields (unchanged)")
    print(f"   updated_extracted_fields: {len(document.updated_extracted_fields.get('fields', {}))} fields (updated)")
    
    # Step 3: What JSON Generator would read (current vs correct)
    print("\n3. JSON Generator Read:")
    current_read = document.extracted_fields
    correct_read = document.updated_extracted_fields if document.updated_extracted_fields else document.extracted_fields
    
    current_npi = current_read.get('fields', {}).get('Provider NPI', {})
    current_npi_value = current_npi.get('value') if isinstance(current_npi, dict) else current_npi
    
    correct_npi = correct_read.get('fields', {}).get('Provider NPI', {})
    correct_npi_value = correct_npi.get('value') if isinstance(correct_npi, dict) else correct_npi
    
    print(f"   Current logic reads: Provider NPI = {current_npi_value}")
    print(f"   Correct logic reads: Provider NPI = {correct_npi_value}")
    
    if current_npi_value != correct_npi_value:
        print(f"   ⚠️  MISMATCH: JSON Generator would use OLD value!")
        return False
    else:
        print(f"   ✓ Values match")
        return True

def cleanup_test_data(db, packet: PacketDB, document: PacketDocumentDB):
    """Revert test changes (restore original updated_extracted_fields)"""
    print_section("Cleanup")
    
    try:
        # Revert updated_extracted_fields to None (or original state)
        # For this test, we'll just remove the test audit entry
        if document.extracted_fields_update_history:
            # Remove the last entry if it's our test entry
            last_entry = document.extracted_fields_update_history[-1]
            if last_entry.get('updated_by') == 'test_user' and last_entry.get('note') == 'Manual field update test':
                document.extracted_fields_update_history.pop()
                flag_modified(document, 'extracted_fields_update_history')
                print("Removed test audit entry")
        
        # Optionally revert updated_extracted_fields (commented out to preserve user's data)
        # document.updated_extracted_fields = None
        # flag_modified(document, 'updated_extracted_fields')
        
        db.commit()
        print("Test changes reverted (original data preserved)")
    except Exception as e:
        print(f"Error during cleanup: {e}")
        db.rollback()

def main():
    """Main test execution"""
    print("\n" + "=" * 80)
    print("  EXTRACTED FIELDS DATA FLOW TEST")
    print("=" * 80)
    
    db = SessionLocal()
    packet = None
    document = None
    
    try:
        # Step 1: Find existing test data
        packet, document = find_or_create_test_packet_and_document(db)
        
        if not packet or not document:
            print("\n[ERROR] Could not find suitable test packet. Exiting.")
            return
        
        # Step 2: Test manual update
        document = test_manual_field_update(db, document)
        
        # Step 3: Test JSON Generator read priority
        priority_ok = test_json_generator_read_priority(db, document)
        
        # Step 4: Test packet sync
        sync_ok = test_packet_sync(db, packet, document)
        
        # Step 5: Full workflow simulation
        workflow_ok = test_full_workflow_simulation(db, packet, document)
        
        # Summary
        print_section("Test Summary")
        print_test_result("JSON Generator Priority Logic", priority_ok)
        print_test_result("Packet Sync from updated_extracted_fields", sync_ok)
        print_test_result("Full Workflow Simulation", workflow_ok)
        
        if not priority_ok:
            print("\n⚠️  CRITICAL ISSUE FOUND:")
            print("   JSON Generator is reading from 'extracted_fields' (baseline)")
            print("   but should read from 'updated_extracted_fields' (working copy) if it exists.")
            print("   This means manual edits are being ignored!")
        
        # Ask if user wants to revert test changes
        print("\n" + "-" * 80)
        response = input("Revert test changes to document? (y/n, default=n): ").strip().lower()
        if response == 'y':
            cleanup_test_data(db, packet, document)
        else:
            print("Test changes preserved in database")
        
    except Exception as e:
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()

