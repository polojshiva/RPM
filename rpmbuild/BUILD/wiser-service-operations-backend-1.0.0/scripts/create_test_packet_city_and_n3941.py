#!/usr/bin/env python3
"""
Create a test packet to verify:
1. City validation fix (word boundaries) - cities like "Manalapan" (contains "PA"), 
   "Parsippany" (contains "NY"), "Camden" (contains "CA") should NOT trigger errors
2. N3941 diagnosis code fix - N3941 with procedure code 64561 should be accepted
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.services.field_auto_fix import apply_auto_fix_to_fields
from app.services.field_validation_service import validate_all_fields
from app.services.validation_persistence import save_field_validation_errors, update_packet_validation_flag
from app.utils.packet_sync import sync_packet_from_extracted_fields
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_packet_city_and_n3941():
    """Create a test packet with cities containing state abbreviations and N3941 diagnosis code"""
    db = SessionLocal()
    try:
        # Create extracted fields with:
        # 1. Cities that contain state abbreviations as substrings (should NOT trigger errors)
        # 2. Procedure code 64561 with diagnosis code N3941 (should be accepted)
        extracted_fields = {
            'fields': {
                # Row 1
                'Request Type': {'value': 'I', 'confidence': 0.95, 'field_type': 'STRING', 'source': 'OCR'},
                'Submission Type': {'value': 'expedited-initial', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 2
                'Submitted Date': {'value': '2026-01-29', 'confidence': 0.98, 'field_type': 'DATE', 'source': 'OCR'},
                'Title': {'value': 'Test Packet for City and N3941 Validation', 'confidence': 0.88, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 3
                'Previous UTN': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                'State of Authorization': {'value': 'NJ', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 4
                'Anticipated Date of Service': {'value': '2026-02-20', 'confidence': 0.85, 'field_type': 'DATE', 'source': 'OCR'},
                'Place of Service': {'value': '11', 'confidence': 0.93, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 5 - TEST: Procedure code 64561 with N3941 diagnosis code
                'Procedure Code set 1': {'value': '64561', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},  # Vagus Nerve Stimulation
                'Modifier set 1': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 6
                'Units of Service set 1': {'value': '1', 'confidence': 0.94, 'field_type': 'STRING', 'source': 'OCR'},
                'Procedure Code set 2': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 7
                'Modifier set 2': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                'Units of Service set 2': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 8
                'Procedure Code set 3': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                'Modifier set 3': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 9 - TEST: N3941 diagnosis code (should be accepted for 64561)
                'Units of Service set 3': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                'Diagnosis Codes': {'value': 'N3941', 'confidence': 0.87, 'field_type': 'STRING', 'source': 'OCR'},  # Should be accepted
                
                # Row 10
                'Facility Provider Name': {'value': 'TEST MEDICAL CENTER', 'confidence': 0.91, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider NPI': {'value': '1578807517', 'confidence': 0.89, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 11
                'Facility Provider CCN': {'value': '261102', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider Address 1': {'value': '123 Main Street', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 12
                'Facility Provider Address 2': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                # TEST: City with "PA" inside (Manalapan) - should NOT trigger error
                'Facility Provider City': {'value': 'Manalapan', 'confidence': 0.88, 'field_type': 'STRING', 'source': 'OCR'},  # Contains "PA" but should be OK
                
                # Row 13
                'Rendering/Facility State': {'value': 'NJ', 'confidence': 0.86, 'field_type': 'STRING', 'source': 'OCR'},  # Correct state
                'Facility Provider Zip': {'value': '07726', 'confidence': 0.95, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 14
                'Beneficiary Last Name': {'value': 'TEST', 'confidence': 0.97, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary First Name': {'value': 'PATIENT', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 15
                'Beneficiary Medicare ID': {'value': '7XW9WR9QD20', 'confidence': 0.93, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary DOB': {'value': '1951-05-06', 'confidence': 0.94, 'field_type': 'DATE', 'source': 'OCR'},
                
                # Row 16
                'Attending Physician Name': {'value': 'TEST DOCTOR', 'confidence': 0.91, 'field_type': 'STRING', 'source': 'OCR'},
                'Attending Physician NPI': {'value': '1184912826', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 17
                'Attending Physician PTAN': {'value': '261102', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                # TEST: City with "NY" inside (Parsippany) - should NOT trigger error
                'Attending Physician Address': {'value': '456 Oak Avenue', 'confidence': 0.88, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 18
                # TEST: City with "NY" inside (Parsippany) - should NOT trigger error
                'Attending Physician City': {'value': 'Parsippany', 'confidence': 0.87, 'field_type': 'STRING', 'source': 'OCR'},  # Contains "NY" but should be OK
                'Attending Physician State': {'value': 'NJ', 'confidence': 0.89, 'field_type': 'STRING', 'source': 'OCR'},  # Correct state
                
                # Row 19
                'Attending Physician Zip': {'value': '07054', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                'Requester Name': {'value': 'Test Requester', 'confidence': 0.85, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 20
                'Requester Email Id': {'value': 'test@example.com', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                'Requester Phone': {'value': '7328490077', 'confidence': 0.88, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 21
                'Requester Fax': {'value': '7328490015', 'confidence': 0.87, 'field_type': 'STRING', 'source': 'OCR'},
            },
            'raw': {},
            'source': 'OCR',
            'last_updated_at': datetime.now(timezone.utc).isoformat(),
            'last_updated_by': 'test_script'
        }
        
        print("=" * 80)
        print("Creating test packet for City and N3941 validation testing")
        print("=" * 80)
        
        # Step 1: Apply auto-fix
        print("\n1. Applying auto-fix...")
        fixed_fields, auto_fix_results = apply_auto_fix_to_fields(extracted_fields)
        print(f"   Auto-fix applied: {len(auto_fix_results)} field(s) fixed")
        
        # Step 2: Create packet
        print("\n2. Creating packet...")
        decision_tracking_id = str(uuid4())
        packet_id = f"TEST-CITY-N3941-{int(datetime.now().timestamp())}"
        
        packet = PacketDB(
            external_id=packet_id,
            decision_tracking_id=decision_tracking_id,
            beneficiary_name="Test Patient",
            beneficiary_mbi="1AB2CD3EF45",
            provider_name="Test Medical Center",
            provider_npi="1578807517",
            service_type="DME - Test Service",
            detailed_status="Pending - New",
            validation_status="Pending - Validation",
            received_date=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc) + timedelta(days=3),
            page_count=1,
            completeness=0,
            has_field_validation_errors=False
        )
        db.add(packet)
        db.flush()
        print(f"   Created packet: {packet_id}")
        print(f"   Packet ID: {packet.packet_id}")
        
        # Step 3: Create document
        print("\n3. Creating document...")
        document = PacketDocumentDB(
            external_id=f"DOC-{packet_id}",
            packet_id=packet.packet_id,
            file_name="test_document.pdf",
            document_unique_identifier=f"test-doc-{uuid4()}",
            page_count=1,
            extracted_fields=fixed_fields,
            updated_extracted_fields=fixed_fields.copy(),
            part_type="PART_B",
            ocr_status="DONE",
            split_status="DONE",
            document_type_id=1,
            uploaded_at=datetime.now(timezone.utc)
        )
        db.add(document)
        db.flush()
        print(f"   Created document: {document.external_id}")
        
        # Step 4: Sync to packet table
        print("\n4. Syncing to packet table...")
        sync_packet_from_extracted_fields(packet, fixed_fields, datetime.now(timezone.utc), db)
        db.flush()
        print("   Packet table synced")
        
        # Step 5: Run validation
        print("\n5. Running validation...")
        validation_result = validate_all_fields(fixed_fields, packet, db)
        print(f"   Validation has_errors: {validation_result['has_errors']}")
        
        if validation_result['has_errors']:
            print("   Validation errors found:")
            for field, errors in validation_result.get('field_errors', {}).items():
                print(f"     - {field}: {', '.join(errors)}")
        else:
            print("   [OK] No validation errors (expected for this test packet)")
        
        # Step 6: Save validation
        print("\n6. Saving validation results...")
        save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        
        db.refresh(packet)
        print(f"   Validation flag set: {packet.has_field_validation_errors}")
        
        print("\n" + "=" * 80)
        print("Test packet created successfully!")
        print("=" * 80)
        print(f"\nPacket ID: {packet_id}")
        print(f"Packet DB ID: {packet.packet_id}")
        print(f"Document ID: {document.external_id}")
        print(f"Has Validation Errors: {packet.has_field_validation_errors}")
        
        print("\n=== TEST SCENARIOS ===")
        print("1. City 'Manalapan' contains 'PA' - should NOT trigger error (word boundary fix)")
        print("2. City 'Parsippany' contains 'NY' - should NOT trigger error (word boundary fix)")
        print("3. Diagnosis code 'N3941' with procedure '64561' - should be ACCEPTED (N3941 fix)")
        
        print("\n=== EXPECTED RESULTS ===")
        if packet.has_field_validation_errors:
            print("[WARN] Packet has validation errors - check if fixes are working correctly")
        else:
            print("[OK] Packet has no validation errors - fixes are working correctly!")
        
        print("\n=== TO TEST IN UI ===")
        print(f"1. Go to UI and search for: {packet_id}")
        print("2. Open the document view")
        print("3. Check that:")
        print("   - City 'Manalapan' does NOT show a validation error")
        print("   - City 'Parsippany' does NOT show a validation error")
        print("   - Diagnosis code 'N3941' does NOT show a validation error")
        print("4. Try editing the diagnosis code field and saving - it should save without errors")
        
        return packet_id, packet.packet_id, document.external_id
        
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_test_packet_city_and_n3941()
