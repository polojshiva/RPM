"""
Create test packets with UTN failures for UI testing

Creates:
1. Packet with ONLY UTN failure (no validation errors)
2. Packet with BOTH UTN failure AND validation errors
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
from app.models.packet_decision_db import PacketDecisionDB
from app.services.field_auto_fix import apply_auto_fix_to_fields
from app.services.field_validation_service import validate_all_fields
from app.services.validation_persistence import save_field_validation_errors, update_packet_validation_flag
from app.utils.packet_sync import sync_packet_from_extracted_fields
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_packet_with_utn_failure_only():
    """Create a packet with ONLY UTN failure (no validation errors)"""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("Creating packet with ONLY UTN failure (no validation errors)")
        print("=" * 80)
        
        # Create extracted fields with NO validation errors
        extracted_fields = {
            'fields': {
                'Request Type': {'value': 'I', 'confidence': 0.95, 'field_type': 'STRING', 'source': 'OCR'},
                'Submission Type': {'value': 'standard-initial', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                'Submitted Date': {'value': '2026-01-28', 'confidence': 0.98, 'field_type': 'DATE', 'source': 'OCR'},
                'State of Authorization': {'value': 'NJ', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                'Procedure Code set 1': {'value': '62321', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider Name': {'value': 'GARDEN STATE MEDICAL CENTER', 'confidence': 0.91, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider NPI': {'value': '1234567890', 'confidence': 0.89, 'field_type': 'STRING', 'source': 'OCR'},  # Valid 10 digits
                'Rendering/Facility State': {'value': 'NJ', 'confidence': 0.86, 'field_type': 'STRING', 'source': 'OCR'},  # Valid state
                'Beneficiary Last Name': {'value': 'SMITH', 'confidence': 0.97, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary First Name': {'value': 'JOHN', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary Medicare ID': {'value': '7XW9WR9QD20', 'confidence': 0.93, 'field_type': 'STRING', 'source': 'OCR'},
            }
        }
        
        # Apply auto-fix
        print("\n1. Applying auto-fix...")
        fixed_fields, _ = apply_auto_fix_to_fields(extracted_fields)
        
        # Create packet
        print("\n2. Creating packet...")
        decision_tracking_id = str(uuid4())
        packet_id = f"TEST-UTN-FAILURE-ONLY-{int(datetime.now().timestamp())}"
        
        # Extract beneficiary name from fields for required field
        beneficiary_first = fixed_fields.get('fields', {}).get('Beneficiary First Name', {}).get('value', 'JOHN')
        beneficiary_last = fixed_fields.get('fields', {}).get('Beneficiary Last Name', {}).get('value', 'SMITH')
        beneficiary_name = f"{beneficiary_first} {beneficiary_last}"
        beneficiary_mbi = fixed_fields.get('fields', {}).get('Beneficiary Medicare ID', {}).get('value', '7XW9WR9QD20')
        provider_name = fixed_fields.get('fields', {}).get('Facility Provider Name', {}).get('value', 'GARDEN STATE MEDICAL CENTER')
        provider_npi = fixed_fields.get('fields', {}).get('Facility Provider NPI', {}).get('value', '1234567890')
        submission_type = fixed_fields.get('fields', {}).get('Submission Type', {}).get('value', 'standard-initial')
        
        # Calculate due_date: 48 hours for expedited, 72 hours for standard
        received_date = datetime.now(timezone.utc) - timedelta(days=2)
        if 'expedited' in submission_type.lower():
            due_date = received_date + timedelta(hours=48)
        else:
            due_date = received_date + timedelta(hours=72)
        
        packet = PacketDB(
            external_id=packet_id,
            decision_tracking_id=decision_tracking_id,
            channel_type_id=1,  # Fax
            detailed_status="Pending - Clinical Review",
            received_date=received_date,
            due_date=due_date,
            beneficiary_name=beneficiary_name,
            beneficiary_mbi=beneficiary_mbi,
            provider_name=provider_name,
            provider_npi=provider_npi,
            service_type="Prior Authorization",  # Required field
            submission_type=submission_type,
            has_field_validation_errors=False,  # No validation errors
            created_at=datetime.now(timezone.utc)
        )
        db.add(packet)
        db.flush()
        
        # Create document
        print("\n3. Creating document...")
        document = PacketDocumentDB(
            packet_id=packet.packet_id,
            external_id=f"DOC-{packet_id}",
            file_name=f"{packet_id}.pdf",  # Required field
            document_unique_identifier=f"TEST-{packet_id}-{int(datetime.now().timestamp())}",  # Required field
            document_type_id=1,  # Required field - default document type
            extracted_fields=fixed_fields,
            updated_extracted_fields=fixed_fields,
            part_type="PART_B",
            created_at=datetime.now(timezone.utc)
        )
        db.add(document)
        db.flush()
        
        # Sync packet from extracted fields (updates other fields)
        print("\n4. Syncing packet from extracted fields...")
        sync_packet_from_extracted_fields(packet, fixed_fields, datetime.now(timezone.utc), db)
        db.commit()
        
        # Run validation (should pass - no errors)
        print("\n5. Running validation...")
        validation_result = validate_all_fields(fixed_fields, packet, db)
        save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        
        db.refresh(packet)
        print(f"   Validation errors: {packet.has_field_validation_errors} (should be False)")
        
        # Create packet_decision with UTN failure
        print("\n6. Creating packet_decision with UTN failure...")
        utn_fail_payload = {
            'error_code': 'UNABLE_TO_CREATE_UTN',
            'error_description': 'Unable to create UTN - provider enrollment issue',
            'action_required': 'Review error details and resubmit or contact MAC enrollment department',
            'part_type': 'B',
            'esmd_transaction_id': f'ESMD-{int(datetime.now().timestamp())}',
            'unique_id': packet_id,
        }
        
        packet_decision = PacketDecisionDB(
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            decision_type='APPROVE',
            operational_decision='DECISION_COMPLETE',
            clinical_decision='AFFIRM',
            decision_outcome='AFFIRM',
            part_type='B',
            decision_subtype='DIRECT_PA',
            utn_status='FAILED',
            utn_received_at=datetime.now(timezone.utc),
            utn_fail_payload=utn_fail_payload,
            utn_action_required=utn_fail_payload['action_required'],
            requires_utn_fix=True,
            is_active=True,
            created_by='SYSTEM',
            created_at=datetime.now(timezone.utc)
        )
        db.add(packet_decision)
        db.commit()
        
        print("\n" + "=" * 80)
        print("Packet with UTN failure only created successfully!")
        print("=" * 80)
        print(f"\nPacket ID: {packet_id}")
        print(f"Packet DB ID: {packet.packet_id}")
        print(f"Decision Tracking ID: {decision_tracking_id}")
        print(f"Has Validation Errors: {packet.has_field_validation_errors} (should be False)")
        print(f"UTN Status: {packet_decision.utn_status}")
        print(f"Requires UTN Fix: {packet_decision.requires_utn_fix}")
        print(f"Error Code: {utn_fail_payload['error_code']}")
        
        return packet_id, packet.packet_id, decision_tracking_id
        
    except Exception as e:
        db.rollback()
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


def create_packet_with_both_utn_failure_and_validation():
    """Create a packet with BOTH UTN failure AND validation errors"""
    db = SessionLocal()
    try:
        print("\n\n" + "=" * 80)
        print("Creating packet with BOTH UTN failure AND validation errors")
        print("=" * 80)
        
        # Create extracted fields WITH validation errors
        extracted_fields = {
            'fields': {
                'Request Type': {'value': 'I', 'confidence': 0.95, 'field_type': 'STRING', 'source': 'OCR'},
                'Submission Type': {'value': 'expedited-initial', 'confidence': 0.92, 'field_type': 'STRING', 'source': 'OCR'},
                'Submitted Date': {'value': '2026-01-28', 'confidence': 0.98, 'field_type': 'DATE', 'source': 'OCR'},
                'State of Authorization': {'value': 'NJ', 'confidence': 0.90, 'field_type': 'STRING', 'source': 'OCR'},
                'Procedure Code set 1': {'value': '62321', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider Name': {'value': 'GARDEN STATE MEDICAL CENTER', 'confidence': 0.91, 'field_type': 'STRING', 'source': 'OCR'},
                'Facility Provider NPI': {'value': '123456789', 'confidence': 0.89, 'field_type': 'STRING', 'source': 'OCR'},  # ERROR: Only 9 digits
                'Rendering/Facility State': {'value': 'NY', 'confidence': 0.86, 'field_type': 'STRING', 'source': 'OCR'},  # ERROR: Should be NJ
                'Beneficiary Last Name': {'value': 'JONES', 'confidence': 0.97, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary First Name': {'value': 'MARY', 'confidence': 0.96, 'field_type': 'STRING', 'source': 'OCR'},
                'Beneficiary Medicare ID': {'value': '7XW9WR9QD20', 'confidence': 0.93, 'field_type': 'STRING', 'source': 'OCR'},
            }
        }
        
        # Apply auto-fix
        print("\n1. Applying auto-fix...")
        fixed_fields, _ = apply_auto_fix_to_fields(extracted_fields)
        
        # Create packet
        print("\n2. Creating packet...")
        decision_tracking_id = str(uuid4())
        packet_id = f"TEST-UTN-FAILURE-AND-VALIDATION-{int(datetime.now().timestamp())}"
        
        # Extract beneficiary name from fields for required field
        beneficiary_first = fixed_fields.get('fields', {}).get('Beneficiary First Name', {}).get('value', 'MARY')
        beneficiary_last = fixed_fields.get('fields', {}).get('Beneficiary Last Name', {}).get('value', 'JONES')
        beneficiary_name = f"{beneficiary_first} {beneficiary_last}"
        beneficiary_mbi = fixed_fields.get('fields', {}).get('Beneficiary Medicare ID', {}).get('value', '7XW9WR9QD20')
        provider_name = fixed_fields.get('fields', {}).get('Facility Provider Name', {}).get('value', 'GARDEN STATE MEDICAL CENTER')
        provider_npi = fixed_fields.get('fields', {}).get('Facility Provider NPI', {}).get('value', '123456789')
        submission_type = fixed_fields.get('fields', {}).get('Submission Type', {}).get('value', 'expedited-initial')
        
        # Calculate due_date: 48 hours for expedited, 72 hours for standard
        received_date = datetime.now(timezone.utc) - timedelta(days=1)
        if 'expedited' in submission_type.lower():
            due_date = received_date + timedelta(hours=48)
        else:
            due_date = received_date + timedelta(hours=72)
        
        packet = PacketDB(
            external_id=packet_id,
            decision_tracking_id=decision_tracking_id,
            channel_type_id=1,  # Fax
            detailed_status="Pending - Clinical Review",
            received_date=received_date,
            due_date=due_date,
            beneficiary_name=beneficiary_name,
            beneficiary_mbi=beneficiary_mbi,
            provider_name=provider_name,
            provider_npi=provider_npi,
            service_type="Prior Authorization",  # Required field
            submission_type=submission_type,
            has_field_validation_errors=True,  # Will be set by validation
            created_at=datetime.now(timezone.utc)
        )
        db.add(packet)
        db.flush()
        
        # Create document
        print("\n3. Creating document...")
        document = PacketDocumentDB(
            packet_id=packet.packet_id,
            external_id=f"DOC-{packet_id}",
            file_name=f"{packet_id}.pdf",  # Required field
            document_unique_identifier=f"TEST-{packet_id}-{int(datetime.now().timestamp())}",  # Required field
            document_type_id=1,  # Required field - default document type
            extracted_fields=fixed_fields,
            updated_extracted_fields=fixed_fields,
            part_type="PART_B",
            created_at=datetime.now(timezone.utc)
        )
        db.add(document)
        db.flush()
        
        # Sync packet from extracted fields (updates other fields)
        print("\n4. Syncing packet from extracted fields...")
        sync_packet_from_extracted_fields(packet, fixed_fields, datetime.now(timezone.utc), db)
        db.commit()
        
        # Run validation (should find errors)
        print("\n5. Running validation...")
        validation_result = validate_all_fields(fixed_fields, packet, db)
        print(f"   Validation errors found: {validation_result['has_errors']}")
        if validation_result['has_errors']:
            print("   Errors:")
            for field, errors in validation_result.get('field_errors', {}).items():
                print(f"     - {field}: {', '.join(errors)}")
        
        save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        
        db.refresh(packet)
        print(f"   Validation errors: {packet.has_field_validation_errors} (should be True)")
        
        # Create packet_decision with UTN failure
        print("\n6. Creating packet_decision with UTN failure...")
        utn_fail_payload = {
            'error_code': 'INVALID_PROVIDER_NPI',
            'error_description': 'Provider NPI validation failed at ESMD',
            'action_required': 'Verify provider NPI and resubmit to ESMD',
            'part_type': 'B',
            'esmd_transaction_id': f'ESMD-{int(datetime.now().timestamp())}',
            'unique_id': packet_id,
        }
        
        packet_decision = PacketDecisionDB(
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            decision_type='APPROVE',
            operational_decision='DECISION_COMPLETE',
            clinical_decision='AFFIRM',
            decision_outcome='AFFIRM',
            part_type='B',
            decision_subtype='DIRECT_PA',
            utn_status='FAILED',
            utn_received_at=datetime.now(timezone.utc),
            utn_fail_payload=utn_fail_payload,
            utn_action_required=utn_fail_payload['action_required'],
            requires_utn_fix=True,
            is_active=True,
            created_by='SYSTEM',
            created_at=datetime.now(timezone.utc)
        )
        db.add(packet_decision)
        db.commit()
        
        print("\n" + "=" * 80)
        print("Packet with BOTH UTN failure AND validation errors created successfully!")
        print("=" * 80)
        print(f"\nPacket ID: {packet_id}")
        print(f"Packet DB ID: {packet.packet_id}")
        print(f"Decision Tracking ID: {decision_tracking_id}")
        print(f"Has Validation Errors: {packet.has_field_validation_errors} (should be True)")
        print(f"UTN Status: {packet_decision.utn_status}")
        print(f"Requires UTN Fix: {packet_decision.requires_utn_fix}")
        print(f"Error Code: {utn_fail_payload['error_code']}")
        
        return packet_id, packet.packet_id, decision_tracking_id
        
    except Exception as e:
        db.rollback()
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


def main():
    """Create both test packets"""
    print("\n" + "=" * 80)
    print("Creating Test Packets with UTN Failures")
    print("=" * 80)
    
    try:
        # Create packet with only UTN failure
        packet1_id, packet1_db_id, dt_id1 = create_packet_with_utn_failure_only()
        
        # Create packet with both UTN failure and validation errors
        packet2_id, packet2_db_id, dt_id2 = create_packet_with_both_utn_failure_and_validation()
        
        print("\n\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print("\n1. Packet with ONLY UTN failure:")
        print(f"   - Packet ID: {packet1_id}")
        print(f"   - Should show: RED badge (UTN failure)")
        print(f"   - Should NOT show: Amber badge (validation)")
        
        print("\n2. Packet with BOTH UTN failure AND validation errors:")
        print(f"   - Packet ID: {packet2_id}")
        print(f"   - Should show: RED badge (UTN failure) - takes priority")
        print(f"   - Should NOT show: Amber badge (hidden when UTN failure exists)")
        
        print("\n" + "=" * 80)
        print("To test in UI:")
        print("=" * 80)
        print(f"1. Search for: {packet1_id}")
        print("   - Should see RED badge and RED left border")
        print("   - Should NOT see amber validation badge")
        print(f"\n2. Search for: {packet2_id}")
        print("   - Should see RED badge and RED left border")
        print("   - Should NOT see amber validation badge (UTN failure takes priority)")
        print("=" * 80)
        
    except Exception as e:
        print(f"\nERROR: Failed to create test packets: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
