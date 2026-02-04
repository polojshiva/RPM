"""
Test letter generation with existing packets in database
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from sqlalchemy.orm import Session
import uuid
import asyncio

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_decision_db import PacketDecisionDB
from app.services.utn_handlers import UtnSuccessHandler
from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
from app.config.settings import settings

def print_status(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def find_packets_with_decisions(db: Session):
    """Find existing packets that have decisions"""
    packets = db.query(PacketDB).join(PacketDecisionDB).filter(
        PacketDecisionDB.is_active == True
    ).limit(10).all()
    
    return packets

def test_existing_packet_letter_gen(db: Session, packet: PacketDB):
    """Test letter generation for an existing packet"""
    print(f"\n{'='*80}")
    print(f"Testing Packet: {packet.external_id} (packet_id={packet.packet_id})")
    print(f"{'='*80}")
    
    # Get decision
    decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).order_by(PacketDecisionDB.created_at.desc()).first()
    
    if not decision:
        print_status("No active decision found")
        return False
    
    print_status(f"Decision: {decision.decision_outcome}, UTN Status: {decision.utn_status}, Letter Status: {decision.letter_status}")
    
    # Get document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id
    ).first()
    
    if not document:
        print_status("No document found")
        return False
    
    # If decision is AFFIRM/NON_AFFIRM and has UTN but no letter, trigger letter generation
    if decision.decision_outcome in ['AFFIRM', 'NON_AFFIRM']:
        if decision.utn_status == 'SUCCESS' and decision.letter_status not in ['READY', 'SENT']:
            print_status("UTN exists but letter not generated. Triggering letter generation...")
            
            # Determine letter type
            letter_type = 'affirmation' if decision.decision_outcome == 'AFFIRM' else 'non-affirmation'
            
            try:
                letter_service = LetterGenerationService(db)
                letter_metadata = letter_service.generate_letter(
                    packet=packet,
                    packet_decision=decision,
                    packet_document=document,
                    letter_type=letter_type
                )
                
                # Update decision
                from app.services.workflow_orchestrator import WorkflowOrchestratorService
                decision.letter_status = 'READY'
                decision.letter_package = letter_metadata
                decision.letter_generated_at = datetime.utcnow()
                
                WorkflowOrchestratorService.update_packet_status(
                    db=db,
                    packet=packet,
                    new_status="Generate Decision Letter - Complete"
                )
                
                db.commit()
                
                print_status(f"SUCCESS: Letter generated! Blob URL: {letter_metadata.get('blob_url', 'N/A')[:60]}...")
                print_status(f"Filename: {letter_metadata.get('filename', 'N/A')}")
                return True
                
            except LetterGenerationError as e:
                print_status(f"Letter generation failed: {str(e)}")
                decision.letter_status = 'FAILED'
                decision.letter_package = {"error": {"message": str(e)}}
                db.commit()
                return False
        elif decision.letter_status in ['READY', 'SENT']:
            print_status(f"Letter already generated: {decision.letter_status}")
            letter_package = decision.letter_package or {}
            if letter_package.get('blob_url'):
                print_status(f"Blob URL: {letter_package.get('blob_url')[:60]}...")
            return True
        else:
            print_status(f"Waiting for UTN. Current UTN status: {decision.utn_status}")
            return False
    
    # If decision is DISMISSAL
    elif decision.decision_outcome == 'DISMISSAL':
        if decision.letter_status not in ['READY', 'SENT']:
            print_status("Dismissal decision found but letter not generated. Triggering letter generation...")
            
            try:
                from app.services.dismissal_workflow_service import DismissalWorkflowService
                DismissalWorkflowService.process_dismissal(
                    db=db,
                    packet=packet,
                    packet_decision=decision,
                    created_by="SYSTEM"
                )
                db.commit()
                
                db.refresh(decision)
                print_status(f"SUCCESS: Dismissal letter generated! Status: {decision.letter_status}")
                return True
                
            except Exception as e:
                print_status(f"Dismissal letter generation failed: {str(e)}")
                import traceback
                traceback.print_exc()
                db.rollback()
                return False
        else:
            print_status(f"Dismissal letter already generated: {decision.letter_status}")
            return True
    
    return False

def main():
    print("="*80)
    print("TESTING LETTER GENERATION WITH EXISTING PACKETS")
    print("="*80)
    print(f"Test Date: {datetime.now().isoformat()}")
    
    # Use dev URL if not configured
    base_url = settings.lettergen_base_url
    if not base_url:
        base_url = "https://dev-wiser-letter-generatorv2.azurewebsites.net"
        print(f"LetterGen Base URL: {base_url} (using dev as default)")
        settings.lettergen_base_url = base_url
    else:
        print(f"LetterGen Base URL: {base_url}")
    
    db = SessionLocal()
    try:
        # Find existing packets with decisions
        packets = find_packets_with_decisions(db)
        
        if not packets:
            print("\nNo packets with decisions found. Creating test packet...")
            # Create a simple test packet
            now = datetime.now(timezone.utc)
            decision_tracking_id = uuid.uuid4()
            
            packet = PacketDB(
                decision_tracking_id=decision_tracking_id,
                external_id=f"TEST-LETTER-{now.strftime('%Y%m%d-%H%M%S')}",
                channel_type_id=1,
                beneficiary_name="Test Patient",
                beneficiary_mbi="1S2A3B4C5D6E7F8G9H",
                provider_name="Test Provider",
                provider_npi="1234567890",
                submission_type="Standard",
                service_type="Prior Authorization",
                received_date=now,
                due_date=now,
                detailed_status="Pending - UTN",
                created_at=now,
                updated_at=now
            )
            db.add(packet)
            db.flush()
            
            document = PacketDocumentDB(
                external_id=f"DOC-{packet.packet_id}",
                packet_id=packet.packet_id,
                file_name="test.pdf",
                document_unique_identifier=f"TEST-{packet.packet_id}",
                file_size="1024",
                page_count=1,
                document_type_id=1,
                status_type_id=1,
                uploaded_at=now,
                created_at=now,
                updated_at=now
            )
            db.add(document)
            db.flush()
            
            decision = PacketDecisionDB(
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                decision_type="APPROVE",
                decision_outcome="AFFIRM",
                decision_subtype="STANDARD_PA",
                part_type="B",
                clinical_decision="AFFIRM",
                operational_decision="PENDING",
                utn="UTN-TEST-12345",
                utn_status="SUCCESS",
                utn_received_at=now,
                is_active=True,
                created_by="SYSTEM",
                created_at=now
            )
            db.add(decision)
            db.commit()
            
            print_status(f"Created test packet: {packet.external_id}")
            packets = [packet]
        
        print(f"\nFound {len(packets)} packet(s) with decisions")
        
        results = []
        for packet in packets:
            result = test_existing_packet_letter_gen(db, packet)
            results.append((packet.external_id, result))
        
        # Summary
        print(f"\n{'='*80}")
        print("TEST SUMMARY")
        print(f"{'='*80}")
        for external_id, passed in results:
            status = "PASS" if passed else "FAIL"
            print(f"{status}: {external_id}")
        
        passed_count = sum(1 for _, p in results if p)
        print(f"\nTotal: {passed_count}/{len(results)} packets completed letter generation")
        
    except Exception as e:
        print(f"\nFATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()



