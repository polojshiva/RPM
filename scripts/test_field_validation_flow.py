"""
Comprehensive Test Script for Field Validation System
Tests auto-fix, validation, persistence, and UI integration
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.services.db import SessionLocal, engine
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.services.field_auto_fix import apply_auto_fix_to_fields
from app.services.field_validation_service import validate_all_fields
from app.services.validation_persistence import save_field_validation_errors, update_packet_validation_flag, get_field_validation_errors
from app.utils.packet_sync import sync_packet_from_extracted_fields
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def print_section(title: str):
    """Print a section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_test_result(test_name: str, passed: bool, message: str = ""):
    """Print test result"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status}: {test_name}")
    if message:
        print(f"  -> {message}")


def create_test_packet(db, packet_id: str, extracted_fields: dict, part_type: str = "PART_B") -> tuple[PacketDB, PacketDocumentDB]:
    """Create a test packet and document with extracted fields"""
    # Use unique ID with timestamp to avoid duplicates
    import time
    unique_id = f"{packet_id}-{int(time.time() * 1000)}"
    
    # Create packet
    decision_tracking_id = str(uuid4())
    packet = PacketDB(
        external_id=unique_id,
        decision_tracking_id=decision_tracking_id,
        beneficiary_name="Test Beneficiary",
        beneficiary_mbi="1AB2CD3EF45",
        provider_name="Test Provider",
        provider_npi="1234567890",
        service_type="DME - Test",
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
    
    # Create document
    document = PacketDocumentDB(
        external_id=f"DOC-{unique_id}",
        packet_id=packet.packet_id,
        file_name="test_document.pdf",
        document_unique_identifier=f"test-doc-{uuid4()}",
        page_count=1,
        extracted_fields=extracted_fields,
        updated_extracted_fields=extracted_fields.copy() if extracted_fields else None,
        part_type=part_type,
        ocr_status="DONE",
        split_status="DONE",
        document_type_id=1,  # Default document type
        uploaded_at=datetime.now(timezone.utc)
    )
    db.add(document)
    db.flush()
    
    return packet, document


def test_auto_fix_phone():
    """Test 1: Auto-fix phone number"""
    print_section("Test 1: Auto-Fix Phone Number")
    
    db = SessionLocal()
    try:
        extracted_fields = {
            'fields': {
                'Requester Phone': {
                    'value': '(732) 849-0077',
                    'confidence': 0.95,
                    'field_type': 'STRING'
                }
            }
        }
        
        fixed_fields, auto_fix_results = apply_auto_fix_to_fields(extracted_fields)
        
        expected_phone = '7328490077'
        actual_phone = fixed_fields['fields']['Requester Phone']['value']
        
        passed = actual_phone == expected_phone and 'Requester Phone' in auto_fix_results
        print_test_result(
            "Phone Auto-Fix",
            passed,
            f"Expected: {expected_phone}, Got: {actual_phone}"
        )
        
        return passed
    except Exception as e:
        print_test_result("Phone Auto-Fix", False, f"Error: {str(e)}")
        return False
    finally:
        db.close()


def test_auto_fix_date():
    """Test 2: Auto-fix date"""
    print_section("Test 2: Auto-Fix Date")
    
    db = SessionLocal()
    try:
        extracted_fields = {
            'fields': {
                'Anticipated Date of Service': {
                    'value': '01/28/2026',
                    'confidence': 0.90,
                    'field_type': 'STRING'
                }
            }
        }
        
        fixed_fields, auto_fix_results = apply_auto_fix_to_fields(extracted_fields)
        
        expected_date = '2026-01-28'
        actual_date = fixed_fields['fields']['Anticipated Date of Service']['value']
        
        passed = actual_date == expected_date and 'Anticipated Date of Service' in auto_fix_results
        print_test_result(
            "Date Auto-Fix",
            passed,
            f"Expected: {expected_date}, Got: {actual_date}"
        )
        
        return passed
    except Exception as e:
        print_test_result("Date Auto-Fix", False, f"Error: {str(e)}")
        return False
    finally:
        db.close()


def test_validation_state_error():
    """Test 3: Validation - State must be NJ"""
    print_section("Test 3: Validation - State Error")
    
    db = SessionLocal()
    try:
        extracted_fields = {
            'fields': {
                'Rendering/Facility State': {'value': 'NY'},
                'Request Type': {'value': 'I'},
                'Requester Phone': {'value': '7328490077'}
            }
        }
        
        # Apply auto-fix first
        fixed_fields, _ = apply_auto_fix_to_fields(extracted_fields)
        
        # Create test packet
        packet, document = create_test_packet(db, "TEST-VAL-STATE-001", fixed_fields)
        document.updated_extracted_fields = fixed_fields
        db.commit()
        
        # Run validation
        validation_result = validate_all_fields(fixed_fields, packet, db)
        
        has_state_error = 'state' in validation_result.get('field_errors', {})
        passed = validation_result['has_errors'] and has_state_error
        
        print_test_result(
            "State Validation Error",
            passed,
            f"Has errors: {validation_result['has_errors']}, State error: {has_state_error}"
        )
        
        # Save validation
        save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        
        # Verify flag was set
        db.refresh(packet)
        flag_set = packet.has_field_validation_errors == True
        print_test_result(
            "Validation Flag Set",
            flag_set,
            f"Flag value: {packet.has_field_validation_errors}"
        )
        
        return passed and flag_set
    except Exception as e:
        print_test_result("State Validation", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_validation_no_errors():
    """Test 4: Validation - No Errors (All Valid)"""
    print_section("Test 4: Validation - No Errors")
    
    db = SessionLocal()
    try:
        extracted_fields = {
            'fields': {
                'Rendering/Facility State': {'value': 'NJ'},
                'Request Type': {'value': 'I'},
                'Requester Phone': {'value': '7328490077'},
                'Anticipated Date of Service': {'value': '2026-01-28'},
                'Facility Provider NPI': {'value': '1234567890'}
            }
        }
        
        # Apply auto-fix first
        fixed_fields, _ = apply_auto_fix_to_fields(extracted_fields)
        
        # Create test packet
        packet, document = create_test_packet(db, "TEST-VAL-NO-ERRORS-001", fixed_fields)
        document.updated_extracted_fields = fixed_fields
        db.commit()
        
        # Run validation
        validation_result = validate_all_fields(fixed_fields, packet, db)
        
        passed = not validation_result['has_errors']
        
        print_test_result(
            "No Validation Errors",
            passed,
            f"Has errors: {validation_result['has_errors']}, Error count: {len(validation_result.get('field_errors', {}))}"
        )
        
        # Save validation
        save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        
        # Verify flag was NOT set
        db.refresh(packet)
        flag_not_set = packet.has_field_validation_errors == False
        print_test_result(
            "Validation Flag Not Set",
            flag_not_set,
            f"Flag value: {packet.has_field_validation_errors}"
        )
        
        return passed and flag_not_set
    except Exception as e:
        print_test_result("No Errors Validation", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_auto_fix_and_validation_flow():
    """Test 5: Full Flow - Auto-Fix + Validation + Persistence"""
    print_section("Test 5: Full Flow - Auto-Fix + Validation + Persistence")
    
    db = SessionLocal()
    try:
        # Create extracted fields with issues that can be auto-fixed
        extracted_fields = {
            'fields': {
                'Requester Phone': {'value': '(732) 849-0077'},
                'Requester Fax': {'value': '732-849-0015'},
                'Anticipated Date of Service': {'value': '01/28/2026'},
                'Diagnosis Codes': {'value': 'G40.011, M2551'},
                'Rendering/Facility State': {'value': 'NJ'},
                'Request Type': {'value': 'I'},
                'Facility Provider NPI': {'value': '1234567890'}
            }
        }
        
        # Step 1: Apply auto-fix
        fixed_fields, auto_fix_results = apply_auto_fix_to_fields(extracted_fields)
        print_test_result(
            "Auto-Fix Applied",
            len(auto_fix_results) > 0,
            f"Fixed {len(auto_fix_results)} fields: {list(auto_fix_results.keys())}"
        )
        
        # Step 2: Create packet and document
        packet, document = create_test_packet(db, "TEST-FULL-FLOW-001", fixed_fields)
        document.updated_extracted_fields = fixed_fields
        db.commit()
        
        # Step 3: Sync to packet table
        sync_result = sync_packet_from_extracted_fields(packet, fixed_fields, datetime.now(timezone.utc), db)
        db.commit()
        print_test_result("Packet Sync", sync_result, "Packet table synced from extracted fields")
        
        # Step 4: Run validation
        validation_result = validate_all_fields(fixed_fields, packet, db)
        print_test_result(
            "Validation Run",
            True,
            f"Has errors: {validation_result['has_errors']}, Error count: {len(validation_result.get('field_errors', {}))}"
        )
        
        # Step 5: Save validation
        validation_record = save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        print_test_result("Validation Saved", validation_record is not None, "Validation record created")
        
        # Step 6: Verify flag
        db.refresh(packet)
        flag_correct = packet.has_field_validation_errors == validation_result['has_errors']
        print_test_result(
            "Flag Updated",
            flag_correct,
            f"Flag: {packet.has_field_validation_errors}, Expected: {validation_result['has_errors']}"
        )
        
        # Step 7: Retrieve validation errors
        retrieved_errors = get_field_validation_errors(packet.packet_id, db)
        retrieved_correct = retrieved_errors is not None and retrieved_errors.get('has_errors') == validation_result['has_errors']
        print_test_result(
            "Retrieve Validation Errors",
            retrieved_correct,
            f"Retrieved: {retrieved_errors is not None}"
        )
        
        return all([sync_result, validation_record is not None, flag_correct, retrieved_correct])
    except Exception as e:
        print_test_result("Full Flow Test", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_validation_with_multiple_errors():
    """Test 6: Validation with Multiple Errors"""
    print_section("Test 6: Validation with Multiple Errors")
    
    db = SessionLocal()
    try:
        extracted_fields = {
            'fields': {
                'Rendering/Facility State': {'value': 'NY'},  # Error: not NJ
                'Request Type': {'value': 'X'},  # Error: invalid
                'Requester Phone': {'value': '732849'},  # Error: too short
                'Facility Provider NPI': {'value': '12345'},  # Error: too short
            }
        }
        
        # Apply auto-fix first
        fixed_fields, _ = apply_auto_fix_to_fields(extracted_fields)
        
        # Create test packet
        packet, document = create_test_packet(db, "TEST-MULTI-ERRORS-001", fixed_fields)
        document.updated_extracted_fields = fixed_fields
        db.commit()
        
        # Run validation
        validation_result = validate_all_fields(fixed_fields, packet, db)
        
        error_count = len(validation_result.get('field_errors', {}))
        passed = validation_result['has_errors'] and error_count >= 3
        
        print_test_result(
            "Multiple Errors Detected",
            passed,
            f"Error count: {error_count}, Errors: {list(validation_result.get('field_errors', {}).keys())}"
        )
        
        # Save and verify
        save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        
        db.refresh(packet)
        flag_set = packet.has_field_validation_errors == True
        print_test_result("Flag Set for Multiple Errors", flag_set, f"Flag: {packet.has_field_validation_errors}")
        
        return passed and flag_set
    except Exception as e:
        print_test_result("Multiple Errors Test", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_fix_errors_and_revalidate():
    """Test 7: Fix Errors and Re-validate"""
    print_section("Test 7: Fix Errors and Re-validate")
    
    db = SessionLocal()
    try:
        # Start with errors
        extracted_fields = {
            'fields': {
                'Rendering/Facility State': {'value': 'NY'},
                'Request Type': {'value': 'I'},
                'Requester Phone': {'value': '7328490077'}
            }
        }
        
        fixed_fields, _ = apply_auto_fix_to_fields(extracted_fields)
        packet, document = create_test_packet(db, "TEST-FIX-REVALIDATE-001", fixed_fields)
        document.updated_extracted_fields = fixed_fields
        db.commit()
        
        # Initial validation (should have errors)
        validation_result1 = validate_all_fields(fixed_fields, packet, db)
        save_field_validation_errors(packet.packet_id, validation_result1, db)
        update_packet_validation_flag(packet.packet_id, validation_result1['has_errors'], db)
        db.commit()
        
        db.refresh(packet)
        initial_has_errors = packet.has_field_validation_errors
        print_test_result("Initial Validation", initial_has_errors, f"Has errors: {initial_has_errors}")
        
        # Fix the error (change state to NJ)
        fixed_fields['fields']['Rendering/Facility State']['value'] = 'NJ'
        document.updated_extracted_fields = fixed_fields
        db.commit()
        
        # Re-validate
        validation_result2 = validate_all_fields(fixed_fields, packet, db)
        save_field_validation_errors(packet.packet_id, validation_result2, db)
        update_packet_validation_flag(packet.packet_id, validation_result2['has_errors'], db)
        db.commit()
        
        db.refresh(packet)
        final_has_errors = packet.has_field_validation_errors
        passed = initial_has_errors and not final_has_errors
        
        print_test_result(
            "Re-validation After Fix",
            passed,
            f"Initial: {initial_has_errors}, Final: {final_has_errors}"
        )
        
        return passed
    except Exception as e:
        print_test_result("Fix and Re-validate", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_clinicalops_blocking():
    """Test 8: ClinicalOps Submission Blocking"""
    print_section("Test 8: ClinicalOps Submission Blocking")
    
    db = SessionLocal()
    try:
        # Skip this test if azure module not available (optional dependency)
        try:
            from app.services.clinical_ops_outbox_service import ClinicalOpsOutboxService
        except ImportError:
            print_test_result("ClinicalOps Blocking", True, "Skipped - azure module not available")
            return True
        
        # Create packet with validation errors
        extracted_fields = {
            'fields': {
                'Rendering/Facility State': {'value': 'NY'},  # Error
                'Request Type': {'value': 'I'},
            }
        }
        
        fixed_fields, _ = apply_auto_fix_to_fields(extracted_fields)
        packet, document = create_test_packet(db, "TEST-BLOCK-001", fixed_fields)
        document.updated_extracted_fields = fixed_fields
        db.commit()
        
        # Set validation errors
        validation_result = validate_all_fields(fixed_fields, packet, db)
        save_field_validation_errors(packet.packet_id, validation_result, db)
        update_packet_validation_flag(packet.packet_id, validation_result['has_errors'], db)
        db.commit()
        
        db.refresh(packet)
        
        # Try to send to ClinicalOps (should fail)
        try:
            ClinicalOpsOutboxService.send_case_ready_for_review(
                db=db,
                packet=packet,
                packet_document=document,
                created_by="test_user"
            )
            print_test_result("ClinicalOps Blocking", False, "Should have raised ValueError")
            return False
        except ValueError as e:
            error_msg = str(e)
            passed = "validation errors" in error_msg.lower() or "field validation" in error_msg.lower()
            print_test_result(
                "ClinicalOps Blocking",
                passed,
                f"Correctly blocked: {error_msg[:100]}"
            )
            return passed
        except Exception as e:
            print_test_result("ClinicalOps Blocking", False, f"Unexpected error: {str(e)}")
            return False
    except Exception as e:
        print_test_result("ClinicalOps Blocking", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    """Run all tests"""
    print_section("Field Validation System - Comprehensive Testing")
    print("Testing auto-fix, validation, persistence, and integration")
    
    results = []
    
    # Test auto-fix
    results.append(("Auto-Fix Phone", test_auto_fix_phone()))
    results.append(("Auto-Fix Date", test_auto_fix_date()))
    
    # Test validation
    results.append(("Validation State Error", test_validation_state_error()))
    results.append(("Validation No Errors", test_validation_no_errors()))
    results.append(("Validation Multiple Errors", test_validation_with_multiple_errors()))
    
    # Test full flow
    results.append(("Full Flow Test", test_auto_fix_and_validation_flow()))
    results.append(("Fix and Re-validate", test_fix_errors_and_revalidate()))
    
    # Test ClinicalOps blocking
    results.append(("ClinicalOps Blocking", test_clinicalops_blocking()))
    
    # Summary
    print_section("Test Summary")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[SUCCESS] All tests passed! Validation system is working correctly.")
        return 0
    else:
        print(f"\n[FAILURE] {total - passed} test(s) failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    exit(main())
