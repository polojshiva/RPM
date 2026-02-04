"""
Create a test packet with validation errors for UI testing
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


def create_test_packet_with_errors():
    """Create a test packet with validation errors"""
    db = SessionLocal()
    try:
        # Create extracted fields with validation errors and comprehensive OCR values
        extracted_fields = {
            'fields': {
                # Row 1
                'Request Type': {'value': 'I', 'confidence': 0.95, 'field_type': 'STRING', 'source': 'OCR'},
                'Submission Type': {'value': 'expedited-initial', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 2
                'Submitted Date': {'value': '2026-01-28', 'confidence': 0.98, 'field_type': 'DATE', 'source': 'OCR'},
                'Title': {'value': 'Genzeon Portal Prior Authorization Request', 'confidence': 0.88, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 3
                'Previous UTN': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                'State of Authorization': {'value': 'NJ', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 4
                'Anticipated Date of Service': {'value': '01/28/2026', 'confidence': 0.85, 'field_type': 'DATE', 'source': 'OCR'},  # Will be auto-fixed
                'Place of Service': {'value': '11', 'confidence': 0.93, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 5
                'Procedure Code set 1': {'value': '62321', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
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
                
                # Row 9
                'Units of Service set 3': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                'Diagnosis Codes': {'value': 'G40.011, M2551', 'confidence': 0.87, 'field_type': 'STRING', 'source': 'OCR'},  # Will be auto-fixed
                
                # Row 10
                'Facility Provider Name': {'value': 'GARDEN STATE MEDICAL CENTER', 'confidence': 0.91, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider NPI': {'value': '123456789', 'confidence': 0.89, 'field_type': 'STRING', 'source': 'OCR'},  # ERROR: Only 9 digits
                
                # Row 11
                'Facility Provider CCN': {'value': '261102', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider Address 1': {'value': '1100 ROUTE 70 WEST', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 12
                'Facility Provider Address 2': {'value': '', 'confidence': 0.0, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider City': {'value': 'WHITING', 'confidence': 0.88, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 13
                'Rendering/Facility State': {'value': 'NY', 'confidence': 0.86, 'field_type': 'STRING', 'source': 'OCR'},  # ERROR: Should be NJ
                'Facility Provider Zip': {'value': '08759', 'confidence': 0.95, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 14
                'Beneficiary Last Name': {'value': 'RYAN', 'confidence': 0.97, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary First Name': {'value': 'DENISE', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 15
                'Beneficiary Medicare ID': {'value': '7XW9WR9QD20', 'confidence': 0.93, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary DOB': {'value': '1951-05-06', 'confidence': 0.94, 'field_type': 'DATE', 'source': 'OCR'},
                
                # Row 16
                'Attending Physician Name': {'value': 'SAMIR JANI', 'confidence': 0.91, 'field_type': 'STRING', 'source': 'OCR'},
                'Attending Physician NPI': {'value': '1184912826', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 17
                'Attending Physician PTAN': {'value': '261102', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                'Attending Physician Address': {'value': '1100 ROUTE 70 WEST', 'confidence': 0.88, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 18
                'Attending Physician City': {'value': 'WHITING', 'confidence': 0.87, 'field_type': 'STRING', 'source': 'OCR'},
                'Attending Physician State': {'value': 'NJ', 'confidence': 0.95, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 19
                'Attending Physician Zip': {'value': '08759', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
                'Requester Name': {'value': 'Susan E', 'confidence': 0.89, 'field_type': 'STRING', 'source': 'OCR'},
                
                # Row 20
                'Requester Email Id': {'value': 'precert@gsmedicalcenter.org', 'confidence': 0.93, 'field_type': 'STRING', 'source': 'OCR'},
                'Requester Phone': {'value': '(732) 849-0077', 'confidence': 0.91, 'field_type': 'STRING', 'source': 'OCR'},  # Will be auto-fixed
                
                # Row 21
                'Requester Fax': {'value': '732-849-0015', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},  # Will be auto-fixed
            }
        }
        
        print("=" * 80)
        print("Creating test packet with validation errors...")
        print("=" * 80)
        
        # Step 1: Apply auto-fix
        print("\n1. Applying auto-fix...")
        fixed_fields, auto_fix_results = apply_auto_fix_to_fields(extracted_fields)
        print(f"   Auto-fixed {len(auto_fix_results)} fields:")
        for field, changes in auto_fix_results.items():
            old_val = changes.get('original', 'N/A')
            new_val = changes.get('fixed', 'N/A')
            status = changes.get('status', 'N/A')
            print(f"     - {field}: '{old_val}' -> '{new_val}' ({status})")
        
        # Step 2: Create packet
        print("\n2. Creating packet...")
        decision_tracking_id = str(uuid4())
        packet_id = f"TEST-ERRORS-{int(datetime.now().timestamp())}"
        
        packet = PacketDB(
            external_id=packet_id,
            decision_tracking_id=decision_tracking_id,
            beneficiary_name="John Test Patient",
            beneficiary_mbi="1AB2CD3EF45",
            provider_name="Test Medical Center",
            provider_npi="1234567890",
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
        db.commit()
        print("   Packet table synced")
        
        # Step 5: Run validation
        print("\n5. Running validation...")
        validation_result = validate_all_fields(fixed_fields, packet, db)
        print(f"   Validation errors found: {validation_result['has_errors']}")
        if validation_result['has_errors']:
            print("   Errors:")
            for field, errors in validation_result.get('field_errors', {}).items():
                print(f"     - {field}: {', '.join(errors)}")
        
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
        print("\nErrors to fix:")
        print("  1. State: Change 'NY' to 'NJ'")
        print("  2. NPI: Change '123456789' to '1234567890' (add leading zero)")
        print("\nTo test:")
        print(f"  1. Go to UI and search for: {packet_id}")
        print("  2. You should see a red warning icon next to the packet ID")
        print("  3. Click 'View' to see the document")
        print("  4. Fix the errors in the fields")
        print("  5. Save and verify the warning icon disappears")
        
        return packet_id, packet.packet_id, document.external_id
        
    except Exception as e:
        db.rollback()
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_test_packet_with_errors()
