"""
Live Letter Generation Test - Creates real records and tests end-to-end
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
import uuid
import asyncio

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_decision_db import PacketDecisionDB
from app.services.utn_handlers import UtnSuccessHandler
from app.services.dismissal_workflow_service import DismissalWorkflowService
from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
from app.services.workflow_orchestrator import WorkflowOrchestratorService
from app.config.settings import settings

def print_status(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def find_or_create_test_packet(db: Session, test_id: str = "LETTERGEN-TEST") -> PacketDB:
    """Find existing test packet or create new one"""
    # Try to find existing test packet
    packet = db.query(PacketDB).filter(
        PacketDB.external_id.like(f"{test_id}%")
    ).order_by(PacketDB.created_at.desc()).first()
    
    if packet:
        print_status(f"Found existing test packet: {packet.external_id} (packet_id={packet.packet_id})")
        return packet
    
    # Create new test packet
    now = datetime.now(timezone.utc)
    decision_tracking_id = uuid.uuid4()
    
    packet = PacketDB(
        decision_tracking_id=decision_tracking_id,
        external_id=f"{test_id}-{now.strftime('%Y%m%d-%H%M%S')}",
        channel_type_id=1,  # Portal
        beneficiary_name="Test Patient",
        beneficiary_mbi="1S2A3B4C5D6E7F8G9H",
        provider_name="Test Provider",
        provider_npi="1234567890",
        provider_fax="5551234567",
        submission_type="Standard",
        service_type="Prior Authorization",
        received_date=now,
        due_date=now + timedelta(days=30),
        detailed_status="Pending - UTN",
        created_at=now,
        updated_at=now
    )
    db.add(packet)
    db.flush()
    print_status(f"Created new test packet: {packet.external_id} (packet_id={packet.packet_id})")
    return packet

def find_or_create_test_document(db: Session, packet: PacketDB) -> PacketDocumentDB:
    """Find existing document or create new one"""
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id
    ).first()
    
    if document:
        print_status(f"Found existing document: {document.file_name} (doc_id={document.packet_document_id})")
        return document
    
    # Create new document
    now = datetime.now(timezone.utc)
    document = PacketDocumentDB(
        external_id=f"DOC-{packet.packet_id}",
        packet_id=packet.packet_id,
        file_name="test_coversheet.pdf",
        document_unique_identifier=f"TEST-{packet.packet_id}-{now.timestamp()}",
        file_size="1024",
        page_count=1,
        document_type_id=1,
        status_type_id=1,
        coversheet_page_number=1,
        part_type="B",
        uploaded_at=now,
        extracted_fields={
            "fields": {
                "Beneficiary Name": {"value": "Test Patient", "confidence": 0.95, "field_type": "STRING"},
                "Beneficiary Medicare ID": {"value": "1S2A3B4C5D6E7F8G9H", "confidence": 0.98, "field_type": "STRING"},
                "Provider Name": {"value": "Test Provider", "confidence": 0.92, "field_type": "STRING"},
                "Procedure Code set 1": {"value": "69799", "confidence": 0.90, "field_type": "STRING"}
            },
            "coversheet_type": "Prior Authorization Request Medicare Part B",
            "source": "TEST"
        },
        updated_extracted_fields={
            "fields": {
                "Beneficiary Name": {"value": "Test Patient", "confidence": 0.95, "field_type": "STRING"},
                "Beneficiary Medicare ID": {"value": "1S2A3B4C5D6E7F8G9H", "confidence": 0.98, "field_type": "STRING"},
                "Provider Name": {"value": "Test Provider", "confidence": 0.92, "field_type": "STRING"},
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
    print_status(f"Created new document: {document.file_name} (doc_id={document.packet_document_id})")
    return document

def test_affirm_workflow(db: Session):
    """Test AFFIRM workflow end-to-end"""
    print("\n" + "="*80)
    print("TEST: AFFIRM Decision Workflow")
    print("="*80)
    
    try:
        # 1. Get or create packet and document
        packet = find_or_create_test_packet(db, "AFFIRM-TEST")
        document = find_or_create_test_document(db, packet)
        
        # 2. Check for existing decision
        decision = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == packet.packet_id,
            PacketDecisionDB.is_active == True
        ).first()
        
        if decision and decision.decision_outcome == "AFFIRM" and decision.utn_status == "SUCCESS":
            print_status("Decision already exists with UTN. Testing letter generation...")
        else:
            # Create or update decision
            if decision:
                decision.decision_outcome = "AFFIRM"
                decision.decision_subtype = "STANDARD_PA"
                decision.part_type = "B"
                decision.clinical_decision = "AFFIRM"
                decision.operational_decision = "PENDING"
                decision.utn_status = None
                decision.letter_status = None
                print_status("Updated existing decision to AFFIRM")
            else:
                decision = PacketDecisionDB(
                    packet_id=packet.packet_id,
                    packet_document_id=document.packet_document_id,
                    decision_type="APPROVE",
                    decision_outcome="AFFIRM",
                    decision_subtype="STANDARD_PA",
                    part_type="B",
                    clinical_decision="AFFIRM",
                    operational_decision="PENDING",
                    is_active=True,
                    created_by="SYSTEM",
                    created_at=datetime.now(timezone.utc)
                )
                db.add(decision)
                print_status("Created new AFFIRM decision")
            
            db.flush()
            
            # 3. Simulate UTN_SUCCESS
            print_status("Simulating UTN_SUCCESS message...")
            utn_message = {
                "message_id": 1,
                "decision_tracking_id": packet.decision_tracking_id,
                "payload": {
                    "unique_tracking_number": f"UTN-{packet.packet_id}-{int(datetime.now().timestamp())}",
                    "esmd_transaction_id": f"ESMD-{packet.packet_id}",
                    "unique_id": f"UNIQUE-{packet.packet_id}",
                    "destination_type": "MAIL"
                },
                "created_at": datetime.now(timezone.utc)
            }
            
            # Process UTN (this should trigger letter generation)
            asyncio.run(UtnSuccessHandler.handle(db, utn_message))
            db.commit()
            print_status("UTN_SUCCESS processed")
        
        # 4. Refresh and check results
        db.refresh(decision)
        db.refresh(packet)
        
        print_status(f"UTN: {decision.utn}, Status: {decision.utn_status}")
        print_status(f"Letter Status: {decision.letter_status}")
        print_status(f"Packet Status: {packet.detailed_status}")
        
        if decision.letter_status == "READY" or decision.letter_status == "SENT":
            letter_package = decision.letter_package or {}
            blob_url = letter_package.get("blob_url", "N/A")
            print_status(f"SUCCESS: Letter generated! Blob URL: {blob_url[:60]}...")
            print_status(f"Operational Decision: {decision.operational_decision}")
            return True
        else:
            print_status(f"WARNING: Letter status is {decision.letter_status}")
            if decision.letter_package:
                print_status(f"Letter package: {decision.letter_package}")
            return False
            
    except Exception as e:
        print_status(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False

def test_non_affirm_workflow(db: Session):
    """Test NON_AFFIRM workflow end-to-end"""
    print("\n" + "="*80)
    print("TEST: NON_AFFIRM Decision Workflow")
    print("="*80)
    
    try:
        # 1. Get or create packet and document
        packet = find_or_create_test_packet(db, "NONAFFIRM-TEST")
        document = find_or_create_test_document(db, packet)
        
        # 2. Create or update decision
        decision = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == packet.packet_id,
            PacketDecisionDB.is_active == True
        ).first()
        
        if decision and decision.decision_outcome == "NON_AFFIRM" and decision.utn_status == "SUCCESS":
            print_status("Decision already exists with UTN. Testing letter generation...")
        else:
            if decision:
                decision.decision_outcome = "NON_AFFIRM"
                decision.decision_subtype = "STANDARD_PA"
                decision.part_type = "B"
                decision.clinical_decision = "NON_AFFIRM"
                decision.operational_decision = "PENDING"
                decision.utn_status = None
                decision.letter_status = None
                decision.esmd_request_payload = {
                    "procedures": [{
                        "procedure_code": "69799",
                        "review_codes": "0F",
                        "program_codes": "GBC01"
                    }]
                }
                print_status("Updated existing decision to NON_AFFIRM")
            else:
                decision = PacketDecisionDB(
                    packet_id=packet.packet_id,
                    packet_document_id=document.packet_document_id,
                    decision_type="APPROVE",
                    decision_outcome="NON_AFFIRM",
                    decision_subtype="STANDARD_PA",
                    part_type="B",
                    clinical_decision="NON_AFFIRM",
                    operational_decision="PENDING",
                    esmd_request_payload={
                        "procedures": [{
                            "procedure_code": "69799",
                            "review_codes": "0F",
                            "program_codes": "GBC01"
                        }]
                    },
                    is_active=True,
                    created_by="SYSTEM",
                    created_at=datetime.now(timezone.utc)
                )
                db.add(decision)
                print_status("Created new NON_AFFIRM decision")
            
            db.flush()
            
            # 3. Simulate UTN_SUCCESS
            print_status("Simulating UTN_SUCCESS message...")
            utn_message = {
                "message_id": 2,
                "decision_tracking_id": packet.decision_tracking_id,
                "payload": {
                    "unique_tracking_number": f"UTN-{packet.packet_id}-{int(datetime.now().timestamp())}",
                    "esmd_transaction_id": f"ESMD-{packet.packet_id}",
                    "unique_id": f"UNIQUE-{packet.packet_id}",
                    "destination_type": "MAIL"
                },
                "created_at": datetime.now(timezone.utc)
            }
            
            asyncio.run(UtnSuccessHandler.handle(db, utn_message))
            db.commit()
            print_status("UTN_SUCCESS processed")
        
        # 4. Refresh and check results
        db.refresh(decision)
        db.refresh(packet)
        
        print_status(f"UTN: {decision.utn}, Status: {decision.utn_status}")
        print_status(f"Letter Status: {decision.letter_status}")
        print_status(f"Packet Status: {packet.detailed_status}")
        
        if decision.letter_status == "READY" or decision.letter_status == "SENT":
            letter_package = decision.letter_package or {}
            blob_url = letter_package.get("blob_url", "N/A")
            print_status(f"SUCCESS: Letter generated! Blob URL: {blob_url[:60]}...")
            return True
        else:
            print_status(f"WARNING: Letter status is {decision.letter_status}")
            return False
            
    except Exception as e:
        print_status(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False

def test_dismissal_workflow(db: Session):
    """Test DISMISSAL workflow end-to-end"""
    print("\n" + "="*80)
    print("TEST: DISMISSAL Decision Workflow")
    print("="*80)
    
    try:
        # 1. Get or create packet and document
        packet = find_or_create_test_packet(db, "DISMISSAL-TEST")
        document = find_or_create_test_document(db, packet)
        
        # 2. Check for existing dismissal decision
        decision = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == packet.packet_id,
            PacketDecisionDB.is_active == True,
            PacketDecisionDB.decision_outcome == "DISMISSAL"
        ).first()
        
        if decision and decision.letter_status in ["READY", "SENT"]:
            print_status("Dismissal decision already exists with letter. Checking status...")
        else:
            # Create or update decision
            if decision:
                decision.decision_type = "DISMISSAL"
                decision.denial_reason = "MISSING_FIELDS"
                decision.denial_details = {"missingFields": ["provider_fax"]}
                decision.letter_status = None
                print_status("Updated existing decision to DISMISSAL")
            else:
                decision = PacketDecisionDB(
                    packet_id=packet.packet_id,
                    packet_document_id=document.packet_document_id,
                    decision_type="DISMISSAL",
                    decision_outcome="DISMISSAL",
                    decision_subtype=None,
                    part_type="B",
                    clinical_decision="PENDING",
                    operational_decision="DISMISSAL",
                    denial_reason="MISSING_FIELDS",
                    denial_details={"missingFields": ["provider_fax"]},
                    is_active=True,
                    created_by="SYSTEM",
                    created_at=datetime.now(timezone.utc)
                )
                db.add(decision)
                print_status("Created new DISMISSAL decision")
            
            db.flush()
            
            # 3. Process dismissal (this should generate letter immediately)
            print_status("Processing dismissal workflow...")
            DismissalWorkflowService.process_dismissal(
                db=db,
                packet=packet,
                packet_decision=decision,
                created_by="SYSTEM"
            )
            db.commit()
            print_status("Dismissal workflow processed")
        
        # 4. Refresh and check results
        db.refresh(decision)
        db.refresh(packet)
        
        print_status(f"Letter Status: {decision.letter_status}")
        print_status(f"Packet Status: {packet.detailed_status}")
        print_status(f"Operational Decision: {decision.operational_decision}")
        
        if decision.letter_status in ["READY", "SENT"]:
            letter_package = decision.letter_package or {}
            if letter_package.get("blob_url") or letter_package.get("notes"):
                print_status(f"SUCCESS: Dismissal letter generated!")
                if letter_package.get("blob_url"):
                    print_status(f"Blob URL: {letter_package.get('blob_url')[:60]}...")
                return True
            else:
                print_status(f"Letter package: {letter_package}")
                return True  # Even if no blob_url, if status is READY/SENT, it worked
        else:
            print_status(f"WARNING: Letter status is {decision.letter_status}")
            return False
            
    except Exception as e:
        print_status(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False

def main():
    print("="*80)
    print("LIVE LETTER GENERATION END-TO-END TEST")
    print("="*80)
    print(f"Test Date: {datetime.now().isoformat()}")
    
    # Use dev URL if not configured
    base_url = settings.lettergen_base_url
    if not base_url:
        base_url = "https://dev-wiser-letter-generatorv2.azurewebsites.net"
        print(f"LetterGen Base URL: {base_url} (using dev as default)")
        # Temporarily set it
        settings.lettergen_base_url = base_url
    else:
        print(f"LetterGen Base URL: {base_url}")
    
    db = SessionLocal()
    try:
        results = []
        
        # Test all workflows
        results.append(("AFFIRM", test_affirm_workflow(db)))
        results.append(("NON_AFFIRM", test_non_affirm_workflow(db)))
        results.append(("DISMISSAL", test_dismissal_workflow(db)))
        
        # Summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        for name, passed in results:
            status = "PASS" if passed else "FAIL"
            print(f"{status}: {name} workflow")
        
        passed_count = sum(1 for _, p in results if p)
        print(f"\nTotal: {passed_count}/{len(results)} workflows completed successfully")
        
    except Exception as e:
        print(f"\nFATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

