"""
End-to-End Letter Generation Workflow Test
Tests the complete workflow from UTN received to letter generation for:
1. AFFIRM decisions
2. NON_AFFIRM decisions  
3. DISMISSAL decisions

This script creates synthetic records and tests the actual letter generation module.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
import json

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_decision_db import PacketDecisionDB
from app.services.utn_handlers import UtnSuccessHandler
from app.services.dismissal_workflow_service import DismissalWorkflowService
from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
from app.services.workflow_orchestrator import WorkflowOrchestratorService
from app.config.settings import settings

# Test results
test_results = []

def log_test(name: str, passed: bool, message: str = ""):
    """Log test result"""
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name} - {message}")
    test_results.append({"test": name, "passed": passed, "message": message})

def create_test_packet(db: Session, decision_tracking_id: str, channel_type_id: int = 1) -> PacketDB:
    """Create a synthetic test packet"""
    now = datetime.now(timezone.utc)
    packet = PacketDB(
        decision_tracking_id=uuid.UUID(decision_tracking_id),
        external_id=f"TEST-{decision_tracking_id[:8]}",
        channel_type_id=channel_type_id,
        beneficiary_name="John Doe",
        beneficiary_mbi="1S2A3B4C5D6E7F8G9H",
        provider_name="UPMC Jameson",
        provider_npi="1234567890",
        provider_fax="5551234567",
        submission_type="Standard",
        service_type="Prior Authorization",
        received_date=now,
        due_date=now,  # Required field
        detailed_status="Pending - UTN",
        created_at=now,
        updated_at=now
    )
    db.add(packet)
    db.flush()
    return packet

def create_test_document(db: Session, packet: PacketDB) -> PacketDocumentDB:
    """Create a synthetic test document"""
    now = datetime.now(timezone.utc)
    document = PacketDocumentDB(
        external_id=f"DOC-TEST-{packet.packet_id}",
        packet_id=packet.packet_id,
        file_name="test_coversheet.pdf",
        document_unique_identifier=f"TEST-{packet.packet_id}-{now.timestamp()}",
        file_size="1024",
        page_count=1,
        document_type_id=1,  # Required field
        status_type_id=1,  # Required field
        coversheet_page_number=1,
        part_type="B",
        uploaded_at=now,
        extracted_fields={
            "fields": {
                "Beneficiary Name": {"value": "John Doe", "confidence": 0.95, "field_type": "STRING"},
                "Beneficiary Medicare ID": {"value": "1S2A3B4C5D6E7F8G9H", "confidence": 0.98, "field_type": "STRING"},
                "Provider Name": {"value": "UPMC Jameson", "confidence": 0.92, "field_type": "STRING"},
                "Procedure Code set 1": {"value": "69799", "confidence": 0.90, "field_type": "STRING"}
            },
            "coversheet_type": "Prior Authorization Request Medicare Part B",
            "source": "TEST"
        },
        updated_extracted_fields={
            "fields": {
                "Beneficiary Name": {"value": "John Doe", "confidence": 0.95, "field_type": "STRING"},
                "Beneficiary Medicare ID": {"value": "1S2A3B4C5D6E7F8G9H", "confidence": 0.98, "field_type": "STRING"},
                "Provider Name": {"value": "UPMC Jameson", "confidence": 0.92, "field_type": "STRING"},
                "Procedure Code set 1": {"value": "69799", "confidence": 0.90, "field_type": "STRING"}
            },
            "coversheet_type": "Prior Authorization Request Medicare Part B",
            "source": "TEST"
        },
        created_at=now,
        updated_at=now
    )
    db.add(document)
    db.flush()
    return document

def create_test_decision(
    db: Session,
    packet: PacketDB,
    document: PacketDocumentDB,
    decision_outcome: str,
    decision_subtype: str = "STANDARD_PA"
) -> PacketDecisionDB:
    """Create a synthetic test decision"""
    decision = PacketDecisionDB(
        packet_id=packet.packet_id,
        packet_document_id=document.packet_document_id,
        decision_type="APPROVE",
        decision_outcome=decision_outcome,
        decision_subtype=decision_subtype,
        part_type="B",
        clinical_decision="PENDING",
        operational_decision="PENDING",
        utn_status=None,  # Will be set when UTN received
        letter_status=None,  # Will be set when letter generated
        is_active=True,
        created_by="SYSTEM",
        created_at=datetime.now(timezone.utc)
    )
    db.add(decision)
    db.flush()
    return decision

def test_affirm_workflow(db: Session):
    """Test AFFIRM decision workflow: UTN received → Letter generation"""
    print("\n" + "=" * 80)
    print("TEST 1: AFFIRM Decision Workflow")
    print("=" * 80)
    
    try:
        # 1. Create test packet, document, and decision
        decision_tracking_id = str(uuid.uuid4())
        packet = create_test_packet(db, decision_tracking_id, channel_type_id=1)
        document = create_test_document(db, packet)
        decision = create_test_decision(db, packet, document, "AFFIRM", "STANDARD_PA")
        
        log_test("Create Test Records", True, f"Created packet_id={packet.packet_id}, decision_id={decision.packet_decision_id}")
        
        # 2. Simulate UTN_SUCCESS message
        utn_message = {
            "message_id": 1,
            "decision_tracking_id": uuid.UUID(decision_tracking_id),
            "payload": {
                "unique_tracking_number": "UTN123456789",
                "esmd_transaction_id": "ESMD123456",
                "unique_id": "UNIQUE123",
                "destination_type": "MAIL"
            },
            "created_at": datetime.now(timezone.utc)
        }
        
        # 3. Handle UTN_SUCCESS (this should trigger letter generation)
        import asyncio
        asyncio.run(UtnSuccessHandler.handle(db, utn_message))
        
        # 4. Refresh decision from DB
        db.refresh(decision)
        db.refresh(packet)
        
        # 5. Verify UTN was set
        if decision.utn == "UTN123456789" and decision.utn_status == "SUCCESS":
            log_test("UTN Received", True, f"UTN={decision.utn}, status={decision.utn_status}")
        else:
            log_test("UTN Received", False, f"UTN={decision.utn}, status={decision.utn_status}")
            return
        
        # 6. Verify letter was generated
        if decision.letter_status == "READY":
            log_test("Letter Generated", True, f"Letter status={decision.letter_status}")
            
            # Check letter_package
            letter_package = decision.letter_package or {}
            if letter_package.get("blob_url"):
                log_test("Letter Package", True, f"Blob URL: {letter_package.get('blob_url')[:50]}...")
            else:
                log_test("Letter Package", False, "No blob_url in letter_package")
        else:
            log_test("Letter Generated", False, f"Letter status={decision.letter_status}, package={decision.letter_package}")
        
        # 7. Verify packet status
        expected_statuses = ["Generate Decision Letter - Complete", "Send Decision Letter - Complete", "Decision Complete"]
        if packet.detailed_status in expected_statuses:
            log_test("Packet Status", True, f"Status={packet.detailed_status}")
        else:
            log_test("Packet Status", False, f"Status={packet.detailed_status}, expected one of {expected_statuses}")
        
        # 8. Verify operational decision
        if decision.operational_decision == "DECISION_COMPLETE":
            log_test("Operational Decision", True, f"Decision={decision.operational_decision}")
        else:
            log_test("Operational Decision", False, f"Decision={decision.operational_decision}, expected DECISION_COMPLETE")
        
        # Cleanup
        db.delete(decision)
        db.delete(document)
        db.delete(packet)
        db.commit()
        
        log_test("Cleanup", True, "Test records deleted")
        
    except Exception as e:
        log_test("AFFIRM Workflow", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()

def test_non_affirm_workflow(db: Session):
    """Test NON_AFFIRM decision workflow: UTN received → Letter generation"""
    print("\n" + "=" * 80)
    print("TEST 2: NON_AFFIRM Decision Workflow")
    print("=" * 80)
    
    try:
        # 1. Create test packet, document, and decision
        decision_tracking_id = str(uuid.uuid4())
        packet = create_test_packet(db, decision_tracking_id, channel_type_id=1)
        document = create_test_document(db, packet)
        decision = create_test_decision(db, packet, document, "NON_AFFIRM", "STANDARD_PA")
        
        # Add review codes and program codes for non-affirm
        decision.esmd_request_payload = {
            "procedures": [{
                "procedure_code": "69799",
                "review_codes": "0F",
                "program_codes": "GBC01"
            }]
        }
        db.flush()
        
        log_test("Create Test Records", True, f"Created packet_id={packet.packet_id}, decision_id={decision.packet_decision_id}")
        
        # 2. Simulate UTN_SUCCESS message
        utn_message = {
            "message_id": 2,
            "decision_tracking_id": uuid.UUID(decision_tracking_id),
            "payload": {
                "unique_tracking_number": "UTN987654321",
                "esmd_transaction_id": "ESMD987654",
                "unique_id": "UNIQUE987",
                "destination_type": "MAIL"
            },
            "created_at": datetime.now(timezone.utc)
        }
        
        # 3. Handle UTN_SUCCESS (this should trigger letter generation)
        import asyncio
        asyncio.run(UtnSuccessHandler.handle(db, utn_message))
        
        # 4. Refresh decision from DB
        db.refresh(decision)
        db.refresh(packet)
        
        # 5. Verify UTN was set
        if decision.utn == "UTN987654321" and decision.utn_status == "SUCCESS":
            log_test("UTN Received", True, f"UTN={decision.utn}, status={decision.utn_status}")
        else:
            log_test("UTN Received", False, f"UTN={decision.utn}, status={decision.utn_status}")
            return
        
        # 6. Verify letter was generated
        if decision.letter_status == "READY":
            log_test("Letter Generated", True, f"Letter status={decision.letter_status}")
            
            # Check letter_package
            letter_package = decision.letter_package or {}
            if letter_package.get("blob_url"):
                log_test("Letter Package", True, f"Blob URL: {letter_package.get('blob_url')[:50]}...")
            else:
                log_test("Letter Package", False, "No blob_url in letter_package")
        else:
            log_test("Letter Generated", False, f"Letter status={decision.letter_status}, package={decision.letter_package}")
        
        # 7. Verify packet status
        expected_statuses = ["Generate Decision Letter - Complete", "Send Decision Letter - Complete", "Decision Complete"]
        if packet.detailed_status in expected_statuses:
            log_test("Packet Status", True, f"Status={packet.detailed_status}")
        else:
            log_test("Packet Status", False, f"Status={packet.detailed_status}, expected one of {expected_statuses}")
        
        # Cleanup
        db.delete(decision)
        db.delete(document)
        db.delete(packet)
        db.commit()
        
        log_test("Cleanup", True, "Test records deleted")
        
    except Exception as e:
        log_test("NON_AFFIRM Workflow", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()

def test_dismissal_workflow(db: Session):
    """Test DISMISSAL decision workflow: Dismissal → Letter generation (no UTN required)"""
    print("\n" + "=" * 80)
    print("TEST 3: DISMISSAL Decision Workflow")
    print("=" * 80)
    
    try:
        # 1. Create test packet and document
        decision_tracking_id = str(uuid.uuid4())
        packet = create_test_packet(db, decision_tracking_id, channel_type_id=1)
        document = create_test_document(db, packet)
        
        # 2. Create dismissal decision
        decision = PacketDecisionDB(
            packet_id=packet.packet_id,
            packet_document_id=document.packet_document_id,
            decision_type="DISMISS",
            decision_outcome="DISMISSAL",
            decision_subtype=None,  # Dismissal doesn't have DIRECT_PA/STANDARD_PA
            part_type="B",
            clinical_decision="PENDING",  # Dismissal never sent to ClinicalOps
            operational_decision="DISMISSAL",
            denial_reason="Missing required documentation",
            denial_details={"missingFields": ["provider_fax"]},
            utn_status=None,  # Dismissal doesn't require UTN
            letter_status=None,  # Will be set when letter generated
            is_active=True,
            created_by="SYSTEM",
            created_at=datetime.now(timezone.utc)
        )
        db.add(decision)
        db.flush()
        
        log_test("Create Test Records", True, f"Created packet_id={packet.packet_id}, decision_id={decision.packet_decision_id}")
        
        # 3. Process dismissal (this should trigger letter generation immediately)
        DismissalWorkflowService.process_dismissal(
            db=db,
            packet=packet,
            packet_decision=decision,
            created_by="SYSTEM"
        )
        
        # 4. Refresh decision from DB
        db.refresh(decision)
        db.refresh(packet)
        
        # 5. Verify letter was generated (no UTN required)
        if decision.letter_status in ["READY", "SENT"]:
            log_test("Letter Generated", True, f"Letter status={decision.letter_status}")
            
            # Check letter_package
            letter_package = decision.letter_package or {}
            if letter_package.get("blob_url") or letter_package.get("notes"):
                log_test("Letter Package", True, f"Letter metadata present")
            else:
                log_test("Letter Package", False, "No letter metadata in letter_package")
        else:
            log_test("Letter Generated", False, f"Letter status={decision.letter_status}, package={decision.letter_package}")
        
        # 6. Verify packet status
        expected_statuses = ["Generate Decision Letter - Complete", "Send Decision Letter - Complete", "Dismissal Complete"]
        if packet.detailed_status in expected_statuses:
            log_test("Packet Status", True, f"Status={packet.detailed_status}")
        else:
            log_test("Packet Status", False, f"Status={packet.detailed_status}, expected one of {expected_statuses}")
        
        # 7. Verify operational decision
        if decision.operational_decision == "DISMISSAL_COMPLETE":
            log_test("Operational Decision", True, f"Decision={decision.operational_decision}")
        else:
            log_test("Operational Decision", False, f"Decision={decision.operational_decision}, expected DISMISSAL_COMPLETE")
        
        # Cleanup
        db.delete(decision)
        db.delete(document)
        db.delete(packet)
        db.commit()
        
        log_test("Cleanup", True, "Test records deleted")
        
    except Exception as e:
        log_test("DISMISSAL Workflow", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()

def test_lettergen_service_direct(db: Session):
    """Test LetterGenerationService directly"""
    print("\n" + "=" * 80)
    print("TEST 4: Direct LetterGenerationService Test")
    print("=" * 80)
    
    # Check if LetterGen is configured
    if not settings.lettergen_base_url:
        log_test("LetterGen Configuration", False, "LETTERGEN_BASE_URL not configured")
        print("  Note: Set LETTERGEN_BASE_URL environment variable to test actual letter generation")
        return
    
    try:
        # 1. Create test packet, document, and decision
        decision_tracking_id = str(uuid.uuid4())
        packet = create_test_packet(db, decision_tracking_id, channel_type_id=1)
        document = create_test_document(db, packet)
        decision = create_test_decision(db, packet, document, "AFFIRM", "STANDARD_PA")
        
        log_test("Create Test Records", True, f"Created packet_id={packet.packet_id}")
        
        # 2. Test letter generation service directly
        letter_service = LetterGenerationService(db)
        
        try:
            letter_metadata = letter_service.generate_letter(
                packet=packet,
                packet_decision=decision,
                packet_document=document,
                letter_type="affirmation"
            )
            
            if letter_metadata.get("blob_url"):
                log_test("Letter Generation", True, f"Generated letter: {letter_metadata.get('filename')}")
                log_test("Letter Blob URL", True, f"URL: {letter_metadata.get('blob_url')[:60]}...")
            else:
                log_test("Letter Generation", False, "No blob_url in response")
                
        except LetterGenerationError as e:
            log_test("Letter Generation", False, f"LetterGenerationError: {str(e)}")
        except Exception as e:
            log_test("Letter Generation", False, f"Unexpected error: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Cleanup
        db.delete(decision)
        db.delete(document)
        db.delete(packet)
        db.commit()
        
        log_test("Cleanup", True, "Test records deleted")
        
    except Exception as e:
        log_test("Direct Service Test", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()

def main():
    """Run all tests"""
    print("=" * 80)
    print("Letter Generation Workflow End-to-End Test")
    print("=" * 80)
    print(f"Test Date: {datetime.now().isoformat()}")
    print(f"LetterGen Base URL: {settings.lettergen_base_url or 'NOT CONFIGURED'}")
    print()
    
    db = SessionLocal()
    try:
        # Run all tests
        test_affirm_workflow(db)
        test_non_affirm_workflow(db)
        test_dismissal_workflow(db)
        test_lettergen_service_direct(db)
        
        # Print summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        
        passed = sum(1 for r in test_results if r["passed"])
        failed = sum(1 for r in test_results if not r["passed"])
        
        print(f"Total Tests: {len(test_results)}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print()
        
        if failed > 0:
            print("FAILED TESTS:")
            for result in test_results:
                if not result["passed"]:
                    print(f"  - {result['test']}: {result['message']}")
            print()
        
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

